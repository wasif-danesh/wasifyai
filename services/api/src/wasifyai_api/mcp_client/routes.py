"""Settings > Other apps > "Tools from other apps" (ADR-0070 decision 2): the person, and only the
person in the window, adds, tests, changes and removes servers. No connection or key may."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from wasifyai_platform_sdk.identity import Identity

from wasifyai_api.identity import require_person
from wasifyai_api.mcp_client.client import ExternalClient

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
    client = getattr(request.app.state, "mcp_client", None)
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
