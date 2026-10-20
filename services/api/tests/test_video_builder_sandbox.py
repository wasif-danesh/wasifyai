"""The sandbox of a Video Builder render (V1b) on stand-ins: the filter, the launcher, the lint step
and the guard. The real browser against hostile compositions is `test_video_builder_hostile.py`."""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from wasifyai_api import video_builder_sandbox as sb
from wasifyai_api.video_builder_runtime import VideoBuilderInstall

# ---- the filter ----------------------------------------------------------------------------------


async def origin(body: bytes) -> tuple[asyncio.base_events.Server, int, list[bytes]]:
    seen: list[bytes] = []

    async def handle(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        head = await r.readuntil(b"\r\n\r\n")
        seen.append(head)
        w.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n%s"
            % (len(body), body)
        )
        await w.drain()
        w.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1], seen


async def through(proxy_port: int, request: bytes) -> bytes:
    r, w = await asyncio.open_connection("127.0.0.1", proxy_port)
    w.write(request)
    await w.drain()
    try:
        return await asyncio.wait_for(r.read(), 5)
    finally:
        w.close()


async def test_the_proxy_forwards_to_the_first_loopback_port_and_nothing_else():
    render, render_port, render_seen = await origin(b"the video page")
    canary, canary_port, canary_seen = await origin(b"canary")
    proxy = sb.FilterProxy()
    port = await proxy.start()
    try:
        request = f"GET http://localhost:{render_port}/index.html?a=1 HTTP/1.1\r\nHost: x\r\n\r\n"
        ok = await through(port, request.encode())
        assert b"200 OK" in ok and ok.endswith(b"the video page")
        # the origin sees an ordinary request, not the proxy's absolute form
        assert render_seen[0].startswith(b"GET /index.html?a=1 HTTP/1.1")
        assert proxy.allowed_port == render_port and proxy.forwarded == 1

        for request in (
            f"GET http://127.0.0.1:{canary_port}/steal HTTP/1.1\r\nHost: x\r\n\r\n",  # another port
            "CONNECT example.com:443 HTTP/1.1\r\nHost: example.com\r\n\r\n",  # the internet
            "GET http://example.com/ HTTP/1.1\r\nHost: example.com\r\n\r\n",
            f"CONNECT 127.0.0.1:{canary_port} HTTP/1.1\r\nHost: x\r\n\r\n",
        ):
            assert await through(port, request.encode()) == b""  # closed: no response at all
        assert canary_seen == []  # the other service was never touched
        assert proxy.blocked_count == 4
        assert "CONNECT example.com:443" in proxy.blocked
        assert f"GET 127.0.0.1:{canary_port}" in proxy.blocked
    finally:
        await proxy.stop()
        render.close()
        canary.close()


async def test_a_composition_cannot_choose_the_port_because_the_first_one_asked_wins():
    other, other_port, other_seen = await origin(b"other")
    render, render_port, _ = await origin(b"page")
    proxy = sb.FilterProxy()
    port = await proxy.start()
    try:
        await through(port, f"GET http://127.0.0.1:{render_port}/ HTTP/1.1\r\n\r\n".encode())
        assert (
            await through(port, f"GET http://127.0.0.1:{other_port}/ HTTP/1.1\r\n\r\n".encode())
            == b""
        )
        assert other_seen == []
    finally:
        await proxy.stop()
        other.close()
        render.close()


async def test_garbage_and_oversized_requests_are_dropped_without_a_crash():
    proxy = sb.FilterProxy(allowed_port=1)
    port = await proxy.start()
    try:
        assert await through(port, b"\x00\x01nonsense\r\n\r\n") == b""
        assert await through(port, b"GET\r\n\r\n") == b""
        assert (
            await through(
                port, b"GET http://127.0.0.1:1/ HTTP/1.1\r\n" + b"X: " + b"a" * 70000 + b"\r\n\r\n"
            )
            == b""
        )
    finally:
        await proxy.stop()


async def test_only_a_fixed_port_when_one_is_given():
    other, other_port, other_seen = await origin(b"other")
    proxy = sb.FilterProxy(allowed_port=65000)
    port = await proxy.start()
    try:
        assert (
            await through(port, f"GET http://127.0.0.1:{other_port}/ HTTP/1.1\r\n\r\n".encode())
            == b""
        )
        assert other_seen == [] and proxy.blocked_count == 1
    finally:
        await proxy.stop()
        other.close()


# ---- the launcher --------------------------------------------------------------------------------


def fake_install(root: Path, mode: str = "ok") -> VideoBuilderInstall:
    """A component whose `node` is a shell script, so the guard can be tried without a browser."""
    node = root / "node" / "bin" / "node"
    node.parent.mkdir(parents=True)
    node.write_text(
        "#!/bin/bash\n"
        'mode=$(cat "$1")\n'
        'shift; shift; shift; out="$1"\n'  # <cli> render --output <out>
        'case "$mode" in\n'
        '  ok) echo "render 50%"; echo "render 100%"; echo mp4 > "$out";;\n'
        "  silent_loop) while true; do :; done;;\n"
        "  chatter) while true; do echo working; sleep 0.05; done;;\n"
        f"  memory) {sys.executable} -c "
        '"b = bytearray(700*1024*1024); import time; time.sleep(30)";;\n'
        '  fail) echo "boom"; exit 3;;\n'
        "  nothing) exit 0;;\n"
        "esac\n"
    )
    node.chmod(0o755)
    cli = root / "app" / "cli.mjs"
    cli.parent.mkdir(parents=True)
    cli.write_text(mode)
    shell = root / "shell" / "chrome-headless-shell"
    shell.parent.mkdir(parents=True)
    shell.write_text("#!/bin/bash\n")
    shell.chmod(0o755)
    return VideoBuilderInstall(root, node, shell, cli, root / "app", "managed")


def test_the_launcher_drops_the_weak_flags_adds_the_lock_down_and_keeps_the_rest(tmp_path):
    install = fake_install(tmp_path / "c")
    real = tmp_path / "real-browser"
    real.write_text('#!/bin/bash\nfor a in "$@"; do echo "ARG:$a"; done\necho "HOME:$HOME"\n')
    real.chmod(0o755)
    launcher = sb.write_launcher(install)
    env = {
        "VB_REAL_BROWSER": str(real),
        "VB_PROXY_PORT": "4242",
        "VB_BROWSER_HOME": str(tmp_path / "h"),
    }
    out = subprocess.run(
        [str(launcher), "--no-sandbox", "--headless=new", "--disable-setuid-sandbox",
         "--disable-popup-blocking", "--enable-automation", "--user-data-dir=/x",
         "--remote-debugging-port=0"],
        env=env, capture_output=True, text=True, check=True,
    ).stdout.splitlines()  # fmt: skip
    args = {line[4:] for line in out if line.startswith("ARG:")}
    for weak in (
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-popup-blocking",
        "--enable-automation",
    ):
        assert weak not in args
    assert {"--headless=new", "--user-data-dir=/x", "--remote-debugging-port=0"} <= args
    assert (
        "--proxy-server=http://127.0.0.1:4242" in args and "--proxy-bypass-list=<-loopback>" in args
    )
    assert (
        "--deny-permission-prompts" in args
        and "--force-webrtc-ip-handling-policy=disable_non_proxied_udp" in args
    )
    assert any(a.startswith("--host-resolver-rules=MAP * ~NOTFOUND") for a in args)
    assert f"HOME:{tmp_path / 'h'}" in out  # downloads and defaults land in a throwaway home


@pytest.mark.parametrize("missing", ["VB_REAL_BROWSER", "VB_PROXY_PORT", "VB_BROWSER_HOME"])
def test_the_launcher_never_starts_the_browser_without_the_filter(tmp_path, missing):
    install = fake_install(tmp_path / "c")
    launcher = sb.write_launcher(install)
    env = {"VB_REAL_BROWSER": "/bin/echo", "VB_PROXY_PORT": "1", "VB_BROWSER_HOME": str(tmp_path)}
    del env[missing]
    done = subprocess.run([str(launcher)], env=env, capture_output=True, text=True)
    assert done.returncode == 97 and done.stdout == ""


def test_the_launcher_file_is_rewritten_if_someone_changed_it(tmp_path):
    install = fake_install(tmp_path / "c")
    path = sb.write_launcher(install)
    path.write_text('#!/bin/bash\nexec "$VB_REAL_BROWSER" --no-sandbox\n')
    sb.write_launcher(install)
    assert path.read_text() == sb.LAUNCHER and os.access(path, os.X_OK)


# ---- lint ----------------------------------------------------------------------------------------


def project(tmp_path: Path, html: str, **files: str) -> Path:
    p = tmp_path / "p"
    p.mkdir()
    (p / "index.html").write_text(html)
    for name, text in files.items():
        f = p / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    return p


CLEAN = """<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="style.css">
<script src="vendor/gsap.min.js"></script></head><body>
<div id="root" data-composition-id="main" data-width="1280" data-height="720"
 style="background:url(img/bg.png)"><img src="img/logo.png"><svg xmlns="http://www.w3.org/2000/svg"></svg></div>
<script>const tl = gsap.timeline({paused: true}); window.__timelines = {main: tl};</script>
</body></html>"""


def test_a_plain_composition_passes_the_lint(tmp_path):
    p = project(
        tmp_path, CLEAN, **{"style.css": "@import url('fonts.css'); a{background:url(img/x.png)}"}
    )
    assert sb.lint_project(p) == []


@pytest.mark.parametrize(
    ("html", "code"),
    [
        ('<script src="https://cdn.jsdelivr.net/npm/gsap"></script>', "remote_url"),
        ('<link href="//fonts.googleapis.com/css?family=Inter" rel="stylesheet">', "remote_url"),
        ('<img src="http://127.0.0.1:59999/x">', "remote_url"),
        ('<style>@import "https://x.test/a.css";</style>', "remote_url"),
        ("<style>a{background:url(https://x.test/a.png)}</style>", "remote_url"),
        ("<script>fetch('/x')</script>", "network_api"),
        ("<script>new WebSocket(u)</script>", "network_api"),
        ("<script>navigator.sendBeacon(u)</script>", "network_api"),
        ("<script>eval('1')</script>", "dynamic_code"),
        ("<script>import('./x.js')</script>", "dynamic_code"),
        ("<script>window.open('about:blank')</script>", "dynamic_code"),
        (
            "<script>var s=document.createElement('script');s.src='file:///etc/x'</script>",
            "file_url",
        ),
        ('<script src="../../secret.js"></script>', "path_escape"),
    ],
)
def test_the_lint_refuses_what_reaches_outside_the_folder(tmp_path, html, code):
    findings = sb.lint_project(project(tmp_path, html))
    assert code in {f.code for f in findings}, findings


def test_the_lint_does_not_read_vendored_libraries_and_describes_findings_in_words(tmp_path):
    p = project(
        tmp_path,
        '<script src="vendor/lib.js"></script><script>fetch("/x")</script>',
        **{"vendor/lib.js": "fetch('https://gsap.com'); eval('1')"},
    )
    findings = sb.lint_project(p)
    assert {f.file for f in findings} == {"index.html"}
    words = sb.describe_findings(findings)
    assert words.startswith("This video cannot be made") and "index.html line 1" in words


# ---- the guard -----------------------------------------------------------------------------------


async def run(tmp_path, mode, **limits):
    install = fake_install(tmp_path / "c", mode)
    proj = tmp_path / "proj"
    proj.mkdir(exist_ok=True)
    (proj / "index.html").write_text("<p>x</p>")
    return await sb.run_render(
        install, proj, tmp_path / "out" / "x.mp4", limits=sb.RenderLimits(**limits), skip_lint=True
    )


async def test_a_render_that_works_returns_its_file(tmp_path):
    seen: list[str] = []
    install = fake_install(tmp_path / "c", "ok")
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "index.html").write_text("<p>x</p>")
    result = await sb.run_render(install, proj, tmp_path / "x.mp4", on_progress=seen.append)
    assert result.ok and result.output is not None and result.output.is_file()
    assert result.reason is None and "render 100%" in seen and result.seconds < 5


async def test_a_render_that_does_not_end_cleanly_is_a_plain_failure(tmp_path):
    for mode in ("fail", "nothing"):
        result = await run(tmp_path / mode, mode)
        assert (
            not result.ok
            and result.reason == "failed"
            and result.message == "The video could not be made."
        )
    assert "boom" in (await run(tmp_path / "again", "fail")).log_tail


async def test_a_loop_that_prints_nothing_is_stopped_and_nothing_is_left_running(tmp_path):
    started = time.monotonic()
    result = await run(tmp_path, "silent_loop", stall_s=0.6)
    assert result.reason == "stalled" and "stopped making progress" in result.message
    assert time.monotonic() - started < 6
    assert not leftovers(tmp_path)


async def test_a_render_that_takes_too_long_is_stopped_even_if_it_keeps_talking(tmp_path):
    result = await run(tmp_path, "chatter", wall_s=0.8, stall_s=30)
    assert result.reason == "wall_time" and "too long" in result.message
    assert not leftovers(tmp_path)


async def test_a_render_that_eats_memory_is_stopped_near_its_limit(tmp_path):
    limit = 300 * 1024**2
    result = await run(tmp_path, "memory", rss_bytes=limit, wall_s=20, stall_s=30)
    assert result.reason == "memory" and "too much memory" in result.message
    assert (
        limit < result.peak_rss_bytes < limit + 900 * 1024**2
    )  # stopped before it reached 700 MB more
    assert not leftovers(tmp_path)


async def test_cancelling_stops_the_whole_tree(tmp_path):
    task = asyncio.create_task(run(tmp_path, "chatter", wall_s=60, stall_s=60))
    await asyncio.sleep(0.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not leftovers(tmp_path)


async def test_a_composition_the_lint_refuses_is_never_started(tmp_path):
    install = fake_install(tmp_path / "c", "ok")
    proj = project(tmp_path, '<script src="https://cdn.example/gsap.js"></script>')
    result = await sb.run_render(install, proj, tmp_path / "x.mp4")
    assert result.reason == "refused" and "reaches outside its own folder" in result.message
    assert not (tmp_path / "x.mp4").exists() and result.seconds == 0


async def test_a_project_without_a_page_is_refused_in_words(tmp_path):
    install = fake_install(tmp_path / "c", "ok")
    empty = tmp_path / "empty"
    empty.mkdir()
    result = await sb.run_render(install, empty, tmp_path / "x.mp4")
    assert result.reason == "refused" and "no index.html" in result.message


async def test_the_render_environment_is_the_components_own(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
    install = fake_install(tmp_path / "c", "ok")
    node = install.node
    node.write_text('#!/bin/bash\nenv > "$HOME/env.txt"\nshift; shift; shift; echo mp4 > "$1"\n')
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "index.html").write_text("<p>x</p>")
    result = await sb.run_render(install, proj, tmp_path / "x.mp4")
    assert result.ok
    env = (install.root / "home" / "env.txt").read_text()
    assert "GITHUB_TOKEN" not in env and "HYPERFRAMES_NO_TELEMETRY=1" in env
    assert f"HYPERFRAMES_BROWSER_PATH={install.root / 'bin' / 'launch-browser'}" in env
    assert "VB_PROXY_PORT=" in env and f"VB_REAL_BROWSER={install.shell}" in env


def leftovers(tmp_path: Path) -> list[str]:
    """Processes whose command mentions this test's component folder."""
    out = subprocess.run(["ps", "-A", "-o", "command="], capture_output=True, text=True).stdout
    return [line for line in out.splitlines() if str(tmp_path) in line and "pytest" not in line]
