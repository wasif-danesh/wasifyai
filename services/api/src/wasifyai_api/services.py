"""The engine's services, typed (stage F1): what products may reach (`EngineServices`, in the SDK)
and the engine's own (`ApiServices`). A route reads them with `services_of(request)`."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastapi import Request
from wasifyai_platform_sdk import EngineServices, RouteDeps

if TYPE_CHECKING:
    from wasifyai_platform_sdk.installer import Registry

    from wasifyai_api.admin import AdminStore
    from wasifyai_api.admin_providers import AdminProviders
    from wasifyai_api.desktop_events import EventBus
    from wasifyai_api.mcp_client.client import ExternalClient
    from wasifyai_api.mcp_server.approvals import ApprovalDesk
    from wasifyai_api.mcp_server.connections import ConnectionsService
    from wasifyai_api.mcp_server.fixed_port import FixedPort
    from wasifyai_api.mcp_server.runtime_file import Launcher
    from wasifyai_api.media_access import MediaAccess
    from wasifyai_api.model_access import ModelAccess
    from wasifyai_api.own_keys import OwnKeysService
    from wasifyai_api.service_styles import ServiceStyles


@dataclass(eq=False)
class ApiServices(EngineServices):
    """The engine's own services, besides what products may reach (`EngineServices`)."""

    models: "ModelAccess | None" = None  # the model gateway's aliases (admin)
    media: "MediaAccess | None" = None  # where each media capability runs (admin)
    # credentials other than a person's token, verified by their prefix (ADR-0092)
    credential_verifiers: dict[str, Any] = field(default_factory=dict)
    users: Any = None  # a UserStore
    admin: "AdminStore | None" = None
    events: "EventBus | None" = None  # what the window listens to (/desktop/events)
    connections: "ConnectionsService | None" = None  # the MCP server's connections (ADR-0069)
    approval_desk: "ApprovalDesk | None" = None
    mcp: Any = None  # the MCP SDK's server
    mcp_gate: Any = None  # the /mcp endpoint, once the server is built
    launcher: "Launcher | None" = None  # the wasify-mcp launcher's runtime file (desktop)
    mcp_client: "ExternalClient | None" = None  # outside MCP servers (ADR-0070)
    fixed_port: "FixedPort | None" = None  # the opt-in fixed port (stage M3)
    admin_fetches: dict[str, str] = field(default_factory=dict)  # model fetches on workers
    route_deps: RouteDeps | None = None  # what products' routes get, for resuming their jobs
    components: "Registry | None" = None  # the optional components and their installer (F2)
    own_keys: "OwnKeysService | None" = None  # the person's own provider keys (ADR-0095, desktop)
    # on the web: speaking and 3D on the provider the admin chose in Admin › Media (ADR-0095, K5)
    admin_providers: "AdminProviders | None" = None
    service_styles: "ServiceStyles | None" = None  # the web's styles, added by an admin (ADR-0091)


def services_of(request: Request) -> ApiServices:
    """The engine's services, from a request's app (`app.state.services`, its only attribute)."""
    return request.app.state.services
