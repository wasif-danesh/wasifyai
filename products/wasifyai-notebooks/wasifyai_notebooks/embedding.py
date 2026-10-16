# SPDX-License-Identifier: Apache-2.0
# Adapted from SurfSense (Apache-2.0), surfsense_local/backend/modules/embedding/{pooling,encoder,
# bundled}.py, commit 622c1ded8. See ../PROVENANCE.md.
"""Text to vectors, in process on the processor (ONNX, no torch), as the model's spec says."""

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
