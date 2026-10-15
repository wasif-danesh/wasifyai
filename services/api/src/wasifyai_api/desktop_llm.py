"""The language engine's and the chat model's routes for the window (stage D, D1 and D2): is the
engine installed, which model is chosen, what can be chosen, and a short try-it."""

import asyncio
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from wasifyai_platform_sdk import Identity, RunError

from wasifyai_api.desktop_fit import assess_fit, need_of_language
from wasifyai_api.desktop_language import CONTEXTS, DEFAULT_CONTEXT, LanguageService
from wasifyai_api.identity import get_identity

router = APIRouter(prefix="/desktop", tags=["desktop"])


def _server(request: Request) -> Any:
    server = getattr(request.app.state, "llama_server", None)
    if server is None:
        raise HTTPException(404, "not available in this deployment")
    return server


def _language(request: Request) -> LanguageService:
    svc = getattr(request.app.state, "desktop_language", None)
    if svc is None:
        raise HTTPException(404, "not available in this deployment")
    return svc


@router.get("/language-engine")
async def language_engine(request: Request, _: Identity = Depends(get_identity)) -> dict[str, Any]:
    return _server(request).state()


@router.post("/language-engine/stop")
async def stop_language_engine(
    request: Request, _: Identity = Depends(get_identity)
) -> dict[str, bool]:
    return {"stopped": await _server(request).stop()}


# ---- the chat model ---------------------------------------------------------------------------


@router.get("/language")
async def get_language(request: Request, _: Identity = Depends(get_identity)) -> dict[str, Any]:
    """What is chosen, and what can be: found files (with whether each fits, at the chosen context)
    and the models of running tools."""
    svc = _language(request)
    discovery = svc.discovery
    sel = svc.selected
    context = sel.context if sel else DEFAULT_CONTEXT
    machine = await svc.machine()
    files: list[dict[str, Any]] = []
    servers: list[dict[str, Any]] = []
    if discovery is not None:
        state = discovery.state()
        for item in state["items"]:
            if item["kind"] != "language" or item["format"] != "gguf":
                continue
            fit = None
            if machine is not None and item["state"] != "unsupported":
                need = need_of_language(
                    item["size"], item["layers"], item["kv_heads"], item["head_dim"],
                    item["context"], chosen=context,
                )  # fmt: skip
                fit = assess_fit(need, machine).public()
            files.append({**item, "fit": fit or item["fit"], "chosen": bool(
                sel and sel.kind == "file" and sel.path == item["path"]
            )})  # fmt: skip
        for s in state["servers"]:
            for name in s.get("models", []):
                servers.append({
                    "tool": s["tool"], "title": s["title"], "url": s["url"], "model": name,
                    "chosen": bool(sel and sel.kind == "server" and sel.url == s["url"]
                                   and sel.model == name),
                })  # fmt: skip
    return {
        "selected": sel.public() if sel else None,
        "contexts": list(CONTEXTS),
        "engine": svc.llama.state(),
        "files": files,
        "servers": servers,
    }


class Choice(BaseModel):
    item_id: str | None = None  # a found file (discovery)
    server: dict[str, str] | None = None  # {"tool", "url", "model"} of a running tool
    context: int = Field(DEFAULT_CONTEXT)
    clear: bool = False


@router.put("/language")
async def choose_language(
    body: Choice, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    svc = _language(request)
    if body.clear:
        await svc.clear()
        return {"selected": None}
    discovery = svc.discovery
    if discovery is None:
        raise HTTPException(409, "Finding models is not available.")
    if body.item_id:
        item = next((i for i in discovery.items if i.id == body.item_id), None)
        if item is None or item.kind != "language" or item.format != "gguf":
            raise HTTPException(404, "That model is not in the list. Look again and choose it.")
        if not svc.llama.installed:
            raise HTTPException(409, "Set up the language engine in Settings first.")
        if item.state == "unsupported":
            raise HTTPException(409, item.reason)
        machine = await svc.machine()
        if machine is not None:
            fit = svc.fit_for(item.size, item, machine, body.context)
            if fit.verdict == "too_big":
                raise HTTPException(409, fit.reason)
        await svc.select_file(Path(item.path), item.name, body.context)
    elif body.server:
        tool, url, model = (body.server.get(k, "") for k in ("tool", "url", "model"))
        known = next(
            (s for s in discovery.servers if s["tool"] == tool and s["url"] == url), None
        )  # only a server the engine itself found, on loopback
        if known is None or model not in known.get("models", []):
            raise HTTPException(404, "That tool or model is not running. Look again.")
        await svc.select_server(tool, url, model, body.context)
    else:
        raise HTTPException(422, "Choose a found model or a model of a running tool.")
    if not discovery.running:
        asyncio.create_task(discovery.scan())  # the list shows what is chosen
    return {"selected": svc.selected.public() if svc.selected else None}


class TryIt(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)


@router.post("/language/try")
async def try_language(
    body: TryIt, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    """Ask the chosen model one short question: the window's "Try it", and the proof that the
    engine, the model and the computer work together. It does not touch any creation."""
    svc = _language(request)
    started = time.monotonic()
    try:
        async with svc.session() as route:
            client = AsyncOpenAI(base_url=route.base_url, api_key="none", max_retries=0)
            r = await client.chat.completions.create(
                model=route.model,
                messages=[{"role": "user", "content": body.prompt}],
                max_tokens=128,
                temperature=0.2,
            )
    except RunError as exc:
        raise HTTPException(409, exc.message) from None
    except Exception:
        raise HTTPException(
            502, "The model did not answer. Try again, or choose another."
        ) from None
    return {
        "text": (r.choices[0].message.content or "").strip(),
        "seconds": round(time.monotonic() - started, 1),
        "model": svc.selected.name if svc.selected else "",
    }
