# SPDX-License-Identifier: Apache-2.0
# Adapted from SurfSense (Apache-2.0), surfsense_local/backend/modules/embedding/{pooling,encoder,
# bundled}.py, commit 622c1ded8. See ../PROVENANCE.md.
"""Text to vectors, in process on the processor (ONNX, no torch), as the model's spec says."""

import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

import numpy as np


class Purpose(StrEnum):
    """Asymmetric models embed a question and a passage differently."""

    QUERY = "query"
    DOCUMENT = "document"


class Pooling(StrEnum):
    CLS = "cls"
    MEAN = "mean"
    LAST = "last"


@dataclass(frozen=True)
class EmbedderSpec:
    """Everything that decides what a vector means. An index records this next to its vectors."""

    id: str
    dimension: int
    pooling: Pooling
    normalize: bool
    max_tokens: int
    # How much of the order meaning owns: the middle of a plateau SurfSense measured for bge
    # (0.6 to 0.65), not a default.
    semantic_weight: float
    query_prefix: str = ""
    document_prefix: str = ""
    batch: int = 32


BGE_SMALL = EmbedderSpec(
    id="bge-small-en-v1.5",
    dimension=384,
    pooling=Pooling.CLS,
    normalize=True,
    max_tokens=512,
    semantic_weight=0.65,
)


class Embedder(Protocol):
    """What the pipeline needs of an embedder; tests give it a fake."""

    spec: EmbedderSpec

    def embed(self, texts: list[str], purpose: Purpose) -> list[list[float]]: ...


def pool(pooling: Pooling, output: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """One vector per text from the per-token output. Padding is on the right."""
    if pooling is Pooling.CLS:
        return output[:, 0]
    if pooling is Pooling.MEAN:
        weights = mask[:, :, None].astype(output.dtype)
        return (output * weights).sum(axis=1) / np.maximum(weights.sum(axis=1), 1)
    last = mask.sum(axis=1) - 1
    return output[np.arange(output.shape[0]), last]


class OnnxEmbedder:
    """An ONNX embedding model and its tokenizer file, loaded when first used."""

    def __init__(self, spec: EmbedderSpec, weights: Path, tokenizer: Path):
        self.spec = spec
        self._weights = weights
        self._tokenizer = tokenizer
        self._loaded: tuple[Any, Any] | None = None

    def _load(self) -> tuple[Any, Any]:
        if self._loaded is None:
            import onnxruntime as ort
            from tokenizers import Tokenizer

            encoder = Tokenizer.from_file(str(self._tokenizer))
            encoder.enable_truncation(max_length=self.spec.max_tokens)
            encoder.enable_padding()
            session = ort.InferenceSession(str(self._weights), providers=["CPUExecutionProvider"])
            self._loaded = (session, encoder)
        return self._loaded

    def embed(self, texts: list[str], purpose: Purpose) -> list[list[float]]:
        prefix = self.spec.query_prefix if purpose is Purpose.QUERY else self.spec.document_prefix
        prefixed = [prefix + t for t in texts]
        out: list[list[float]] = []
        for start in range(0, len(prefixed), self.spec.batch):
            out.extend(self._batch(prefixed[start : start + self.spec.batch]))
        wrong = next((len(v) for v in out if len(v) != self.spec.dimension), None)
        if wrong is not None:
            raise ValueError(
                f"{self.spec.id} returned {wrong} dimensions "
                f"where its spec says {self.spec.dimension}"
            )
        return out

    def _batch(self, texts: list[str]) -> list[list[float]]:
        session, encoder = self._load()
        encoded = encoder.encode_batch(texts)
        feed = {
            "input_ids": np.array([e.ids for e in encoded], dtype=np.int64),
            "attention_mask": np.array([e.attention_mask for e in encoded], dtype=np.int64),
        }
        # Some exports drop token_type_ids; feed it only if the graph asks.
        if "token_type_ids" in {i.name for i in session.get_inputs()}:
            feed["token_type_ids"] = np.array([e.type_ids for e in encoded], dtype=np.int64)
        output = session.run(None, feed)[0]
        pooled = pool(self.spec.pooling, output, feed["attention_mask"])
        if self.spec.normalize:
            pooled = pooled / np.linalg.norm(pooled, axis=1, keepdims=True)
        return pooled.astype(np.float32).tolist()


GATEWAY_ALIAS = "creation-embedder"  # bge-m3, multilingual, 1024 dimensions (model_defaults.yaml)


class EmbedError(Exception):
    """The gateway's embedder did not answer; `str(e)` is a sentence safe to show."""


class GatewayEmbedder:
    """The platform's embedder, asked through the gateway (rule 5: all model calls go through
    LiteLLM, by alias). Synchronous like the other embedder, because the engine and the reading
    worker call it from threads. A multilingual model (the alias is bge-m3), so a notebook in any
    language is found; it needs no instruction prefix for a question."""

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        *,
        model: str = GATEWAY_ALIAS,
        dimension: int = 1024,
        batch: int = 32,
        timeout_s: float = 60.0,
        retries: int = 3,
        client: Any = None,
    ):
        self.spec = EmbedderSpec(
            id=f"gateway:{model}",
            dimension=dimension,
            pooling=Pooling.CLS,  # not used: the gateway pools
            normalize=True,
            max_tokens=512,
            semantic_weight=0.65,
            batch=batch,
        )
        self._model = model
        self._url = base_url.rstrip("/") + "/v1/embeddings"
        self._headers = {"authorization": f"Bearer {api_key}"} if api_key else {}
        self._timeout = timeout_s
        self._retries = retries
        self._client = client

    def _post(self, texts: list[str]) -> tuple[list[list[float]], int]:
        import httpx

        client = self._client or httpx.Client(timeout=self._timeout)
        last = "The embedding service did not answer."
        for attempt in range(self._retries):
            try:
                res = client.post(
                    self._url,
                    headers=self._headers,
                    json={"model": self._model, "input": texts, "encoding_format": "float"},
                )
            except httpx.TransportError:
                last = "The embedding service could not be reached."
            else:
                if res.status_code < 400:
                    body = res.json()
                    data = sorted(body["data"], key=lambda d: d["index"])
                    tokens = int((body.get("usage") or {}).get("prompt_tokens") or 0)
                    return [d["embedding"] for d in data], tokens
                last = f"The embedding service answered {res.status_code}."
                if res.status_code < 500 and res.status_code != 429:
                    break  # a refusal repeats itself
            time.sleep(min(0.5 * 2**attempt, 4.0))
        raise EmbedError(last)

    def embed_counted(self, texts: list[str], purpose: Purpose) -> tuple[list[list[float]], int]:
        """The vectors, and the tokens the gateway counted (for the usage record)."""
        out: list[list[float]] = []
        tokens = 0
        for start in range(0, len(texts), self.spec.batch):
            vectors, used = self._post(texts[start : start + self.spec.batch])
            out.extend(vectors)
            tokens += used
        wrong = next((len(v) for v in out if len(v) != self.spec.dimension), None)
        if wrong is not None:
            raise EmbedError(
                f"The embedding model returned {wrong} dimensions where {self.spec.dimension} "
                "were expected."
            )
        return out, tokens

    def embed(self, texts: list[str], purpose: Purpose) -> list[list[float]]:
        return self.embed_counted(texts, purpose)[0]


def embed_counted(
    embedder: Any, texts: list[str], purpose: Purpose
) -> tuple[list[list[float]], int]:
    """The vectors and the tokens spent; an embedder that does not count (the local one) spends
    none that are billed."""
    counted = getattr(embedder, "embed_counted", None)
    if counted is not None:
        return counted(texts, purpose)  # type: ignore[no-any-return]
    return embedder.embed(texts, purpose), 0
