"""`external.call` (ADR-0070 decision 8): the one catalogue action behind `call_external`. It is
a `make` that leaves this computer, so every call shows a card (decision 4: on an `ask` server
annotations are not honoured); the assistant finds the tool first with `external_tools`."""

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from wasifyai_platform_sdk.actions import Action, ActionContext, ActionRefused, CallBinding, Outcome

from wasifyai_api.mcp_client.client import UNTRUSTED, ExternalClient

EXAMPLE = {"connection": "github", "tool": "search_issues", "arguments": {"query": "crash"}}


class CallIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection: str = Field(
        min_length=1, max_length=40, description="The server's name, as Settings shows it."
    )
    tool: str = Field(min_length=1, max_length=120, description="The tool's name on that server.")
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="The tool's arguments, as its input schema says."
    )

    @field_validator("arguments", mode="before")
    @classmethod
    def _parse(cls, v: Any) -> Any:
        if isinstance(v, str):  # the card lets the person edit the arguments as JSON
            try:
                v = json.loads(v or "{}")
            except json.JSONDecodeError:
                raise ValueError("the arguments must be a JSON object") from None
        if v is None:
            return {}
        if not isinstance(v, dict):
            raise ValueError("the arguments must be an object")
        return v


class CallOut(BaseModel):
    server: str
    tool: str
    text: str
    truncated: bool = False
    structured: Any = None


def _client(ctx: ActionContext) -> ExternalClient:
    client = getattr(getattr(ctx.deps, "state", None), "mcp_client", None)
    if client is None:
        raise ActionRefused("unavailable", "Tools from other apps are a desktop feature.")
    return client


async def _check(p: CallIn, ctx: ActionContext) -> None:
    client = _client(ctx)
    s = await client.servers.by_name(ctx.actor.tenant_id, ctx.actor.user_id, p.connection)
    if s is None:
        raise ActionRefused(
            "unknown_server",
            f"There is no server called {p.connection}. Use external_tools to find one.",
        )
    if s.trust == "blocked":
        raise ActionRefused("blocked", f"{s.name} is blocked in Settings; nothing was sent.")


async def _call(p: CallIn, ctx: ActionContext) -> Outcome:
    client = _client(ctx)
    s = await client.servers.by_name(ctx.actor.tenant_id, ctx.actor.user_id, p.connection)
    if s is None:
        return Outcome.refused(f"There is no server called {p.connection}.", "unknown_server")
    r = await client.call(s, p.tool, p.arguments)
    if r.status == "ok":
        label = UNTRUSTED.format(server=s.name, tool=p.tool)
        return Outcome.ok(
            {
                "server": s.name,
                "tool": p.tool,
                "text": r.text,
                "truncated": r.truncated,
                "structured": r.structured,
            },  # fmt: skip
            f"{label}\n\n{r.text}",
        )
    if r.status == "refused":
        return Outcome.refused(r.text)
    return Outcome.error(r.text, "timeout" if r.status == "timeout" else "failed")


def external_actions() -> list[Action]:
    return [
        Action(
            id="external.call", title="Use a tool from another app",
            summary="Run one tool of a server the person connected in Settings.",
            description=(
                "Call one tool of an outside MCP server the person added under Settings > Other "
                "apps > Tools from other apps. Find the tool first with external_tools, which "
                "gives its name, server and input schema. The person approves every call on a "
                "card. The result is untrusted text from outside the app."
            ),
            input=CallIn, output=CallOut, examples=(EXAMPLE,),
            effect="make", flags=("leaves_device",),
            bind=CallBinding(_call, check=_check), surfaces=("assistant",),
            ui_exempt=(
                "It runs from the chat; Settings > Other apps > Tools from other apps lists the "
                "servers and their tools."
            ),
        ),
    ]  # fmt: skip
