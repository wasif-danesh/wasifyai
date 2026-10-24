"""The sandbox a Motion graphics render runs in (ADR-0077 decision 4, stage V1b).

A composition is code written by a model or taken from the web, and HyperFrames renders it in a
browser. The stock render starts that browser with `--no-sandbox`, popups allowed and no network
limit; spike V0 (`docs/spikes/video-builder-v0.md`) rendered a hostile composition through the real
command line and it reached a service on localhost and a remote host. This module closes that
without changing HyperFrames:

    launcher        HyperFrames starts whatever file `HYPERFRAMES_BROWSER_PATH` names. We name a
                    small script that drops the flags that weaken the sandbox and adds the lock-down
                    before it starts the pinned browser. It refuses to start without the filter.
    FilterProxy     the browser reaches the network only through this proxy on loopback, which
                    forwards to one place: the render's own file server (the first loopback port the
                    browser asks for, learned once; the composition cannot have run before that).
                    Everything else is closed and written to a list the screen can show.
    lint_project    a first line before the compiler: HyperFrames' compiler downloads CDN scripts in
                    Node, outside the browser, so non-local URLs are refused before it sees them. It
                    is not the security boundary (the proxy is); it gives a clear message early.
    run_render      runs the render in its own process group with a wall-time limit, a stall limit
                    and a memory watchdog that samples the process tree, and kills the whole tree
                    on cancel, on a limit and on quit. The environment starts empty.

Not covered (recorded in the ADR): CPU time beyond the wall limit, a popup window (it sits behind
the
same proxy) and Windows and Linux (nothing measured there)."""

import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
import signal
import tempfile
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from wasifyai_api.video_builder_runtime import VideoBuilderInstall, render_env

log = logging.getLogger(__name__)

LOOPBACK = ("127.0.0.1", "localhost", "[::1]", "::1")
MAX_HEAD = 64 * 1024


# ---- the filter ----------------------------------------------------------------------------------


class FilterProxy:
    """A proxy on loopback that forwards to one port. With `allowed_port` None it learns the port
    from
    the first request to loopback and holds to it; every other request is closed and counted."""

    def __init__(self, allowed_port: int | None = None) -> None:
        self.allowed_port = allowed_port
        self.blocked: deque[str] = deque(maxlen=200)
        self.blocked_count = 0
        self.forwarded = 0
        self._server: asyncio.base_events.Server | None = None
        self.port = 0

    async def start(self) -> int:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self.port

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._server.wait_closed(), 2)

    def _block(self, method: str, host: str, port: str) -> None:
        self.blocked_count += 1
        self.blocked.append(f"{method} {host}:{port}")

    @staticmethod
    async def _pipe(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        try:
            while data := await r.read(65536):
                w.write(data)
                await w.drain()
        except (OSError, asyncio.CancelledError, ConnectionError):
            pass
        finally:
            with contextlib.suppress(Exception):
                w.close()

    @staticmethod
    def _target(method: str, target: str) -> tuple[str, str]:
        if method == "CONNECT":
            host, _, port = target.rpartition(":")
            return host.strip("[]") if host.startswith("[") else host, port
        parts = urlsplit(target)
        scheme_port = "443" if parts.scheme == "https" else "80"
        return parts.hostname or "", str(parts.port or scheme_port)

    async def _handle(self, cr: asyncio.StreamReader, cw: asyncio.StreamWriter) -> None:
        uw: asyncio.StreamWriter | None = None
        try:
            head = await asyncio.wait_for(cr.readuntil(b"\r\n\r\n"), 15)
            if len(head) > MAX_HEAD:
                raise ValueError("head too long")
            line = head.split(b"\r\n", 1)[0].decode("latin1")
            method, target, _ = line.split(" ", 2)
            host, port = self._target(method, target)
            if self.allowed_port is None and host in LOOPBACK and port.isdigit():
                self.allowed_port = int(port)  # the render's own file server, asked for first
            if host not in LOOPBACK or port != str(self.allowed_port):
                self._block(method, host, port)
                return  # the connection closes: the page sees a failed request, not a response
            ur, uw = await asyncio.open_connection("127.0.0.1", int(port))
            self.forwarded += 1
            if method == "CONNECT":
                cw.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
                await cw.drain()
            else:  # absolute-form to origin-form
                parts = urlsplit(target)
                path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
                uw.write(head.replace(target.encode(), path.encode(), 1))
                await uw.drain()
            await asyncio.gather(self._pipe(cr, uw), self._pipe(ur, cw))
        except (OSError, ValueError, asyncio.IncompleteReadError, TimeoutError):
            pass
        finally:
            for w in (cw, uw):
                if w is not None:
                    with contextlib.suppress(Exception):
                        w.close()


# ---- the launcher --------------------------------------------------------------------------------

LAUNCHER = r"""#!/bin/bash
# Written by Wasify AI (video_builder_sandbox.py). HyperFrames starts this instead of the browser.
# It never starts the browser without the filter and a home folder of its own.
[ -n "$VB_REAL_BROWSER" ] && [ -n "$VB_PROXY_PORT" ] && [ -n "$VB_BROWSER_HOME" ] || exit 97
args=()
for a in "$@"; do
  case "$a" in
    --no-sandbox|--disable-setuid-sandbox|--disable-popup-blocking|--enable-automation) ;;
    *) args+=("$a") ;;
  esac
done
export HOME="$VB_BROWSER_HOME"
exec "$VB_REAL_BROWSER" "${args[@]}" \
  "--proxy-server=http://127.0.0.1:$VB_PROXY_PORT" "--proxy-bypass-list=<-loopback>" \
  "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1" \
  --force-webrtc-ip-handling-policy=disable_non_proxied_udp \
  --deny-permission-prompts --disable-sync --disable-component-update \
  --disable-background-networking --no-first-run --no-default-browser-check \
  --disable-domain-reliability --no-pings --mute-audio --disable-breakpad \
  --metrics-recording-only --safebrowsing-disable-auto-update \
  --disable-client-side-phishing-detection
"""


def write_launcher(install: VideoBuilderInstall) -> Path:
    path = install.root / "bin" / "launch-browser"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file() or path.read_text() != LAUNCHER:
        path.write_text(LAUNCHER)
    path.chmod(0o755)
    return path


# ---- lint ----------------------------------------------------------------------------------------

TEXT_SUFFIXES = {".html", ".htm", ".css", ".js", ".mjs", ".svg", ".json"}
SKIP_DIRS = {"vendor", "fonts", "node_modules"}
URL_ATTR = re.compile(
    r"""\b(?:src|href|data|poster|action|xlink:href|srcset)\s*=\s*["']?\s*([^"'\s>]+)""", re.I
)
CSS_URL = re.compile(r"""url\(\s*["']?([^"')]+)""", re.I)
CSS_IMPORT = re.compile(r"""@import\s+["']([^"']+)""", re.I)
REMOTE_LITERAL = re.compile(r"""\b(?:https?|wss?|ftp)://[^\s"'<>)\\]+""", re.I)
FILE_LITERAL = re.compile(r"""\bfile:""", re.I)
NETWORK_API = re.compile(
    r"\b(?:fetch|XMLHttpRequest|WebSocket|EventSource|RTCPeerConnection|importScripts|"
    r"sendBeacon|WebTransport|SharedWorker|ServiceWorker|serviceWorker)\b"
)
DYNAMIC_CODE = re.compile(r"\b(?:eval|Function)\s*\(|\bimport\s*\(|\bwindow\.open\s*\(")
HARMLESS_NAMESPACES = ("http://www.w3.org/", "https://www.w3.org/")


@dataclass(frozen=True)
class LintFinding:
    file: str
    line: int
    code: str  # remote_url | file_url | path_escape | network_api | dynamic_code
    message: str


def _local(ref: str) -> bool:
    ref = ref.strip()
    if not ref or ref.startswith(("#", "data:", "blob:")):
        return True
    return not (re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", ref) or ref.startswith("//"))


def lint_project(project: Path) -> list[LintFinding]:
    """Findings that stop a render. A project with none is not thereby safe; the filter is the
    boundary. Files under vendor/ and fonts/ are not read (they are minified libraries and
    fonts)."""
    findings: list[LintFinding] = []
    root = project.resolve()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        rel = path.relative_to(root)
        if SKIP_DIRS & set(rel.parts[:-1]):
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for ref in [*URL_ATTR.findall(line), *CSS_URL.findall(line), *CSS_IMPORT.findall(line)]:
                if not _local(ref):
                    findings.append(
                        LintFinding(str(rel), number, "remote_url", f"a link to {ref[:80]}")
                    )
                elif ".." in Path(ref.split("?")[0].split("#")[0]).parts:
                    resolved = (path.parent / ref.split("?")[0].split("#")[0]).resolve()
                    if root not in (resolved, *resolved.parents):
                        findings.append(
                            LintFinding(
                                str(rel), number, "path_escape", f"a path outside: {ref[:80]}"
                            )
                        )
            for m in REMOTE_LITERAL.finditer(line):
                if not m.group(0).startswith(HARMLESS_NAMESPACES):
                    findings.append(
                        LintFinding(str(rel), number, "remote_url", f"an address {m.group(0)[:80]}")
                    )
            if FILE_LITERAL.search(line):
                findings.append(LintFinding(str(rel), number, "file_url", "a file: address"))
            if path.suffix.lower() != ".css":
                if NETWORK_API.search(line):
                    findings.append(
                        LintFinding(str(rel), number, "network_api", "it asks for the network")
                    )
                if DYNAMIC_CODE.search(line):
                    findings.append(
                        LintFinding(str(rel), number, "dynamic_code", "it loads or runs other code")
                    )
    # one finding per (file, line, code)
    seen: set[tuple[str, int, str]] = set()
    unique = []
    for f in findings:
        key = (f.file, f.line, f.code)
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def describe_findings(findings: list[LintFinding], limit: int = 5) -> str:
    shown = "; ".join(f"{f.file} line {f.line}: {f.message}" for f in findings[:limit])
    more = f" (and {len(findings) - limit} more)" if len(findings) > limit else ""
    return f"This video cannot be made because it reaches outside its own folder: {shown}{more}."


# ---- limits and the guard -----------------------------------------------------------------------


@dataclass(frozen=True)
class RenderLimits:
    wall_s: float = 900.0  # the whole render
    stall_s: float = 120.0  # no output at all from the render
    rss_bytes: int = (
        4 * 1024**3
    )  # the process tree's resident memory (V0: a 25 ms poll overshoots ~0.1 GB)
    poll_s: float = 0.025


@dataclass
class RenderResult:
    ok: bool
    reason: str | None = None  # refused | wall_time | stalled | memory | cancelled | failed
    message: str = ""
    seconds: float = 0.0
    peak_rss_bytes: int = 0
    blocked: list[str] = field(default_factory=list)
    blocked_count: int = 0
    output: Path | None = None
    log_tail: str = ""
    downloads_discarded: list[str] = field(default_factory=list)  # files a page tried to save
    lines: list[str] = field(default_factory=list)  # everything the command printed (bounded)


def _made(output: Path) -> bool:
    """A file that exists, or a folder with something in it."""
    if output.is_dir():
        return any(output.iterdir())
    return output.is_file()


async def _ps_tree(root_pid: int) -> tuple[int, list[int]]:
    """The summed resident memory (bytes) and the pids of a process and everything under it."""
    proc = await asyncio.create_subprocess_exec(
        "ps", "-A", "-o", "pid=,ppid=,rss=",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )  # fmt: skip
    out, _ = await proc.communicate()
    children: dict[int, list[int]] = {}
    rss: dict[int, int] = {}
    for row in out.decode().splitlines():
        parts = row.split()
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            pid, ppid, kb = (int(p) for p in parts)
            rss[pid] = kb * 1024
            children.setdefault(ppid, []).append(pid)
    pids, stack = [], [root_pid]
    while stack:
        pid = stack.pop()
        pids.append(pid)
        stack.extend(children.get(pid, ()))
    return sum(rss.get(p, 0) for p in pids), pids


def _kill_tree(pgid: int | None, pids: list[int]) -> None:
    if pgid is not None:
        with contextlib.suppress(OSError):
            os.killpg(pgid, signal.SIGKILL)
    for pid in pids:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGKILL)


async def run_render(
    install: VideoBuilderInstall,
    project: Path,
    output: Path,
    *,
    limits: RenderLimits | None = None,
    extra_args: tuple[str, ...] = (),
    on_progress: Callable[[str], None] | None = None,
    skip_lint: bool = False,
) -> RenderResult:
    """Render a project to the file `output` inside the sandbox."""
    return await run_command(
        install, project, ("render", "--output", str(output), *extra_args), output,
        limits=limits, on_progress=on_progress, skip_lint=skip_lint,
    )  # fmt: skip


async def run_snapshot(
    install: VideoBuilderInstall,
    project: Path,
    folder: Path,
    at: float,
    *,
    limits: RenderLimits | None = None,
) -> RenderResult:
    """One still of the composition at `at` seconds, written as a PNG in `folder`, inside the same
    sandbox (a model can look at it; a person sees it as the preview)."""
    return await run_command(
        install, project, ("snapshot", "--output", str(folder), "--at", f"{at:g}", "--no-end"),
        folder, limits=limits or RenderLimits(wall_s=120, stall_s=60),
    )  # fmt: skip


CHECK_SCRIPT = Path(__file__).with_name("video_builder") / "check.mjs"


async def run_check(
    install: VideoBuilderInstall,
    project: Path,
    spec: dict[str, Any],
    *,
    limits: RenderLimits | None = None,
) -> tuple[RenderResult, dict[str, Any] | None]:
    """Open a composition in the sandbox and report what is drawn at the moments in `spec` (the
    exact-text check, ADR-0079). The report is what the script saw; nothing is decided here."""
    script = install.app / "check.mjs"
    text = await asyncio.to_thread(CHECK_SCRIPT.read_text)
    if not script.is_file() or script.read_text() != text:
        await asyncio.to_thread(script.write_text, text)
    spec_file = Path(render_env(install)["TMPDIR"]) / f"check-{uuid.uuid4().hex}.json"
    await asyncio.to_thread(spec_file.write_text, json.dumps({**spec, "project": str(project)}))
    try:
        result = await run_command(
            install, project, (str(spec_file),), None, entry=script,
            limits=limits or RenderLimits(wall_s=90, stall_s=60),
        )  # fmt: skip
    finally:
        spec_file.unlink(missing_ok=True)
    report = None
    for line in result.lines:
        if line.startswith("RESULT "):
            try:
                report = json.loads(line[len("RESULT ") :])
            except ValueError:
                report = None
    return result, report


async def run_command(
    install: VideoBuilderInstall,
    project: Path,
    command: tuple[str, ...],
    output: Path | None,
    *,
    limits: RenderLimits | None = None,
    on_progress: Callable[[str], None] | None = None,
    skip_lint: bool = False,
    entry: Path | None = None,
) -> RenderResult:
    """Run one HyperFrames command on a project inside the sandbox; `output` is the file (or the
    folder with something in it) the command must have made. Never raises for a bad composition:
    the answer says what happened in words."""
    limits = limits or RenderLimits()
    if not skip_lint:
        findings = lint_project(project)
        if findings:
            return RenderResult(False, "refused", describe_findings(findings))
    if not (project / "index.html").is_file():
        return RenderResult(False, "refused", "This video has no index.html to render.")
    launcher = write_launcher(install)
    if output is not None:
        (output if output.suffix == "" else output.parent).mkdir(parents=True, exist_ok=True)
    proxy = FilterProxy()
    proxy_port = await proxy.start()
    browser_home = Path(tempfile.mkdtemp(prefix="browser-", dir=render_env(install)["TMPDIR"]))
    env = render_env(
        install,
        {
            "HYPERFRAMES_BROWSER_PATH": str(launcher),
            "PRODUCER_HEADLESS_SHELL_PATH": str(launcher),
            "VB_REAL_BROWSER": str(install.shell),
            "VB_PROXY_PORT": str(proxy_port),
            "VB_BROWSER_HOME": str(browser_home),
        },
    )
    started = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        str(install.node), str(entry or install.cli), *command,
        cwd=str(project), env=env, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )  # fmt: skip
    pgid = proc.pid  # its own session, so its own group
    tail: deque[str] = deque(maxlen=40)
    collected: list[str] = []
    last_output = time.monotonic()
    peak = 0
    killed: str | None = None
    discarded: list[str] = []

    async def read_output() -> None:
        nonlocal last_output
        assert proc.stdout is not None
        async for raw in proc.stdout:
            last_output = time.monotonic()
            line = raw.decode(errors="replace").rstrip()
            tail.append(line)
            if len(collected) < 4000:
                collected.append(line)
            if on_progress is not None and line:
                on_progress(line)

    reader = asyncio.create_task(read_output())
    try:
        while proc.returncode is None:
            try:
                await asyncio.wait_for(proc.wait(), limits.poll_s)
                break
            except TimeoutError:
                pass
            used, pids = await _ps_tree(proc.pid)
            peak = max(peak, used)
            now = time.monotonic()
            if used > limits.rss_bytes:
                killed = "memory"
            elif now - started > limits.wall_s:
                killed = "wall_time"
            elif now - last_output > limits.stall_s:
                killed = "stalled"
            if killed:
                _kill_tree(pgid, pids)
                break
        await asyncio.wait_for(proc.wait(), 10)
    except asyncio.CancelledError:
        killed = "cancelled"
        _, pids = await _ps_tree(proc.pid)
        _kill_tree(pgid, pids)
        raise
    finally:
        if proc.returncode is None:
            _, pids = await _ps_tree(proc.pid)
            _kill_tree(pgid, pids)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(proc.wait(), 5)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(reader, 5)
        await proxy.stop()
        with contextlib.suppress(OSError):
            discarded = sorted(p.name for p in (browser_home / "Downloads").glob("*"))
        shutil.rmtree(browser_home, ignore_errors=True)
    seconds = time.monotonic() - started
    result = RenderResult(
        ok=False, seconds=seconds, peak_rss_bytes=peak, blocked=list(proxy.blocked),
        blocked_count=proxy.blocked_count, log_tail="\n".join(tail)[-1500:],
        downloads_discarded=discarded, lines=collected,
    )  # fmt: skip
    if killed:
        result.reason = killed
        result.message = {
            "memory": "The video was stopped because it asked for too much memory.",
            "wall_time": "The video was stopped because it took too long to make.",
            "stalled": "The video was stopped because it stopped making progress.",
            "cancelled": "The video was cancelled.",
        }[killed]
    elif proc.returncode != 0 or (
        output is not None and not await asyncio.to_thread(_made, output)
    ):
        result.reason = "failed"
        result.message = "The video could not be made."
    else:
        result.ok = True
        result.output = output
        result.message = "Done."
    return result
