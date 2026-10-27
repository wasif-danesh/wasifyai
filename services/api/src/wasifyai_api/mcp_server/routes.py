"""Settings > Connections (ADR-0069 decision 3) and the window's side of approvals (decision 8).

GET/POST /connections, PATCH/DELETE /connections/{id}, POST /connections/{id}/rotate,
GET /connections/{id}/activity, GET /connections/snippets
GET/PUT /connections/launcher             "Let other apps use Wasify AI"
GET /actions/approvals, POST /actions/approvals/{id}   the pending cards and the answer
"""

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from wasifyai_api.config import get_settings
from wasifyai_api.identity import Identity, get_identity
from wasifyai_api.mcp_server.approvals import ApprovalDesk
from wasifyai_api.mcp_server.connections import ConnectionsService

router = APIRouter(tags=["connections"])
LAUNCHER_PLACEHOLDER = "<path to wasify-mcp>"


def _connections(request: Request) -> ConnectionsService:
    svc = getattr(request.app.state, "connections", None)
    if svc is None:
        raise HTTPException(404, "connections are not available in this deployment")
    return svc


def _desk(request: Request) -> ApprovalDesk:
    desk = getattr(request.app.state, "approval_desk", None)
    if desk is None:
        raise HTTPException(404, "not available in this deployment")
    return desk


class ConnectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    scopes: list[str] | None = None
    approval: dict[str, str] | None = None
    read_folders: list[str] | None = None
    write_folders: list[str] | None = None


class ConnectionPatch(BaseModel):
    name: str | None = None
    scopes: list[str] | None = None
    approval: dict[str, str] | None = None
    read_folders: list[str] | None = None
    write_folders: list[str] | None = None
    rate_per_minute: int | None = None


class Decision(BaseModel):
    approved: bool


class LauncherIn(BaseModel):
    enabled: bool


def _bad(exc: ValueError) -> HTTPException:
    return HTTPException(422, str(exc))


@router.get("/connections")
async def list_connections(
    request: Request, me: Identity = Depends(get_identity)
) -> dict[str, Any]:
    svc = _connections(request)
    rows = await svc.store.for_person(me.tenant_id, me.user_id)
    return {"connections": [c.public() for c in rows if c.kind == "client"]}


@router.post("/connections", status_code=201)
async def create_connection(
    body: ConnectionIn, request: Request, me: Identity = Depends(get_identity)
) -> dict[str, Any]:
    """A new connection. The answer holds the secret once; it is never shown again."""
    svc = _connections(request)
    try:
        c, secret = await svc.create(
            me.tenant_id, me.user_id, body.name, scopes=body.scopes, policy=body.approval,
            read_folders=body.read_folders, write_folders=body.write_folders,
        )  # fmt: skip
    except ValueError as exc:
        raise _bad(exc) from None
    return {"connection": c.public(), "secret": secret}


@router.patch("/connections/{connection_id}")
async def update_connection(
    connection_id: str,
    body: ConnectionPatch,
    request: Request,
    me: Identity = Depends(get_identity),
) -> dict[str, Any]:
    svc = _connections(request)
    try:
        c = await svc.update(
            me.tenant_id, me.user_id, connection_id, body.model_dump(exclude_unset=True)
        )
    except KeyError:
        raise HTTPException(404, "no such connection") from None
    except ValueError as exc:
        raise _bad(exc) from None
    return c.public()


@router.post("/connections/{connection_id}/rotate")
async def rotate_connection(
    connection_id: str, request: Request, me: Identity = Depends(get_identity)
) -> dict[str, Any]:
    svc = _connections(request)
    try:
        c, secret = await svc.rotate(me.tenant_id, me.user_id, connection_id)
    except KeyError:
        raise HTTPException(404, "no such connection") from None
    return {"connection": c.public(), "secret": secret}


@router.delete("/connections/{connection_id}")
async def revoke_connection(
    connection_id: str, request: Request, me: Identity = Depends(get_identity)
) -> dict[str, Any]:
    svc = _connections(request)
    try:
        c = await svc.revoke(me.tenant_id, me.user_id, connection_id)
    except KeyError:
        raise HTTPException(404, "no such connection") from None
    return c.public()


@router.get("/connections/{connection_id}/activity")
async def connection_activity(
    connection_id: str, request: Request, me: Identity = Depends(get_identity)
) -> dict[str, Any]:
    svc = _connections(request)
    try:
        await svc.mine(me.tenant_id, me.user_id, connection_id)
    except KeyError:
        raise HTTPException(404, "no such connection") from None
    return {"activity": [e.public() for e in await svc.store.activity(connection_id)]}


def snippets(launcher: str, port: int | None) -> dict[str, str]:
    """The config each client takes (spike S1, "Config snippets that worked"). The stdio forms
    name only the launcher; the HTTP forms, for the opt-in fixed port, name a variable that
    holds the secret, never the secret."""
    out = {
        "claude_code_command": f'claude mcp add --transport stdio wasify -- "{launcher}"',
        "claude_code_json": json.dumps(
            {"mcpServers": {"wasify": {"type": "stdio", "command": launcher, "args": []}}},
            indent=2,
        ),
        "codex_toml": (
            f'[mcp_servers.wasify]\ncommand = "{launcher}"\n'
            'default_tools_approval_mode = "approve"\n'
        ),
        "opencode_json": json.dumps(
            {"mcp": {"wasify": {"type": "local", "command": [launcher]}}}, indent=2
        ),
    }
    if port:
        out["http_url"] = f"http://127.0.0.1:{port}/mcp"
        out["claude_code_http"] = (
            f"claude mcp add --transport http wasify http://127.0.0.1:{port}/mcp "
            '--header "Authorization: Bearer ${WASIFY_MCP_SECRET}"'
        )
    return out


@router.get("/connections/snippets")
async def connection_snippets(
    request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    settings = get_settings()
    launcher = settings.wasifyai_mcp_launcher or LAUNCHER_PLACEHOLDER
    port = getattr(getattr(request.app.state, "launcher", None), "port", None)
    return {"launcher": launcher, "snippets": snippets(launcher, port)}


@router.get("/connections/launcher")
async def launcher_state(request: Request, me: Identity = Depends(get_identity)) -> dict[str, Any]:
    launcher = getattr(request.app.state, "launcher", None)
    if launcher is None:
        return {"available": False, "enabled": False}
    return {"available": True, **(await launcher.state(me))}


@router.put("/connections/launcher")
async def launcher_set(
    body: LauncherIn, request: Request, me: Identity = Depends(get_identity)
) -> dict[str, Any]:
    """The switch "Let other apps use Wasify AI": on makes the launcher's connection and writes
    `engine.json`; off revokes it and removes the file."""
    launcher = getattr(request.app.state, "launcher", None)
    if launcher is None:
        raise HTTPException(404, "the launcher is a desktop feature")
    if body.enabled:
        await launcher.enable(me)
    else:
        await launcher.disable(me)
    return {"available": True, **(await launcher.state(me))}


@router.get("/actions/approvals")
async def pending_approvals(
    request: Request, me: Identity = Depends(get_identity)
) -> dict[str, Any]:
    desk = _desk(request)
    return {
        "approvals": [
            {
                "approval_id": p.approval_id,
                "connection": p.connection_name,
                "action_id": p.action_id,
                "title": p.title,
                "summary": p.summary,
                "params": {
                    k: v for k, v in p.params.items() if isinstance(v, str | int | float | bool)
                },
            }  # fmt: skip
            for p in desk.pending_for(me.tenant_id, me.user_id)
        ]
    }


@router.post("/actions/approvals/{approval_id}")
async def decide_approval(
    approval_id: str, body: Decision, request: Request, me: Identity = Depends(get_identity)
) -> dict[str, Any]:
    """The person's answer to a card an agent is waiting for. A yes runs the action."""
    desk = _desk(request)
    p = await desk.decide(me.tenant_id, me.user_id, approval_id, body.approved)
    if p is None:
        raise HTTPException(404, "no such approval")
    return p.public()
