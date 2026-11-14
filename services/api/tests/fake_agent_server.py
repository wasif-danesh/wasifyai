"""A stand-in for OpenHands' Agent Server, for unit tests (docs/v2-coding-agent-start-plan.md,
section 8): a small program that answers the endpoints the Wasify engine's supervisor uses
(`wasifyai_api/coding_server.py`), so `make test` needs no model, no network and none of
OpenHands' packages.

It is started the way the real one is: `<python> -I -B -X utf8 -c <the guard> --host H --port N`,
where the test's "python" is a script that runs this file. The guard's own text is then run as it
is, with the one module it starts (`openhands.agent_server`) answered by `serve` below, so the
guard is tested for real. What it answers:

    GET /alive, /health      200, no key asked (as the real one)
    GET /ready               503 until FAKE_READY_AFTER seconds have passed, then 200
    GET /server_info         200 with the version in FAKE_VERSION; 401 without the session key
    GET /fake/env            what it was started with (its environment's names, its arguments,
                             its folder), so a test can read how it was started; 401 without the key

FAKE_EXIT=<code> makes it leave at once with that code (a server that does not start);
FAKE_CHILD=1 makes it start a child in a session of its own, as the real one does for a command.
"""

import http.server
import json
import os
import runpy
import subprocess
import sys
import time

STARTED = time.monotonic()
KEY_ENV = "OH_SESSION_API_KEYS_0"


def serve() -> None:
    args = sys.argv[1:]
    port = int(args[args.index("--port") + 1])
    host = args[args.index("--host") + 1]
    key = os.environ.get(KEY_ENV, "")
    if os.environ.get("FAKE_EXIT"):
        print("fake agent server: told to fail", flush=True)
        raise SystemExit(int(os.environ["FAKE_EXIT"]))
    child = None
    if os.environ.get("FAKE_CHILD"):
        child = subprocess.Popen(["/bin/sleep", "600"], start_new_session=True)
    ready_after = float(os.environ.get("FAKE_READY_AFTER", "0.2"))

    class Handler(http.server.BaseHTTPRequestHandler):
        def _send(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            if self.path in ("/alive", "/health"):
                return self._send(200, {"status": "ok"})
            if self.path == "/ready":
                if time.monotonic() - STARTED < ready_after:
                    return self._send(503, {"status": "initializing"})
                return self._send(200, {"status": "ready"})
            if self.headers.get("X-Session-API-Key") != key or not key:
                return self._send(401, {"detail": "Unauthorized"})
            if self.path == "/server_info":
                return self._send(
                    200, {"title": "fake", "version": os.environ.get("FAKE_VERSION", "1.62.0")}
                )
            if self.path == "/fake/env":
                return self._send(
                    200,
                    {
                        "env": {k: v for k, v in os.environ.items() if k != KEY_ENV},
                        "args": args,
                        "cwd": os.getcwd(),
                        "pid": os.getpid(),
                        "pgid": os.getpgid(0),
                        "sid": os.getsid(0),
                        "child": child.pid if child else None,
                        "fds": sorted(int(n) for n in os.listdir("/dev/fd") if n.isdigit()),
                    },
                )
            return self._send(404, {"detail": "Not Found"})

        def log_message(self, format: str, *args: object) -> None:
            pass

    print(f"fake agent server on {host}:{port}", flush=True)
    http.server.HTTPServer((host, port), Handler).serve_forever()


def main() -> None:
    argv = sys.argv[1:]
    at = argv.index("-c")
    guard, rest = argv[at + 1], argv[at + 2 :]
    sys.argv = ["openhands.agent_server", *rest]
    setattr(runpy, "run_module", lambda *a, **k: serve())  # noqa: B010 (the module the guard starts)
    exec(compile(guard, "<guard>", "exec"), {"__name__": "__main__"})


if __name__ == "__main__":
    main()
