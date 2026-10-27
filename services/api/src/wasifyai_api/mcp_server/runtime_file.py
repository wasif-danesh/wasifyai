"""`engine.json` (ADR-0069 decision 2): what the stdio launcher reads on every request: this
engine's pid, loopback host and port, and the launcher connection's secret. Mode 0600, written
whole through a temporary file, removed when the engine stops. The secret itself lives in the
secret store (`mcp.launcher.secret`), so a restart writes the same connection again."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

FILE_NAME = "engine.json"
SECRET_NAME = "mcp.launcher.secret"


def write_runtime_file(path: Path, *, pid: int, port: int, secret: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"pid": pid, "host": "127.0.0.1", "port": port, "secret": secret})
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def remove_runtime_file(path: Path) -> None:
    path.unlink(missing_ok=True)


class Launcher:
    """ "Let other apps use Wasify AI" on the desktop: the launcher's connection (kind `launcher`,
    the default scopes), its secret kept in the secret store, and `engine.json` written while it
    is on. Nothing is written until the person switches it on."""

    def __init__(self, root: Path, secrets: Any, connections: Any, port: int | None) -> None:
        self.path = root / FILE_NAME
        self.secrets = secrets
        self.connections = connections
        self.port = port

    async def _mine(self, me: Any) -> Any:
        for c in await self.connections.store.for_person(me.tenant_id, me.user_id):
            if c.kind == "launcher" and not c.revoked:
                return c
        return None

    async def state(self, me: Any) -> dict:
        c = await self._mine(me)
        return {
            "enabled": c is not None and self.path.is_file(),
            "connection": c.public() if c is not None else None,
            "file": str(self.path),
        }

    async def enable(self, me: Any) -> None:
        c = await self._mine(me)
        secret = await self.secrets.get(SECRET_NAME) if c is not None else None
        if c is None or not secret:
            if c is not None:
                await self.connections.revoke(me.tenant_id, me.user_id, c.id)
            c, secret = await self.connections.create(
                me.tenant_id, me.user_id, "Launcher on this computer", kind="launcher"
            )
            await self.secrets.put(SECRET_NAME, secret)
        await self.write(secret)

    async def write(self, secret: str) -> None:
        if self.port:
            write_runtime_file(self.path, pid=os.getpid(), port=self.port, secret=secret)

    async def write_if_enabled(self, me: Any) -> None:
        """At start-up: the file for this launch, when the switch was left on."""
        c = await self._mine(me)
        secret = await self.secrets.get(SECRET_NAME) if c is not None else None
        if c is not None and secret:
            await self.write(secret)

    async def disable(self, me: Any) -> None:
        c = await self._mine(me)
        if c is not None:
            await self.connections.revoke(me.tenant_id, me.user_id, c.id)
        await self.secrets.delete(SECRET_NAME)
        remove_runtime_file(self.path)
