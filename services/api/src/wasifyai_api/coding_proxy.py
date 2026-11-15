"""The way out for package installs from inside the coding sandbox (ADR-0102, amendment of
2026-11-15; stage C3 of docs/v2-coding-agent-start-plan.md).

The sandbox lets a program reach this computer only. An install (`pip install`, `npm install`,
`cargo add`) needs a package index, so the programs inside are given a proxy on loopback, this
one, and nothing else:

    which hosts     only the ones in `coding_install_hosts.txt`, and only on port 443. The proxy
                    opens a tunnel (`CONNECT`) and never sees what is sent through it
    who             two names, each with a random password made at every start of the engine and
                    given to the programs in the proxy's address:
                      agent    the agent's commands and the check. Let through only for a while
                               after an install step was let through by the rules
                               (`wasifyai_code/rules.py`), so a command that was not judged an
                               install cannot fetch anything
                      person   the person's own terminal. Always let through, to the same hosts
                    and one name per harness (ADR-0107): the person's own agent program, let
                    through always and only to its own provider's hosts (`harness_hosts`), never
                    to a package index
    what is kept    a count and the host of each request, let through or refused. Never a path,
                    a header or a body

What it does not do: it cannot tell a download from an upload inside a tunnel. The list therefore
holds package indexes only, none of which takes an upload without a key of the person's, and no
such key is inside the sandbox.
"""

import asyncio
import base64
import contextlib
import logging
import secrets
import socket
import time
from collections import deque
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

HOSTS_FILE = Path(__file__).with_name("coding_install_hosts.txt")
AGENT, PERSON = "agent", "person"
PORT = 443
HEAD_LIMIT = 16_384
HEAD_WAIT_S = 10.0
CONNECT_WAIT_S = 15.0
WINDOW_S = 600.0  # how long the agent's commands are let through after an install was allowed
KEPT = 200


def read_hosts(path: Path = HOSTS_FILE) -> tuple[str, ...]:
    """The hosts on the list: one a line, `#` starts a comment."""
    found = []
    for line in path.read_text().splitlines():
        name = line.split("#", 1)[0].strip().lower()
        if name:
            found.append(name)
    return tuple(dict.fromkeys(found))


class InstallProxy:
    def __init__(
        self,
        hosts: Sequence[str] | None = None,
        *,
        window_s: float = WINDOW_S,
        port: int = PORT,
        harness_hosts: Mapping[str, Sequence[str]] | None = None,
    ):
        """`port` is the one port a tunnel may go to; only tests give another. `harness_hosts`
        gives each harness its provider's hosts: a host is let through when it is one of them or
        ends in "." and one of them."""
        self.hosts = frozenset(h.lower() for h in (read_hosts() if hosts is None else hosts))
        self.window_s, self.port = window_s, port
        self.harness_hosts = {
            name: frozenset(h.lower() for h in found)
            for name, found in (harness_hosts or {}).items()
        }
        self._tokens = {AGENT: secrets.token_urlsafe(24), PERSON: secrets.token_urlsafe(24)}
        for name in self.harness_hosts:
            self._tokens[name] = secrets.token_urlsafe(24)
        self._open_until = 0.0
        self._sock: socket.socket | None = None
        self._server: asyncio.Server | None = None
        self._tunnels: set[asyncio.Task[None]] = set()
        self.seen: deque[dict[str, Any]] = deque(maxlen=KEPT)
        self.let_through = 0
        self.refused = 0

    # ---- its address ---------------------------------------------------------------------------

    def bind(self) -> int:
        """Take a free port on loopback now; connections wait until `start`. Gives the port."""
        if self._sock is None:
            sock = socket.socket()
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", 0))
            sock.listen(64)
            sock.setblocking(False)
            self._sock = sock
        return int(self._sock.getsockname()[1])

    @property
    def address(self) -> str:
        return f"127.0.0.1:{self.bind()}"

    def url_for(self, who: str) -> str:
        """The proxy's address with one name's password in it, for a program's environment."""
        return f"http://{who}:{self._tokens[who]}@{self.address}"

    async def start(self) -> None:
        if self._server is None:
            self.bind()
            self._server = await asyncio.start_server(self._serve, sock=self._sock)

    async def close(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.close()
            with contextlib.suppress(Exception):
                await server.wait_closed()
        elif self._sock is not None:
            self._sock.close()
        self._sock = None
        for task in list(self._tunnels):
            task.cancel()
        await asyncio.gather(*self._tunnels, return_exceptions=True)

    # ---- the agent's window --------------------------------------------------------------------

    def open_for_agent(self, seconds: float | None = None) -> None:
        """An install step was let through: the agent's commands may fetch for a while."""
        self._open_until = time.monotonic() + (self.window_s if seconds is None else seconds)

    def close_for_agent(self) -> None:
        self._open_until = 0.0

    @property
    def open_to_agent(self) -> bool:
        return time.monotonic() < self._open_until

    # ---- one connection ------------------------------------------------------------------------

    def _who(self, head: dict[str, str]) -> str | None:
        given = head.get("proxy-authorization", "")
        if not given.lower().startswith("basic "):
            return None
        try:
            name, _, password = base64.b64decode(given[6:]).decode().partition(":")
        except ValueError:
            return None
        known = self._tokens.get(name)
        return name if known and secrets.compare_digest(known, password) else None

    def _judge(self, method: str, target: str, head: dict[str, str]) -> tuple[int, str, str]:
        """(status, why, host): 200 lets a tunnel through."""
        host, _, port = target.rpartition(":")
        host = host.strip("[]").lower()
        if method != "CONNECT":
            return 405, "only_https", host or target[:80]
        who = self._who(head)
        if who is None:
            return 407, "who", host
        if not port.isdigit() or int(port) != self.port:
            return 403, "port", host
        if who in self.harness_hosts:
            # a harness reaches its own provider and nothing else, a package index included
            mine = self.harness_hosts[who]
            if host in mine or any(host.endswith("." + h) for h in mine):
                return 200, who, host
            return 403, "not_the_provider", host
        if host not in self.hosts:
            return 403, "not_on_the_list", host
        if who == AGENT and not self.open_to_agent:
            return 403, "no_install_allowed", host
        return 200, who, host

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._tunnels.add(task)
        try:
            await self._handle(reader, writer)
        except (OSError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
            pass
        finally:
            if task is not None:
                self._tunnels.discard(task)
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), HEAD_WAIT_S)
        if len(raw) > HEAD_LIMIT:
            return
        lines = raw.decode("latin-1").split("\r\n")
        parts = lines[0].split()
        if len(parts) != 3:
            return
        head = {}
        for line in lines[1:]:
            name, sep, value = line.partition(":")
            if sep:
                head[name.strip().lower()] = value.strip()
        status, why, host = self._judge(parts[0].upper(), parts[1], head)
        self.seen.append({"host": host[:200], "ok": status == 200, "why": why, "at": time.time()})
        if status != 200:
            self.refused += 1
            log.info("the install proxy refused %s (%s)", host[:200], why)
            said = {405: "Method Not Allowed", 407: "Proxy Authentication Required"}.get(
                status, "Forbidden"
            )
            more = 'Proxy-Authenticate: Basic realm="wasify"\r\n' if status == 407 else ""
            body = f"Wasify AI: this is not allowed from inside the coding sandbox ({why}).\n"
            writer.write(
                f"HTTP/1.1 {status} {said}\r\n{more}Content-Type: text/plain\r\n"
                f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n{body}".encode()
            )
            await writer.drain()
            return
        try:
            up_reader, up_writer = await asyncio.wait_for(
                asyncio.open_connection(host, self.port), CONNECT_WAIT_S
            )
        except (OSError, TimeoutError):
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
            await writer.drain()
            return
        self.let_through += 1
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        try:
            await asyncio.gather(_pump(reader, up_writer), _pump(up_reader, writer))
        finally:
            up_writer.close()
            with contextlib.suppress(Exception):
                await up_writer.wait_closed()

    def state(self) -> dict[str, Any]:
        """For diagnostics: never a password."""
        return {
            "hosts": sorted(self.hosts),
            "harness_hosts": {k: sorted(v) for k, v in self.harness_hosts.items()},
            "open_to_agent": self.open_to_agent,
            "let_through": self.let_through,
            "refused": self.refused,
        }


async def _pump(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while chunk := await reader.read(65536):
            writer.write(chunk)
            await writer.drain()
    except (OSError, asyncio.IncompleteReadError):
        pass
    finally:
        with contextlib.suppress(Exception):
            writer.close()
