"""Settings > Other apps > "Tools from other apps" (ADR-0070 decision 2): the person, and only the
person in the window, adds, tests, changes and removes servers. No connection or key may."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from wasifyai_platform_sdk.identity import Identity

from wasifyai_api.identity import require_person
from wasifyai_api.mcp_client.client import ExternalClient
from wasifyai_api.mcp_client.imports import SOURCES, default_path, read_definitions
from wasifyai_api.services import services_of

router = APIRouter(tags=["external"])


class ServerIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    transport: str
    url: str = ""
    command: str = ""
    args: list[str] | str | None = None
    env: dict[str, str] | None = None
    token: str | None = None
    trust: str = "ask"
    allowed_tools: list[str] | str | None = None
    timeout_s: int = 60
    # decision 3: adding a program is installing software; the person types its name
    confirm_name: str | None = None


class AttachIn(BaseModel):
    uri: str = Field(min_length=1, max_length=2000)


class PromptIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    arguments: dict[str, str] = Field(default_factory=dict)


class FormAnswer(BaseModel):
    action: str
    content: dict[str, Any] | None = None


class ImportIn(BaseModel):
    source: str
    path: str | None = None  # a file the person named; else the client's usual place
    folder: str | None = None  # claude_code: the project folder whose .mcp.json to read


class ImportAdd(ImportIn):
    name: str = Field(min_length=1, max_length=200)  # the definition to add, as listed


class ServerPatch(BaseModel):
    name: str | None = None
    url: str | None = None
    command: str | None = None
    args: list[str] | str | None = None
    env: dict[str, str] | None = None
    token: str | None = None
    trust: str | None = None
    allowed_tools: list[str] | str | None = None
    timeout_s: int | None = None
    keep_content: bool | None = None


def _client(request: Request) -> ExternalClient:
    client = services_of(request).mcp_client
    if client is None:
        raise HTTPException(404, "tools from other apps are not available in this deployment")
    return client


def _bad(exc: ValueError) -> HTTPException:
    return HTTPException(422, str(exc))


def _row(client: ExternalClient, s: Any) -> dict[str, Any]:
    cached = client.tools_cached(s.id)
    return {**s.public(), "tools": [t.public() for t in cached] if cached else None}


@router.get("/external")
async def list_servers(request: Request, me: Identity = Depends(require_person)) -> dict[str, Any]:
    client = _client(request)
    rows = await client.servers.store.for_person(me.tenant_id, me.user_id)
    return {"servers": [_row(client, s) for s in rows]}


@router.post("/external", status_code=201)
async def add_server(
    body: ServerIn, request: Request, me: Identity = Depends(require_person)
) -> dict[str, Any]:
    client = _client(request)
    if body.transport == "stdio" and (body.confirm_name or "").strip() != body.name.strip():
        raise HTTPException(
            422, "Type the server's name to confirm: this starts a program on this computer."
        )
    try:
        s = await client.servers.create(
            me.tenant_id, me.user_id, body.name, body.transport, url=body.url,
            command=body.command, args=body.args, env=body.env, token=body.token,
            trust=body.trust, allowed_tools=body.allowed_tools, timeout_s=body.timeout_s,
        )  # fmt: skip
    except ValueError as exc:
        raise _bad(exc) from None
    return {"server": _row(client, s)}


@router.patch("/external/{server_id}")
async def update_server(
    server_id: str, body: ServerPatch, request: Request, me: Identity = Depends(require_person)
) -> dict[str, Any]:
    client = _client(request)
    try:
        s = await client.servers.mine(me.tenant_id, me.user_id, server_id)
    except KeyError:
        raise HTTPException(404, "no such server") from None
    changes = body.model_dump(exclude_unset=True)
    try:
        s = await client.servers.update(s, changes)
    except ValueError as exc:
        raise _bad(exc) from None
    if {"url", "command", "args", "env", "token"} & set(changes):
        await client.close(s.id)  # the next call connects afresh
    return {"server": _row(client, s)}


@router.delete("/external/{server_id}")
async def remove_server(
    server_id: str, request: Request, me: Identity = Depends(require_person)
) -> dict[str, Any]:
    client = _client(request)
    try:
        s = await client.servers.mine(me.tenant_id, me.user_id, server_id)
    except KeyError:
        raise HTTPException(404, "no such server") from None
    await client.close(s.id)
    await client.servers.delete(s)
    return {"removed": s.id}


@router.post("/external/{server_id}/test")
async def test_server(
    server_id: str, request: Request, me: Identity = Depends(require_person)
) -> dict[str, Any]:
    """Connect and list the tools; clears the health count (decision 9)."""
    client = _client(request)
    try:
        s = await client.servers.mine(me.tenant_id, me.user_id, server_id)
    except KeyError:
        raise HTTPException(404, "no such server") from None
    out = await client.test(s)
    fresh = await client.servers.store.get(s.id) or s
    return {**out, "server": _row(client, fresh)}


@router.get("/external/{server_id}/log")
async def server_log(
    server_id: str, request: Request, me: Identity = Depends(require_person)
) -> dict[str, Any]:
    """The last part of a program's output (ADR-0070 decision 3); "" for an address."""
    client = _client(request)
    try:
        s = await client.servers.mine(me.tenant_id, me.user_id, server_id)
    except KeyError:
        raise HTTPException(404, "no such server") from None
    return {"log": client.log_tail(s)}


async def _mine(client: ExternalClient, me: Identity, server_id: str) -> Any:
    try:
        return await client.servers.mine(me.tenant_id, me.user_id, server_id)
    except KeyError:
        raise HTTPException(404, "no such server") from None


@router.get("/external/{server_id}/resources")
async def server_resources(
    server_id: str, request: Request, me: Identity = Depends(require_person)
) -> dict[str, Any]:
    """What the server offers to read (ADR-0070 decision 10): the person picks one to attach."""
    client = _client(request)
    s = await _mine(client, me, server_id)
    try:
        return {"resources": [r.public() for r in await client.resources(s)]}
    except ConnectionError as exc:
        raise HTTPException(502, str(exc)) from None


@router.post("/external/{server_id}/resources/attach", status_code=201)
async def attach_resource(
    server_id: str, body: AttachIn, request: Request, me: Identity = Depends(require_person)
) -> dict[str, Any]:
    """Read a text resource and keep it as a document the next chat message can attach, the
    way an uploaded file is kept (the same record, the same storage)."""
    from wasifyai_platform_sdk import new_upload

    client = _client(request)
    s = await _mine(client, me, server_id)
    state: Any = services_of(request)
    storage = state.storage
    uploads = state.uploads
    if storage is None or uploads is None:
        raise HTTPException(503, "file storage is not available")
    try:
        text, cut = await client.read_resource(s, body.uri)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except ConnectionError as exc:
        raise HTTPException(502, str(exc)) from None
    kept = text.encode("utf-8")
    record = new_upload(me.tenant_id, "wasifyai-assistant", me.user_id, len(kept), "text")
    await storage.put_for(record.owner, record.key, kept, "text/plain; charset=utf-8")
    await uploads.add(record)
    name = body.uri.rsplit("/", 1)[-1][:120] or body.uri[:120]
    return {
        "id": record.id, "kind": "document", "name": f"{s.name}: {name}",
        "chars": len(text), "truncated": cut,
    }  # fmt: skip


@router.get("/external/{server_id}/prompts")
async def server_prompts(
    server_id: str, request: Request, me: Identity = Depends(require_person)
) -> dict[str, Any]:
    """The server's prompts: templates for the box."""
    client = _client(request)
    s = await _mine(client, me, server_id)
    try:
        return {"prompts": [p.public() for p in await client.prompts(s)]}
    except ConnectionError as exc:
        raise HTTPException(502, str(exc)) from None


@router.post("/external/{server_id}/prompts/get")
async def server_prompt_text(
    server_id: str, body: PromptIn, request: Request, me: Identity = Depends(require_person)
) -> dict[str, Any]:
    client = _client(request)
    s = await _mine(client, me, server_id)
    try:
        return {"text": await client.get_prompt(s, body.name, body.arguments)}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except ConnectionError as exc:
        raise HTTPException(502, str(exc)) from None


@router.get("/external/forms")
async def pending_forms(request: Request, me: Identity = Depends(require_person)) -> dict[str, Any]:
    """The questions outside servers are waiting on (ADR-0070 decision 10)."""
    client = _client(request)
    return {"forms": [f.public() for f in client.forms.pending_for(me.tenant_id, me.user_id)]}


@router.post("/external/forms/{form_id}")
async def answer_form(
    form_id: str, body: FormAnswer, request: Request, me: Identity = Depends(require_person)
) -> dict[str, Any]:
    """The person's answer to a form: accept with the values, decline, or cancel."""
    client = _client(request)
    try:
        form = client.forms.answer(me.tenant_id, me.user_id, form_id, body.action, body.content)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if form is None:
        raise HTTPException(404, "no such form")
    return {"form_id": form.id, "action": body.action}


def _definitions(body: ImportIn) -> list[Any]:
    if body.source not in SOURCES:
        raise HTTPException(422, "the source is claude_code, claude_desktop or codex")
    from pathlib import Path

    if body.path:
        path = Path(body.path).expanduser()
    else:
        folder = Path(body.folder).expanduser() if body.folder else None
        path = default_path(body.source, folder)
    try:
        return read_definitions(body.source, path)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/external/import")
async def import_definitions(
    body: ImportIn, request: Request, _: Identity = Depends(require_person)
) -> dict[str, Any]:
    """The server definitions another client's config holds (ADR-0070 decision 2): shown to the
    person, who adds each one they want with `/external/import/add`. Values stay on the engine."""
    _client(request)
    return {"found": [d.public() for d in _definitions(body)]}


@router.post("/external/import/add", status_code=201)
async def import_add(
    body: ImportAdd, request: Request, me: Identity = Depends(require_person)
) -> dict[str, Any]:
    """Add one definition as the file has it; its variables and token go to the secret store."""
    client = _client(request)
    d = next((x for x in _definitions(body) if x.name == body.name), None)
    if d is None:
        raise HTTPException(404, "no such definition in that file")
    if d.note:
        raise HTTPException(422, d.note)
    try:
        s = await client.servers.create(
            me.tenant_id, me.user_id, d.name, d.transport, url=d.url, command=d.command,
            args=list(d.args), env=d.env, token=d.token or None,
        )  # fmt: skip
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"server": _row(client, s)}


@router.get("/external/{server_id}/activity")
async def server_activity(
    server_id: str, request: Request, me: Identity = Depends(require_person)
) -> dict[str, Any]:
    client = _client(request)
    try:
        s = await client.servers.mine(me.tenant_id, me.user_id, server_id)
    except KeyError:
        raise HTTPException(404, "no such server") from None
    return {"activity": [e.public() for e in await client.servers.store.activity(s.id)]}
