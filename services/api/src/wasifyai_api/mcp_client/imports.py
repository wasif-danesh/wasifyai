"""Server definitions from other clients' configs (ADR-0070 decision 2, stage C3): Claude Code's
`.mcp.json` (and `~/.claude.json`), Claude Desktop's `claude_desktop_config.json`, Codex's
`config.toml`. Each definition is shown to the person and added only when they say so; the
values of its variables go to the secret store, never to the window."""

import json
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SOURCES = ("claude_code", "claude_desktop", "codex")


@dataclass(frozen=True)
class Definition:
    source: str
    name: str
    transport: str  # http or stdio
    command: str = ""
    args: tuple[str, ...] = ()
    url: str = ""
    env: dict[str, str] = field(default_factory=dict)
    token: str = ""
    note: str = ""  # why it cannot be added as it is ("HTTP+SSE is not supported")

    def public(self) -> dict[str, Any]:
        """What the window shows: the names of the variables, never their values."""
        d = asdict(self)
        d["env_names"] = sorted(self.env)
        d["has_token"] = bool(self.token)
        del d["env"], d["token"]
        d["args"] = list(self.args)
        return d


def default_path(source: str, folder: Path | None = None) -> Path:
    home = Path.home()
    if source == "claude_code":
        return (folder or Path.cwd()) / ".mcp.json" if folder else home / ".claude.json"
    if source == "claude_desktop":
        return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if source == "codex":
        return home / ".codex" / "config.toml"
    raise ValueError("the source is claude_code, claude_desktop or codex")


def _bearer(headers: Any) -> str:
    if isinstance(headers, dict):
        auth = str(headers.get("Authorization") or headers.get("authorization") or "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
    return ""


def _env_of(entry: dict[str, Any]) -> dict[str, str]:
    raw = entry.get("env")
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def _from_json_entry(source: str, name: str, entry: Any) -> Definition | None:
    """The shape Claude Code and Claude Desktop share: `{command, args, env}` or `{type, url,
    headers}`."""
    if not isinstance(entry, dict):
        return None
    kind = str(entry.get("type") or ("http" if entry.get("url") else "stdio")).lower()
    env = _env_of(entry)
    if kind == "stdio" or entry.get("command"):
        args = entry.get("args") or []
        return Definition(
            source, str(name), "stdio", command=str(entry.get("command") or ""),
            args=tuple(str(a) for a in args) if isinstance(args, list) else (), env=env,
        )  # fmt: skip
    if kind in ("http", "streamable-http", "streamable_http"):
        return Definition(
            source, str(name), "http", url=str(entry.get("url") or ""),
            token=_bearer(entry.get("headers")),
        )  # fmt: skip
    return Definition(
        source,
        str(name),
        "http",
        url=str(entry.get("url") or ""),
        note=f"{kind} is not supported (HTTP+SSE and WebSocket are deprecated)",
    )


def read_definitions(source: str, path: Path) -> list[Definition]:
    """Every server definition in the file. Raises ValueError when the file cannot be read."""
    if source not in SOURCES:
        raise ValueError("the source is claude_code, claude_desktop or codex")
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise ValueError(f"{path} could not be read: {e.strerror or e}") from None
    found: list[Definition] = []
    if source == "codex":
        try:
            data = tomllib.loads(raw.decode("utf-8", errors="replace"))
        except tomllib.TOMLDecodeError as e:
            raise ValueError(f"{path} is not valid TOML: {e}") from None
        raw_servers = data.get("mcp_servers")
        servers: dict[str, Any] = raw_servers if isinstance(raw_servers, dict) else {}
        for name, entry in servers.items():
            if not isinstance(entry, dict):
                continue
            env = _env_of(entry)
            if entry.get("command"):
                args = entry.get("args") or []
                found.append(
                    Definition(
                        source,
                        str(name),
                        "stdio",
                        command=str(entry["command"]),
                        args=tuple(str(a) for a in args) if isinstance(args, list) else (),
                        env=env,
                    )  # fmt: skip
                )
            elif entry.get("url"):
                token = _bearer(entry.get("http_headers")) or _bearer(entry.get("headers"))
                found.append(
                    Definition(source, str(name), "http", url=str(entry["url"]), token=token)
                )
        return found
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{path} is not valid JSON: {e.msg}") from None
    if not isinstance(data, dict):
        return found
    groups: list[dict[str, Any]] = []
    if isinstance(data.get("mcpServers"), dict):
        groups.append(data["mcpServers"])
    if source == "claude_code" and isinstance(data.get("projects"), dict):  # ~/.claude.json
        for project in data["projects"].values():
            if isinstance(project, dict) and isinstance(project.get("mcpServers"), dict):
                groups.append(project["mcpServers"])
    seen: set[str] = set()
    for group in groups:
        for name, entry in group.items():
            d = _from_json_entry(source, name, entry)
            if d is not None and d.name not in seen:
                seen.add(d.name)
                found.append(d)
    return found
