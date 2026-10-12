"""LiteLLM's model-management API, as the admin area uses it (ADR-0025).

`ModelBackend` is what the rest of the code depends on; `LiteLLMBackend` talks to a real proxy and
`InMemoryModelBackend` stands in for it in tests. Neither ever returns a provider API key."""

import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


class BackendError(Exception):
    """The model backend refused or could not be reached. The message is safe to log."""


@dataclass
class ModelEntry:
    id: str
    alias: str
    info: dict[str, Any] = field(default_factory=dict)  # model_info (ours is under "wasifyai")

    @property
    def wasifyai(self) -> dict[str, Any]:
        return self.info.get("wasifyai") or {}


@dataclass
class CallResult:
    ok: bool
    latency_ms: int
    sample: str = ""
    error: str = ""


class ModelBackend(Protocol):
    async def list(self) -> list[ModelEntry]: ...
    async def add(self, alias: str, params: dict[str, Any], info: dict[str, Any]) -> None: ...
    async def update(self, model_id: str, params: dict[str, Any], info: dict[str, Any]) -> None: ...
    async def delete(self, model_id: str) -> None: ...
    async def call(self, alias: str, kind: str) -> CallResult: ...


class LiteLLMBackend:
    def __init__(self, base_url: str, api_key: str, client: httpx.AsyncClient | None = None):
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(90.0, connect=5.0),
        )

    async def _send(self, method: str, path: str, **kw: Any) -> httpx.Response:
        try:
            res = await self._client.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise BackendError(f"model gateway unreachable ({type(exc).__name__})") from exc
        if res.status_code >= 400:
            raise BackendError(f"model gateway answered {res.status_code} for {method} {path}")
        return res

    async def list(self) -> list[ModelEntry]:
        data = (await self._send("GET", "/model/info")).json().get("data", [])
        return [
            ModelEntry(
                id=str(m.get("model_info", {}).get("id", "")),
                alias=m.get("model_name", ""),
                info=m.get("model_info", {}),
            )
            for m in data
        ]

    async def add(self, alias: str, params: dict[str, Any], info: dict[str, Any]) -> None:
        await self._send(
            "POST",
            "/model/new",
            json={"model_name": alias, "litellm_params": params, "model_info": info},
        )

    async def update(self, model_id: str, params: dict[str, Any], info: dict[str, Any]) -> None:
        # LiteLLM applies litellm_params on POST /model/update but ignores model_info there; the
        # PATCH route applies model_info (replacing our whole "wasifyai" block, which is what we
        # want).
        await self._send(
            "POST",
            "/model/update",
            json={"model_info": {"id": model_id}, "litellm_params": params},
        )
        await self._send("PATCH", f"/model/{model_id}/update", json={"model_info": info})

    async def delete(self, model_id: str) -> None:
        await self._send("POST", "/model/delete", json={"id": model_id})

    async def call(self, alias: str, kind: str) -> CallResult:
        started = time.monotonic()
        try:
            if kind == "embedding":
                res = await self._client.post(
                    "/v1/embeddings", json={"model": alias, "input": "test"}
                )
            else:
                res = await self._client.post(
                    "/v1/chat/completions",
                    json={
                        "model": alias,
                        "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
                        "max_tokens": 200,
                    },
                )
        except httpx.HTTPError as exc:
            return CallResult(False, _ms(started), error=f"unreachable ({type(exc).__name__})")
        if res.status_code >= 400:
            return CallResult(False, _ms(started), error=_error_text(res))
        body = res.json()
        if kind == "embedding":
            vector = (body.get("data") or [{}])[0].get("embedding") or []
            return CallResult(bool(vector), _ms(started), sample=f"{len(vector)} dimensions")
        text = (((body.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
        return CallResult(True, _ms(started), sample=text.strip()[:80])


def _ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)


def _error_text(res: httpx.Response) -> str:
    try:
        err = res.json().get("error", {})
        msg = err.get("message") if isinstance(err, dict) else str(err)
    except ValueError:
        msg = res.text
    return f"{res.status_code}: {msg or 'error'}"[:400]


class InMemoryModelBackend:
    """Behaves like the proxy for tests: a dict of entries; `fail` makes `call` fail."""

    def __init__(self) -> None:
        self.entries: dict[str, tuple[str, dict[str, Any], dict[str, Any]]] = {}
        self.calls: list[str] = []
        self.fail: set[str] = set()  # aliases whose calls fail

    async def list(self) -> list[ModelEntry]:
        return [ModelEntry(i, a, dict(info)) for i, (a, _, info) in self.entries.items()]

    async def add(self, alias: str, params: dict[str, Any], info: dict[str, Any]) -> None:
        if info["id"] in self.entries:
            raise BackendError("duplicate id")
        self.entries[info["id"]] = (alias, dict(params), dict(info))

    async def update(self, model_id: str, params: dict[str, Any], info: dict[str, Any]) -> None:
        alias = self.entries[model_id][0]
        self.entries[model_id] = (alias, dict(params), {**info, "id": model_id})

    async def delete(self, model_id: str) -> None:
        self.entries.pop(model_id, None)

    async def call(self, alias: str, kind: str) -> CallResult:
        self.calls.append(alias)
        if alias in self.fail or any(
            a in self.fail for a, *_ in self.entries.values() if a == alias
        ):
            return CallResult(False, 5, error="401: invalid api key")
        return CallResult(True, 5, sample="ok")
