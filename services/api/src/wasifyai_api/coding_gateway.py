"""The coding sessions' model gateway (ADR-0102, decision 4; stage C1b of
docs/v2-coding-agent-start-plan.md).

The Agent Server runs inside a sandbox whose network reaches this computer only, and it must never
hold a model key. So it is given this engine's own address and a **token for one session**. Every
model call of that session comes here:

    POST /coding-gateway/v1/messages             the Messages API (a model of shape "anthropic")
    POST /coding-gateway/v1/messages/count_tokens
    POST /coding-gateway/v1/chat/completions     chat completions (a model of shape "openai")

What happens to a call:

    the token      stands for one session of one person (it is the route's identity: the tenant,
                   the product and the person come from it). It is made here, kept in memory
                   only, and dies with the session. An unknown token is refused
    the model      only the model the session was opened with is let through
    the limit      a session whose counted cost reached its limit is refused, in words
    the key        read from the app's secret store for this call and put on it. It is never
                   answered back, logged or written anywhere
    the body       passed on byte for byte, so the provider's prompt-cache marks arrive as the
                   Agent Server wrote them. (One exception: a streamed chat-completions call is
                   asked to report its tokens, which it otherwise would not.)
    streaming      passed through event by event, as it arrives
    the tokens     each call's tokens become usage events (rule 9), and its counted cost is added
                   to the session's
    a refusal      when the model declines (`stop_reason: "refusal"`), the answer the Agent
                   Server gets is a plain message with no tool call, which ends its turn; what
                   the model said is kept for the product to show. Left alone, the Agent Server
                   sees an empty answer, nudges three times and ends "stuck" (C0 spike 2)

The models a session can run on, their prices and where their keys are kept are in
`coding_models.yaml`. Nothing here imports OpenHands' packages, and nothing here is specific to
one provider's SDK: it is HTTP in and HTTP out.
"""

import asyncio
import contextlib
import json
import logging
import secrets as random
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from wasifyai_platform_sdk import SecretStore
from wasifyai_platform_sdk.usage import (
    LLM_INPUT_TOKENS,
    LLM_OUTPUT_TOKENS,
    UsageEvent,
    UsageRecorder,
    record_safely,
)

from wasifyai_api.services import services_of

log = logging.getLogger(__name__)

MODELS_FILE = Path(__file__).with_name("coding_models.yaml")
PREFIX = "/coding-gateway"
ANTHROPIC, OPENAI = "anthropic", "openai"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_LIMIT_USD = 5.0  # for one session; the person can raise it for a session they start
CAPABILITY = "code.agent"  # what the usage events say the tokens were for
TIMEOUT = httpx.Timeout(600.0, connect=10.0)
DECLINED = "The model declined this request."
OVER_LIMIT = "This session reached its cost limit of ${limit:.2f}. Raise the limit to go on."
NO_KEY = "No key is saved for {title}. Save one in Settings, under Your keys."


class GatewayError(Exception):
    """A request the gateway cannot serve. `message` is safe to show."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass(frozen=True)
class ModelRoute:
    """One entry of `coding_models.yaml`."""

    id: str
    title: str
    where: str  # "cloud" or "this-computer"
    shape: str  # ANTHROPIC or OPENAI
    provider: str
    engine_model: str
    provider_model: str
    upstream: str
    secret: str
    price: dict[str, float]
    engine_settings: dict[str, Any]


def load_models(
    path: Path = MODELS_FILE, *, ollama_url: str = ""
) -> tuple[str, dict[str, ModelRoute]]:
    """The default model's id and every model, from the file."""
    data = yaml.safe_load(path.read_text())
    models: dict[str, ModelRoute] = {}
    for model_id, m in data["models"].items():
        upstream = str(m["upstream"])
        if upstream == "ollama":
            upstream = ollama_url.rstrip("/") + "/v1"
        if m["shape"] not in (ANTHROPIC, OPENAI):
            raise ValueError(f"{path.name}: {model_id} has a shape the gateway does not know")
        models[model_id] = ModelRoute(
            id=model_id,
            title=str(m["title"]),
            where=str(m.get("where") or "cloud"),
            shape=str(m["shape"]),
            provider=str(m.get("provider") or m["shape"]),
            engine_model=str(m["engine_model"]),
            provider_model=str(m["provider_model"]),
            upstream=upstream.rstrip("/"),
            secret=str(m.get("secret") or ""),
            price={k: float(v) for k, v in (m.get("price") or {}).items()},
            engine_settings=dict(m.get("engine_settings") or {}),
        )
    default = str(data["default"])
    if default not in models:
        raise ValueError(f"{path.name}: the default model is not in the list")
    return default, models


@dataclass(frozen=True)
class Grant:
    """What a place needs to point an engine at the gateway for one session. `token` goes where
    the engine expects a key. Nothing here is a key."""

    token: str
    model: str  # our id for the model
    engine_model: str
    base_url: str
    shape: str
    engine_settings: dict[str, Any]


@dataclass(frozen=True)
class Call:
    """One model call, in numbers: what the product adds to the session's row."""

    session_id: str
    model: str
    input_tokens: int  # everything that went in: fresh, written to the cache and read from it
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    usd: float
    status: int
    refused: bool = False


@dataclass
class _Session:
    tenant_id: str
    product_id: str
    user_id: str
    session_id: str
    route: ModelRoute
    limit_usd: float
    spent_usd: float = 0.0
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    refusal: dict[str, str] | None = None  # the last refusal nobody has taken yet
    over_limit: bool = False  # a call was refused at the limit and nobody has asked yet
    on_call: Callable[[Call], Awaitable[None] | None] | None = None
    tokens: list[str] = field(default_factory=list)


def cost_of(usage: dict[str, int], price: dict[str, float]) -> float:
    """What a call cost as we count it, in US dollars."""
    if not price:
        return 0.0
    write_1h = usage.get("cache_write_1h", 0)
    write_5m = usage.get("cache_write", 0) - write_1h
    usd = (
        usage.get("input", 0) * price.get("input", 0.0)
        + usage.get("output", 0) * price.get("output", 0.0)
        + usage.get("cache_read", 0) * price.get("cache_read", price.get("input", 0.0))
        + write_5m * price.get("cache_write", price.get("input", 0.0))
        + write_1h * price.get("cache_write_1h", price.get("cache_write", price.get("input", 0.0)))
    )
    return usd / 1_000_000


def _int(value: Any) -> int:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0


def anthropic_usage(usage: dict[str, Any], into: dict[str, int]) -> None:
    """Fold a Messages `usage` object into our counts. A stream reports the same call's usage
    more than once, each time with the totals so far, so the largest value of each stands."""
    seen = {
        "input": _int(usage.get("input_tokens")),
        "output": _int(usage.get("output_tokens")),
        "cache_read": _int(usage.get("cache_read_input_tokens")),
        "cache_write": _int(usage.get("cache_creation_input_tokens")),
        "cache_write_1h": _int((usage.get("cache_creation") or {}).get("ephemeral_1h_input_tokens"))
        if isinstance(usage.get("cache_creation"), dict)
        else 0,
    }
    for key, n in seen.items():
        into[key] = max(into.get(key, 0), n)


def openai_usage(usage: dict[str, Any], into: dict[str, int]) -> None:
    """Fold a chat-completions `usage` object into our counts. Its prompt count includes what
    was read from a cache."""
    details = usage.get("prompt_tokens_details")
    cached = _int(details.get("cached_tokens")) if isinstance(details, dict) else 0
    into["input"] = max(into.get("input", 0), _int(usage.get("prompt_tokens")) - cached)
    into["cache_read"] = max(into.get("cache_read", 0), cached)
    into["output"] = max(into.get("output", 0), _int(usage.get("completion_tokens")))


def refusal_text(details: Any) -> str:
    """The plain message a refusal becomes, with the model's own explanation when it gave one."""
    said = details.get("explanation") if isinstance(details, dict) else None
    return f"{DECLINED} {said.strip()}" if isinstance(said, str) and said.strip() else DECLINED


def _error(shape: str, status: int, kind: str, message: str) -> JSONResponse:
    """An error in the shape the caller's library expects from its provider."""
    if shape == ANTHROPIC:
        body: dict[str, Any] = {"type": "error", "error": {"type": kind, "message": message}}
    else:
        body = {"error": {"message": message, "type": kind, "code": kind}}
    return JSONResponse(body, status_code=status)


# ---- a refusal turned into a plain message ------------------------------------------------------


def anthropic_refusal(body: dict[str, Any]) -> dict[str, str] | None:
    """If a whole Messages answer is a refusal, rewrite it in place into a plain message that
    ends the turn, and give what the model said."""
    if body.get("stop_reason") != "refusal":
        return None
    details = body.pop("stop_details", None)
    text = refusal_text(details)
    # what was written before the model declined is not a finished answer: it is dropped
    body["content"] = [{"type": "text", "text": text}]
    body["stop_reason"] = "end_turn"
    category = details.get("category") if isinstance(details, dict) else None
    return {"message": text, "category": str(category or "")}


def openai_refusal(body: dict[str, Any]) -> dict[str, str] | None:
    """The same for a chat-completions answer: a `refusal` in the message, or the provider's
    content filter."""
    for choice in body.get("choices") or []:
        message = choice.get("message") or {}
        said = message.get("refusal")
        if not said and choice.get("finish_reason") != "content_filter":
            continue
        text = f"{DECLINED} {said.strip()}" if isinstance(said, str) and said.strip() else DECLINED
        message["content"], message["refusal"] = text, None
        message.pop("tool_calls", None)
        choice["message"], choice["finish_reason"] = message, "stop"
        return {"message": text, "category": ""}
    return None


class _AnthropicStream:
    """A Messages stream, event by event: tokens are counted on the way, and a refusal is
    turned into one more text block and an ordinary end."""

    def __init__(self) -> None:
        self.usage: dict[str, int] = {}
        self.refusal: dict[str, str] | None = None
        self._blocks = 0

    def event(self, raw: bytes) -> bytes:
        """One server-sent event (without its blank line). Gives what to pass on."""
        data = _sse_data(raw)
        if data is None:
            return raw
        kind = data.get("type")
        if kind == "message_start":
            anthropic_usage((data.get("message") or {}).get("usage") or {}, self.usage)
        elif kind == "content_block_start":
            self._blocks = max(self._blocks, _int(data.get("index")) + 1)
        elif kind == "message_delta":
            anthropic_usage(data.get("usage") or {}, self.usage)
            delta = data.get("delta") or {}
            if delta.get("stop_reason") == "refusal":
                details = delta.pop("stop_details", None) or data.pop("stop_details", None)
                text = refusal_text(details)
                category = details.get("category") if isinstance(details, dict) else None
                self.refusal = {"message": text, "category": str(category or "")}
                delta["stop_reason"] = "end_turn"
                data["delta"] = delta
                at = self._blocks
                return b"\n\n".join(
                    [
                        _sse(
                            "content_block_start",
                            {
                                "type": "content_block_start",
                                "index": at,
                                "content_block": {"type": "text", "text": ""},
                            },
                        ),  # noqa: E501
                        _sse(
                            "content_block_delta",
                            {
                                "type": "content_block_delta",
                                "index": at,
                                "delta": {"type": "text_delta", "text": text},
                            },
                        ),  # noqa: E501
                        _sse("content_block_stop", {"type": "content_block_stop", "index": at}),
                        _sse("message_delta", data),
                    ]
                )
        return raw


class _OpenAIStream:
    """A chat-completions stream: tokens counted on the way, a refusal turned into words."""

    def __init__(self) -> None:
        self.usage: dict[str, int] = {}
        self.refusal: dict[str, str] | None = None
        self._said = ""

    def event(self, raw: bytes) -> bytes:
        data = _sse_data(raw)
        if data is None:
            return raw
        if isinstance(data.get("usage"), dict):
            openai_usage(data["usage"], self.usage)
        changed = False
        for choice in data.get("choices") or []:
            delta = choice.get("delta") or {}
            if isinstance(delta.get("refusal"), str) and delta["refusal"]:
                self._said += delta["refusal"]
            refused = choice.get("finish_reason") == "content_filter" or (
                self._said and choice.get("finish_reason")
            )
            if refused:
                text = f"{DECLINED} {self._said.strip()}".strip()
                self.refusal = {"message": text, "category": ""}
                choice["delta"] = {"content": text}
                choice["finish_reason"] = "stop"
                changed = True
        return _sse(None, data) if changed else raw


def _sse_data(raw: bytes) -> dict[str, Any] | None:
    """The JSON of an event's `data:` lines, when it has one."""
    lines = [ln[5:].lstrip() for ln in raw.split(b"\n") if ln.startswith(b"data:")]
    if not lines:
        return None
    try:
        found = json.loads(b"\n".join(lines))
    except ValueError:
        return None
    return found if isinstance(found, dict) else None


def _sse(event: str | None, data: dict[str, Any]) -> bytes:
    head = f"event: {event}\n".encode() if event else b""
    return head + b"data: " + json.dumps(data, separators=(",", ":")).encode()


# ---- the gateway --------------------------------------------------------------------------------


class CodingGateway:
    def __init__(
        self,
        *,
        secrets: SecretStore,
        usage: UsageRecorder,
        base_url: Callable[[], str],
        ollama_url: str = "",
        models: tuple[str, dict[str, ModelRoute]] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """`base_url` gives this engine's own address on loopback when it is asked (the port is
        known once the engine listens). `transport` is for tests: the provider, pretended."""
        self._secrets, self._usage, self._base_url = secrets, usage, base_url
        self.default, self.models = models or load_models(ollama_url=ollama_url)
        self.default_limit_usd = DEFAULT_LIMIT_USD  # for a session that names none
        self._by_token: dict[str, _Session] = {}
        self._by_session: dict[str, _Session] = {}
        self._http = httpx.AsyncClient(timeout=TIMEOUT, transport=transport)

    async def close(self) -> None:
        self._by_token.clear()
        self._by_session.clear()
        await self._http.aclose()

    # ---- what the product asks -----------------------------------------------------------------

    def model(self, model_id: str | None) -> ModelRoute:
        found = self.models.get(model_id or self.default)
        if found is None:
            raise GatewayError("no_such_model", "That model is not one a coding session can use.")
        return found

    async def ready(self, model_id: str | None) -> str | None:
        """Why a session cannot run on this model now, in words; None when it can."""
        route = self.model(model_id)
        if route.secret and (not self._secrets.ready or not await self._secrets.get(route.secret)):
            return NO_KEY.format(title=route.title)
        return None

    async def list_models(self) -> list[dict[str, Any]]:
        """The models, for the person to choose from: never a key, only whether one is saved."""
        out = []
        for route in self.models.values():
            out.append(
                {
                    "id": route.id,
                    "title": route.title,
                    "where": route.where,
                    "default": route.id == self.default,
                    "ready": await self.ready(route.id) is None,
                }
            )
        return out

    def open(
        self,
        *,
        tenant_id: str,
        product_id: str,
        user_id: str,
        session_id: str,
        model: str | None = None,
        spent_usd: float = 0.0,
        limit_usd: float | None = None,
        on_call: Callable[[Call], Awaitable[None] | None] | None = None,
    ) -> Grant:
        """Let one session call its model, and give what its engine is pointed at. Asked again
        for a session that is open, it gives a new token for the same count (the engine was
        started again); the earlier tokens stop working."""
        route = self.model(model)
        limit = DEFAULT_LIMIT_USD if not limit_usd or limit_usd <= 0 else float(limit_usd)
        session = self._by_session.get(session_id)
        if session is None or (session.tenant_id, session.user_id) != (tenant_id, user_id):
            session = _Session(tenant_id, product_id, user_id, session_id, route, limit, spent_usd)
            self._by_session[session_id] = session
        else:
            for old in session.tokens:
                self._by_token.pop(old, None)
            session.tokens.clear()
            session.route, session.limit_usd = route, limit
            session.spent_usd = max(session.spent_usd, spent_usd)
        session.on_call = on_call
        token = "wcg-" + random.token_urlsafe(32)
        session.tokens.append(token)
        self._by_token[token] = session
        base = self._base_url().rstrip("/") + PREFIX
        return Grant(
            token=token,
            model=route.id,
            engine_model=route.engine_model,
            # each library adds its own path: "/v1/messages" to this, "/chat/completions" to that
            base_url=base if route.shape == ANTHROPIC else base + "/v1",
            shape=route.shape,
            engine_settings=dict(route.engine_settings),
        )

    def close_session(self, session_id: str) -> None:
        session = self._by_session.pop(session_id, None)
        if session is not None:
            for token in session.tokens:
                self._by_token.pop(token, None)

    def is_open(self, session_id: str) -> bool:
        return session_id in self._by_session

    def spent(self, session_id: str) -> dict[str, Any]:
        s = self._by_session.get(session_id)
        if s is None:
            return {"usd": 0.0, "limit_usd": 0.0, "calls": 0, "input_tokens": 0, "output_tokens": 0}
        return {
            "usd": round(s.spent_usd, 6),
            "limit_usd": s.limit_usd,
            "calls": s.calls,
            "input_tokens": s.input_tokens,
            "output_tokens": s.output_tokens,
        }

    def set_limit(self, session_id: str, limit_usd: float) -> None:
        s = self._by_session.get(session_id)
        if s is not None and limit_usd > 0:
            s.limit_usd = float(limit_usd)

    def take_note(self, session_id: str) -> dict[str, Any]:
        """What the gateway saw that the engine cannot say: a refusal by the model, or a call
        refused at the cost limit. Each is given once."""
        s = self._by_session.get(session_id)
        if s is None:
            return {}
        note: dict[str, Any] = {}
        if s.refusal is not None:
            note["refusal"], s.refusal = s.refusal, None
        if s.over_limit:
            note["over_limit"], s.over_limit = OVER_LIMIT.format(limit=s.limit_usd), False
        return note

    # ---- one call --------------------------------------------------------------------------------

    def _session(self, request: Request) -> _Session | None:
        given = request.headers.get("x-api-key") or ""
        if not given:
            scheme, _, rest = request.headers.get("authorization", "").partition(" ")
            given = rest.strip() if scheme.lower() == "bearer" else ""
        return self._by_token.get(given) if given else None

    async def handle(self, request: Request, shape: str, path: str) -> Response:
        """One model call from an engine. `path` is what is added to the model's address."""
        session = self._session(request)
        if session is None:
            return _error(shape, 401, "authentication_error", "This session token is not known.")
        route = session.route
        if route.shape != shape:
            return _error(shape, 404, "not_found_error", "This session's model is not served here.")
        raw = await request.body()
        try:
            body = json.loads(raw)
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return _error(shape, 400, "invalid_request_error", "The request is not JSON.")
        if body.get("model") != route.provider_model:
            return _error(
                shape, 400, "invalid_request_error",
                f"Only {route.provider_model} is let through for this session.",
            )  # fmt: skip
        counting = path.endswith("/count_tokens")
        if not counting and session.spent_usd >= session.limit_usd:
            session.over_limit = True
            return _error(
                shape, 429, "rate_limit_error", OVER_LIMIT.format(limit=session.limit_usd)
            )
        key = ""
        if route.secret:
            key = (await self._secrets.get(route.secret) if self._secrets.ready else None) or ""
            if not key:
                return _error(shape, 401, "authentication_error", NO_KEY.format(title=route.title))
        streamed = bool(body.get("stream")) and not counting
        options = body.get("stream_options") or {}
        if shape == OPENAI and streamed and "include_usage" not in options:
            # without this a streamed call never says how many tokens it used
            body["stream_options"] = {**options, "include_usage": True}
            raw = json.dumps(body).encode()
        # plain, not compressed: a stream is read and passed on event by event as it arrives
        headers = {"content-type": "application/json", "accept-encoding": "identity"}
        if shape == ANTHROPIC:
            headers["x-api-key"] = key
            headers["anthropic-version"] = (
                request.headers.get("anthropic-version") or ANTHROPIC_VERSION
            )
            if request.headers.get("anthropic-beta"):
                headers["anthropic-beta"] = request.headers["anthropic-beta"]
        else:
            headers["authorization"] = f"Bearer {key or 'none'}"
        url = route.upstream + path
        try:
            upstream = await self._http.send(
                self._http.build_request("POST", url, content=raw, headers=headers), stream=True
            )
        except httpx.HTTPError as e:
            log.warning("the model of a coding session could not be reached: %s", type(e).__name__)
            return _error(shape, 502, "api_error", f"{route.title} could not be reached.")
        kind = upstream.headers.get("content-type", "application/json")
        if "text/event-stream" in kind and upstream.status_code == 200:
            return StreamingResponse(
                self._stream(session, upstream, shape),
                status_code=200,
                media_type="text/event-stream",
                headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
            )
        try:
            data = await upstream.aread()
        except httpx.HTTPError:
            return _error(shape, 502, "api_error", f"{route.title} stopped answering.")
        finally:
            await upstream.aclose()
        usage: dict[str, int] = {}
        refusal = None
        if upstream.status_code >= 400:
            # the provider's own words for what it refused (never the request, never a key)
            log.warning(
                "a coding session's model answered %s: %s",
                upstream.status_code,
                data[:500].decode(errors="replace"),
            )
        if upstream.status_code == 200 and not counting:
            try:
                answer = json.loads(data)
            except ValueError:
                answer = None
            if isinstance(answer, dict):
                if shape == ANTHROPIC:
                    anthropic_usage(answer.get("usage") or {}, usage)
                    refusal = anthropic_refusal(answer)
                else:
                    openai_usage(answer.get("usage") or {}, usage)
                    refusal = openai_refusal(answer)
                if refusal is not None:
                    data = json.dumps(answer).encode()
        if not counting:
            await self._count(session, usage, upstream.status_code, refusal)
        return Response(data, status_code=upstream.status_code, media_type=kind)

    async def _stream(
        self, session: _Session, upstream: httpx.Response, shape: str
    ) -> AsyncIterator[bytes]:
        reader = _AnthropicStream() if shape == ANTHROPIC else _OpenAIStream()
        buffer = b""
        try:
            async for chunk in upstream.aiter_raw():
                buffer += chunk.replace(b"\r\n", b"\n")
                while b"\n\n" in buffer:
                    event, buffer = buffer.split(b"\n\n", 1)
                    yield reader.event(event) + b"\n\n"
            if buffer:
                yield reader.event(buffer)
        except httpx.HTTPError:
            log.warning("a coding session's model stream broke off")
        finally:
            await upstream.aclose()
            await self._count(session, reader.usage, 200, reader.refusal)

    async def _count(
        self, session: _Session, usage: dict[str, int], status: int, refusal: dict[str, str] | None
    ) -> None:
        """Add one call to its session and write its usage events."""
        route = session.route
        usd = cost_of(usage, route.price)
        cache_read, cache_write = usage.get("cache_read", 0), usage.get("cache_write", 0)
        prompt = usage.get("input", 0) + cache_read + cache_write
        output = usage.get("output", 0)
        session.calls += 1
        session.spent_usd += usd
        session.input_tokens += prompt
        session.output_tokens += output
        if refusal is not None:
            session.refusal = refusal
        meta = {
            "capability": CAPABILITY, "alias": route.id, "provider": route.provider,
            "cached_tokens": cache_read, "cache_write_tokens": cache_write,
            "session_id": session.session_id, "usd": round(usd, 6),
        }  # fmt: skip
        for kind, n in ((LLM_INPUT_TOKENS, prompt), (LLM_OUTPUT_TOKENS, output)):
            if n:
                await record_safely(
                    self._usage,
                    UsageEvent(
                        tenant_id=session.tenant_id, product_id=session.product_id,
                        user_id=session.user_id, kind=kind, quantity=n, unit="tokens", meta=meta,
                    ),
                )  # fmt: skip
        if session.on_call is not None:
            call = Call(
                session.session_id, route.id, prompt, output, cache_read, cache_write, usd,
                status, refusal is not None,
            )  # fmt: skip
            try:
                told = session.on_call(call)
                if told is not None:
                    await told
            except Exception:
                log.exception("a coding session's cost could not be written down")


@contextlib.asynccontextmanager
async def serve_alone(gateway: CodingGateway) -> AsyncIterator[str]:
    """The gateway on a loopback port of its own, without the rest of the engine: for the
    evaluation runner and the tests against the real coding engine. Gives its address; the
    gateway's `base_url` should answer the same."""
    import socket

    import uvicorn
    from fastapi import FastAPI

    from wasifyai_api.services import ApiServices

    app = FastAPI()
    app.state.services = ApiServices(coding_gateway=gateway)
    app.include_router(router)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))  # loopback only
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    task = asyncio.ensure_future(server.serve(sockets=[sock]))
    try:
        while not server.started:  # noqa: ASYNC110 - uvicorn offers no event for this
            await asyncio.sleep(0.02)
        yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    finally:
        server.should_exit = True
        await task


# ---- the routes ---------------------------------------------------------------------------------

router = APIRouter(prefix=PREFIX, tags=["coding-gateway"], include_in_schema=False)


def _gateway(request: Request) -> CodingGateway:
    gateway = services_of(request).coding_gateway
    if gateway is None:
        raise HTTPException(404, "not available in this deployment")
    return gateway


@router.post("/v1/messages")
async def messages(request: Request) -> Response:
    return await _gateway(request).handle(request, ANTHROPIC, "/v1/messages")


@router.post("/v1/messages/count_tokens")
async def count_tokens(request: Request) -> Response:
    return await _gateway(request).handle(request, ANTHROPIC, "/v1/messages/count_tokens")


@router.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    return await _gateway(request).handle(request, OPENAI, "/chat/completions")
