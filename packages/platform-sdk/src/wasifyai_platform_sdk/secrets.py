"""Where keys and tokens are kept (stage F4 of the 2026-10-27 plan; ADR-0070 decision 7).

One interface, `SecretStore`: `put`, `get`, `delete`, `names`. It answers a value only by name
and never lists values, so nothing that walks it can print them. Where the values live is the
deployment's choice:

    InMemorySecretStore    tests
    FileSecretStore        one JSON file of Fernet tokens next to the data (the desktop without a
                           keychain; the key comes from `secrets.key` as before)
    KeychainSecretStore    the operating system's own store: the macOS keychain (Security
                           framework), the Windows Credential Manager (advapi32) or the Linux
                           Secret Service (libsecret's secret-tool); the names are kept in a
                           small file so `names()` needs no keychain walk
    SqlSecretStore         a `secrets` table, Fernet under MEDIA_SECRETS_KEY (the web)
    EnvSecretStore         read-only: the values External Secrets or an operator put in the
                           environment, `WASIFYAI_SECRET_<NAME>` (dots and dashes as underscores)
    LayeredSecretStore     a writable store in front of read-only ones

Names are `area.thing`, for example `hf.token`, `web.search.exa`, `mcp.client.<server>`. Logs and
audit never hold a value; `tests/test_secrets.py` checks the stores and the file on disk."""

import json
import os
import re
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from wasifyai_platform_sdk.secretbox import SecretBox, SecretsUnavailable
from wasifyai_platform_sdk.sqlite.engine import ensure_tables, is_sqlite

__all__ = [
    "EnvSecretStore",
    "FileSecretStore",
    "InMemorySecretStore",
    "KeychainSecretStore",
    "LayeredSecretStore",
    "SecretStore",
    "SqlSecretStore",
    "secret_name",
]

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*(\.[a-z0-9][a-z0-9_-]*)+$")
MAX_NAME = 100
MAX_VALUE = 8_000  # a token or key; a file does not belong here


def secret_name(name: str) -> str:
    """A valid secret name (`area.thing`), or a ValueError that names the rule."""
    if not isinstance(name, str) or len(name) > MAX_NAME or not NAME_PATTERN.match(name):
        raise ValueError(
            "a secret name is lower-case words joined by dots, such as hf.token, "
            f"not {str(name)[:40]!r}"
        )
    return name


def _value(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_VALUE:
        raise ValueError("a secret is a non-empty string of at most 8,000 characters")
    return value


class SecretStore(Protocol):
    @property
    def ready(self) -> bool:
        """Whether a new secret can be kept here now (a store with no key says no)."""
        ...

    async def put(self, name: str, value: str) -> None: ...

    async def get(self, name: str) -> str | None: ...

    async def delete(self, name: str) -> None: ...

    async def names(self) -> list[str]: ...


class InMemorySecretStore:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    @property
    def ready(self) -> bool:
        return True

    async def put(self, name: str, value: str) -> None:
        self._values[secret_name(name)] = _value(value)

    async def get(self, name: str) -> str | None:
        return self._values.get(secret_name(name))

    async def delete(self, name: str) -> None:
        self._values.pop(secret_name(name), None)

    async def names(self) -> list[str]:
        return sorted(self._values)


def _write_private(path: Path, body: str) -> None:
    """Write a file readable by this user only, whole or not at all."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


class FileSecretStore:
    """Fernet tokens in one JSON file (`{"hf.token": "gAAAA..."}`), mode 0600."""

    def __init__(self, path: Path, box: SecretBox):
        self._path = path
        self._box = box

    @property
    def ready(self) -> bool:
        return self._box.ready

    def _load(self) -> dict[str, str]:
        return {k: v for k, v in _read_json(self._path).items() if isinstance(v, str)}

    async def put(self, name: str, value: str) -> None:
        name, value = secret_name(name), _value(value)
        data = self._load()
        data[name] = self._box.encrypt(value)
        _write_private(self._path, json.dumps(data, indent=1, sort_keys=True))

    async def get(self, name: str) -> str | None:
        token = self._load().get(secret_name(name))
        return None if token is None else self._box.decrypt(token)

    async def delete(self, name: str) -> None:
        data = self._load()
        if data.pop(secret_name(name), None) is not None:
            _write_private(self._path, json.dumps(data, indent=1, sort_keys=True))

    async def names(self) -> list[str]:
        return sorted(self._load())


class EnvSecretStore:
    """Read-only: `WASIFYAI_SECRET_HF_TOKEN` answers `hf.token`. `aliases` lets a well-known
    variable answer too (`HF_TOKEN` for `hf.token`)."""

    PREFIX = "WASIFYAI_SECRET_"

    def __init__(self, aliases: dict[str, Sequence[str]] | None = None):
        self._aliases = aliases or {}

    @property
    def ready(self) -> bool:
        return False

    @classmethod
    def variable(cls, name: str) -> str:
        return cls.PREFIX + re.sub(r"[.-]", "_", secret_name(name)).upper()

    def _variables(self, name: str) -> list[str]:
        return [self.variable(name), *self._aliases.get(name, ())]

    async def put(self, name: str, value: str) -> None:
        raise SecretsUnavailable("secrets from the environment cannot be changed here")

    async def get(self, name: str) -> str | None:
        for var in self._variables(name):
            value = os.environ.get(var, "").strip()
            if value:
                return value
        return None

    async def delete(self, name: str) -> None:
        raise SecretsUnavailable("secrets from the environment cannot be changed here")

    async def names(self) -> list[str]:
        found = {
            re.sub(r"_", ".", var[len(self.PREFIX) :]).lower()
            for var, value in os.environ.items()
            if var.startswith(self.PREFIX) and value.strip()
        }
        for name, variables in self._aliases.items():
            if any(os.environ.get(v, "").strip() for v in variables):
                found.add(name)
        return sorted(n for n in found if NAME_PATTERN.match(n))


class LayeredSecretStore:
    """Writes go to the first store; reads try it first, then the read-only ones behind it."""

    def __init__(self, writable: SecretStore, *behind: SecretStore):
        self._first = writable
        self._behind = behind

    @property
    def ready(self) -> bool:
        return self._first.ready

    async def put(self, name: str, value: str) -> None:
        await self._first.put(name, value)

    async def get(self, name: str) -> str | None:
        for store in (self._first, *self._behind):
            value = await store.get(name)
            if value is not None:
                return value
        return None

    async def delete(self, name: str) -> None:
        await self._first.delete(name)

    async def names(self) -> list[str]:
        out: set[str] = set()
        for store in (self._first, *self._behind):
            out.update(await store.names())
        return sorted(out)


_SECRETS_DDL = (
    """
    CREATE TABLE IF NOT EXISTS secrets (
        name TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
)


class SqlSecretStore:
    """A `secrets` table (Alembic revision 0022 on Postgres; created on first use on SQLite)."""

    def __init__(self, engine: AsyncEngine, box: SecretBox):
        self._engine = engine
        self._box = box

    @property
    def ready(self) -> bool:
        return self._box.ready

    async def _ready(self) -> None:
        if is_sqlite(self._engine):
            await ensure_tables(self._engine, "secrets", _SECRETS_DDL)

    async def put(self, name: str, value: str) -> None:
        from datetime import UTC, datetime

        name, token = secret_name(name), self._box.encrypt(_value(value))
        await self._ready()
        now = datetime.now(UTC).isoformat()
        async with self._engine.begin() as conn:
            await conn.execute(text("DELETE FROM secrets WHERE name = :n"), {"n": name})
            await conn.execute(
                text("INSERT INTO secrets (name, value, updated_at) VALUES (:n, :v, :t)"),
                {"n": name, "v": token, "t": now},
            )

    async def get(self, name: str) -> str | None:
        name = secret_name(name)
        await self._ready()
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(text("SELECT value FROM secrets WHERE name = :n"), {"n": name})
            ).first()
        return None if row is None else self._box.decrypt(str(row[0]))

    async def delete(self, name: str) -> None:
        name = secret_name(name)
        await self._ready()
        async with self._engine.begin() as conn:
            await conn.execute(text("DELETE FROM secrets WHERE name = :n"), {"n": name})

    async def names(self) -> list[str]:
        await self._ready()
        async with self._engine.connect() as conn:
            rows = await conn.execute(text("SELECT name FROM secrets ORDER BY name"))
            return [str(r[0]) for r in rows]


class KeychainSecretStore:
    """The operating system's own store, one item per secret under one service name: the macOS
    keychain through the Security framework, the Windows Credential Manager through advapi32,
    the Linux Secret Service through libsecret's `secret-tool` (value on stdin). A value is
    never on a command line. The names are kept in `index_path` (0600) because listing a
    service's items would need a store walk and a prompt. `available()` says whether this
    platform has one; the desktop uses the encrypted file when it does not."""

    def __init__(self, service: str, index_path: Path):
        self._service = service
        self._index = index_path
        self._api: Any = None

    @staticmethod
    def platform() -> str:
        """`macos`, `windows`, `linux` or `` (no native store here)."""
        if sys.platform == "darwin":
            return "macos"
        if sys.platform == "win32":
            return "windows"
        if sys.platform.startswith("linux"):
            from wasifyai_platform_sdk import keychain_linux

            return "linux" if keychain_linux.available() else ""
        return ""

    @classmethod
    def available(cls) -> bool:
        return cls.platform() != ""

    @property
    def ready(self) -> bool:
        return self.available()

    def _keychain(self) -> Any:
        if self._api is None:
            which = self.platform()
            if which == "macos":
                from wasifyai_platform_sdk.keychain_macos import Keychain
            elif which == "windows":
                from wasifyai_platform_sdk.keychain_windows import (
                    Keychain,  # type: ignore[assignment]
                )
            elif which == "linux":
                from wasifyai_platform_sdk.keychain_linux import (
                    Keychain,  # type: ignore[assignment]
                )
            else:
                raise SecretsUnavailable("this computer has no keychain the app can use")
            self._api = Keychain(self._service)
        return self._api

    def _names(self) -> set[str]:
        raw = _read_json(self._index).get("names")
        return {n for n in raw if isinstance(n, str)} if isinstance(raw, list) else set()

    def _save_names(self, names: set[str]) -> None:
        _write_private(self._index, json.dumps({"names": sorted(names)}, indent=1))

    async def put(self, name: str, value: str) -> None:
        name, value = secret_name(name), _value(value)
        self._keychain().set(name, value)
        self._save_names(self._names() | {name})

    async def get(self, name: str) -> str | None:
        return self._keychain().get(secret_name(name))

    async def delete(self, name: str) -> None:
        name = secret_name(name)
        self._keychain().delete(name)
        self._save_names(self._names() - {name})

    async def names(self) -> list[str]:
        return sorted(self._names())
