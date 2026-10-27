"""One MCP tool per catalogue action (ADR-0069 decision 4): the name `domain_verb`, the input
schema the action's own, annotations from its effect and flags, and a body that hands the call
to `calls.run_call`. The tools are built once for the whole catalogue; which of them a
connection sees is decided per request from its scopes (`endpoint.py`)."""

from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.mcpserver import Context
from mcp.server.mcpserver.tools.base import Tool
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase, FuncMetadata
from mcp_types import ToolAnnotations
from pydantic import ConfigDict, create_model
from wasifyai_platform_sdk.actions import Action, ActionRegistry, scope_of

Body = Callable[[Action, dict[str, Any], Context], Awaitable[Any]]
HOW_LONG = {
    True: " It can take a while: a result with status running carries a job_id to follow "
    "with job_status or job_wait.",
    False: "",
}


def tool_name(action_id: str) -> str:
    return action_id.replace(".", "_")


def annotations_of(action: Action) -> ToolAnnotations:
    """Hints for the client (the engine enforces the effect; ADR-0069 decision 4)."""
    read = action.effect == "read"
    return ToolAnnotations(
        title=action.title,
        read_only_hint=read,
        destructive_hint=action.effect == "destroy",
        idempotent_hint=read,
        open_world_hint="leaves_device" in action.flags,
    )


def meta_of(action: Action) -> dict[str, Any] | None:
    """A destroy or a consent action asks the person in the app: tell Claude Code to ask too."""
    if action.effect == "destroy" or "needs_consent" in action.flags:
        return {"anthropic/requiresUserInteraction": True}
    return None


def description_of(action: Action) -> str:
    text = action.description.strip() + HOW_LONG[action.long]
    if "needs_consent" in action.flags:
        text += " The person must agree in the Wasify AI window before it runs."
    elif action.effect == "destroy":
        text += " The person must approve in the Wasify AI window before it runs."
    return text


def arg_model_of(action: Action) -> type[ArgModelBase]:
    """The action's input, as the model the SDK validates arguments with."""
    fields = {name: (info.annotation, info) for name, info in action.input.model_fields.items()}
    model = create_model(  # type: ignore[call-overload]
        f"{tool_name(action.id)}_arguments",
        __base__=ArgModelBase,
        __config__=None,
        **fields,
    )
    model.model_config = ConfigDict(
        extra="forbid", arbitrary_types_allowed=True, str_strip_whitespace=True
    )
    model.model_rebuild(force=True)
    return model


def tool_of(action: Action, body: Body) -> Tool:
    async def fn(ctx: Context, **arguments: Any) -> Any:
        return await body(action, arguments, ctx)

    return Tool(
        fn=fn,
        name=tool_name(action.id),
        title=action.title,
        description=description_of(action),
        parameters=action.input.model_json_schema(),
        fn_metadata=FuncMetadata(arg_model=arg_model_of(action)),
        is_async=True,
        context_kwarg="ctx",
        annotations=annotations_of(action),
        meta=meta_of(action),
    )


def tools_of(registry: ActionRegistry, body: Body) -> dict[str, tuple[Action, Tool]]:
    """Every action offered to `mcp`, keyed by tool name, with the scope it needs."""
    out: dict[str, tuple[Action, Tool]] = {}
    for action in registry.for_surface("mcp"):
        out[tool_name(action.id)] = (action, tool_of(action, body))
    return out


def scope_needed(action: Action) -> str:
    return scope_of(action)
