"""Harnesses: a coding session on the person's own agent program and its plan (ADR-0107; stage H1).

A harness is a program the person signs in to with their own plan (Claude Code, Codex). It runs
through OpenHands' ACP agent, on an Agent Server of its own, in a sandbox of its own kind
(`coding_server.py`, the amendment of 2026-11-15 to ADR-0102):

    its sign-in    the program's own folders in the person's home are opened to it, read and
                   write, and the keychain for reading. Nothing else of the home folder is
    its provider   the network through our proxy, to its provider's hosts only (`hosts`)
    its program    the pinned npm packages of the adapters, which carry the programs, from the
                   optional part `components/harness.py` under `<app data>/engine/harness/`

**Wasify AI never reads, stores, copies or sends a plan's login or token** (ADR-0107, decision
3). Signing in is the program's own command (`claude auth login`, `codex login`), started here
outside the sandbox with the person's real home: the program opens its own page in the person's
browser and keeps what it gets. Asking whether it is signed in is the program's own status
command, of whose answer only three things are kept: signed in or not, how (a plan or a key),
and the plan's name. Never an email, an organisation or a token.

Gemini CLI is not here yet: ADR-0107, question 3, waits for the owner.
"""

import asyncio
import contextlib
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from wasifyai_platform_sdk.installer import read_state

log = logging.getLogger(__name__)

STATUS_WAIT_S = 20.0
SIGN_IN_WAIT_S = 600.0  # how long a sign-in may wait for the person in the browser
URL = re.compile(r"https://[^\s\"'<>]+")


def real_home() -> Path:
    """The person's own home folder, from the system's record of this user: not `$HOME`, which
    a test or a launcher may have changed. Windows keeps no such record: there it is the profile
    folder."""
    if sys.platform == "win32":
        return Path(os.environ.get("USERPROFILE") or Path.home())
    import pwd  # noqa: PLC0415  (Unix only)

    return Path(pwd.getpwuid(os.getuid()).pw_dir)


@dataclass(frozen=True)
class Harness:
    id: str  # also the ACP agent's `acp_server`
    title: str  # the program's own name, said plainly (ADR-0107, decision 10)
    package: str  # the adapter's npm package, in the part's `node_modules`
    program: tuple[str, ...]  # the program the adapter carries, in `node_modules`
    hosts: tuple[str, ...]  # the provider's hosts: these and anything under them
    write: tuple[str, ...]  # the program's own folders and files in the home folder
    write_prefix: tuple[str, ...] = ()  # files it writes beside them (`.claude.json.backup`)
    read: tuple[str, ...] = ()  # what it reads and never writes (the keychain)
    env: tuple[tuple[str, str], ...] = ()  # given to the program; `{tmp}` is its temp folder
    status: tuple[str, ...] = ()  # the program's own "am I signed in" command
    sign_in: tuple[str, ...] = ()  # the program's own sign-in command
    plan_words: str = ""  # what pays, in the screen's words

    def write_paths(self, home: Path) -> list[Path]:
        return [home / p for p in self.write]

    def read_paths(self, home: Path) -> list[Path]:
        return [home / p for p in self.read]

    def prefixes(self, home: Path) -> list[Path]:
        return [home / p for p in self.write_prefix]


HARNESSES: dict[str, Harness] = {
    h.id: h
    for h in (
        Harness(
            id="claude-code",
            title="Claude Code",
            package="@agentclientprotocol/claude-agent-acp",
            program=("@anthropic-ai", "claude-agent-sdk-darwin-arm64", "claude"),
            # measured in spike H0: api.anthropic.com and mcp-proxy.anthropic.com; claude.ai and
            # claude.com for its sign-in being renewed
            hosts=("anthropic.com", "claude.ai", "claude.com"),
            write=(".claude", ".claude.json"),
            write_prefix=(".claude.json.",),
            read=("Library/Keychains",),
            env=(
                ("CLAUDE_CODE_TMPDIR", "{tmp}"),  # it writes /tmp/claude-<uid> otherwise
                # no update of itself, no reports of its own (they went to a logs host in H0)
                ("DISABLE_AUTOUPDATER", "1"),
                ("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1"),
            ),
            status=("auth", "status", "--json"),
            sign_in=("auth", "login", "--claudeai"),
            plan_words="your Claude plan",
        ),
        Harness(
            id="codex",
            title="Codex",
            package="@agentclientprotocol/codex-acp",
            program=(
                "@openai",
                "codex-darwin-arm64",
                "vendor",
                "aarch64-apple-darwin",
                "bin",
                "codex",
            ),
            # measured in spike H0: chatgpt.com only; openai.com for its sign-in being renewed
            hosts=("chatgpt.com", "openai.com"),
            write=(".codex",),
            read=("Library/Keychains",),
            status=("login", "status"),
            sign_in=("login",),
            plan_words="your ChatGPT plan",
        ),
    )
}


def harness_of(model: str | None) -> tuple[Harness, str] | None:
    """A session's model names its harness as `<harness>:<the program's model>` ("" for the
    program's own choice). None for a model of the Wasify AI harness."""
    if not model:
        return None
    name, sep, rest = model.partition(":")
    if not sep or name not in HARNESSES:
        return None
    return HARNESSES[name], "" if rest == "default" else rest


def harness_hosts() -> dict[str, tuple[str, ...]]:
    """Each harness's provider hosts, for the proxy."""
    return {h.id: h.hosts for h in HARNESSES.values()}


# ---- the installed programs ----------------------------------------------------------------------


@dataclass(frozen=True)
class HarnessInstall:
    version: str
    root: Path  # <app data>/engine/harness/<version>: its `node_modules`
    adapters: dict[str, str]  # a harness's id -> its adapter's entry file, inside `root`

    def adapter(self, harness: Harness) -> Path | None:
        found = self.adapters.get(harness.id)
        return self.root / found if found else None

    def program(self, harness: Harness) -> Path:
        return self.root / "node_modules" / Path(*harness.program)


def find_harness_install(data_dir: Path) -> HarnessInstall | None:
    """The installed programs, from the state file their part writes last; None when absent,
    damaged or pointing outside its own folder."""
    base = data_dir / "engine" / "harness"
    state = read_state(base / "state.json")
    if state is None:
        return None
    try:
        root = (base / str(state["dir"])).resolve()
        adapters = {str(k): str(v) for k, v in dict(state["adapters"]).items()}
        if base.resolve() not in root.parents or not (root / "node_modules").is_dir():
            return None
        for entry in adapters.values():
            if root not in (root / entry).resolve().parents:
                return None
        return HarnessInstall(str(state["version"]), root, adapters)
    except (KeyError, OSError, TypeError, ValueError):
        return None


def acp_command(
    harness: Harness, install: HarnessInstall, node: Path, tmp: Path, home: Path | None = None
) -> list[str]:
    """How the ACP agent starts the program: the adapter on our Node, with the person's real home
    (where the program keeps its sign-in) and nothing more. The Agent Server keeps its own home;
    only this program is given the real one, and the sandbox opens only its own folders there."""
    adapter = install.adapter(harness)
    if adapter is None:
        raise ValueError(f"no adapter for {harness.id}")
    env = [f"HOME={home or real_home()}"]
    env += [f"{k}={v.replace('{tmp}', str(tmp))}" for k, v in harness.env]
    return ["/usr/bin/env", *env, str(node), str(adapter)]


# ---- signing in ----------------------------------------------------------------------------------


def _clean_env(home: Path) -> dict[str, str]:
    """For the program's own status and sign-in, outside the sandbox: the person's home, the
    system's tools (`open` shows its page in the browser) and nothing of this engine's own
    environment, so no key of ours can be in it."""
    return {
        "HOME": str(home),
        "USER": os.environ.get("USER", "user"),
        "LOGNAME": os.environ.get("USER", "user"),
        "LANG": "en_US.UTF-8",
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
        "DISABLE_AUTOUPDATER": "1",
    }


def read_status(harness: Harness, code: int, out: str) -> dict[str, Any]:
    """What is kept of the program's own answer: signed in, how, and the plan's name."""
    if harness.id == "claude-code":
        try:
            said = json.loads(out[out.find("{") :]) if "{" in out else {}
        except ValueError:
            said = {}
        signed = bool(said.get("loggedIn"))
        method = str(said.get("authMethod") or "")
        plan = str(said.get("subscriptionType") or "")
        how = "plan" if method in ("claude.ai", "oauth_token") else ("key" if signed else "")
        return {"signed_in": signed, "how": how, "plan": plan[:40] if how == "plan" else ""}
    text = out.lower()
    if "not logged in" in text or code != 0:
        return {"signed_in": False, "how": "", "plan": ""}
    if "api key" in text:
        return {"signed_in": True, "how": "key", "plan": ""}
    if "chatgpt" in text:
        return {"signed_in": True, "how": "plan", "plan": "ChatGPT"}
    return {"signed_in": "logged in" in text, "how": "", "plan": ""}


def page_of(harness: Harness, line: str) -> str | None:
    """A sign-in page the program printed, when it is its provider's: shown to the person when
    the browser did not open by itself. Nothing else of the program's output is kept."""
    for found in URL.findall(line):
        host = (urlparse(found).hostname or "").lower()
        if any(host == h or host.endswith("." + h) for h in harness.hosts):
            return found
    return None


class HarnessAccounts:
    """The programs' own sign-in, from the app (ADR-0107, decision 3)."""

    def __init__(self, data_dir: Path, *, home: Path | None = None):
        self.data_dir = data_dir
        self.home = home or real_home()
        self._signing: dict[str, asyncio.subprocess.Process] = {}
        self._pages: dict[str, str] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def install(self) -> HarnessInstall | None:
        return find_harness_install(self.data_dir)

    def _program(self, harness: Harness) -> Path | None:
        found = self.install()
        if found is None:
            return None
        program = found.program(harness)
        return program if program.is_file() else None

    async def status(self, harness_id: str) -> dict[str, Any]:
        harness = HARNESSES[harness_id]
        out: dict[str, Any] = {
            "id": harness.id, "title": harness.title, "plan_words": harness.plan_words,
            "installed": False, "signed_in": False, "how": "", "plan": "",
            "signing_in": harness.id in self._signing, "page": self._pages.get(harness.id, ""),
        }  # fmt: skip
        program = self._program(harness)
        if program is None:
            return out
        out["installed"] = True
        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                str(program), *harness.status, env=_clean_env(self.home), cwd=str(self.home),
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )  # fmt: skip
            raw, _ = await asyncio.wait_for(proc.communicate(), STATUS_WAIT_S)
        except (OSError, TimeoutError):
            if proc is not None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
            return out
        out.update(read_status(harness, proc.returncode or 0, raw.decode(errors="replace")))
        return out

    async def statuses(self) -> list[dict[str, Any]]:
        return list(await asyncio.gather(*(self.status(h) for h in HARNESSES)))

    async def sign_in(self, harness_id: str) -> dict[str, Any]:
        """Start the program's own sign-in. It opens its page in the person's browser and waits
        there; its answer goes to the program, never here."""
        harness = HARNESSES[harness_id]
        program = self._program(harness)
        if program is None:
            raise LookupError(f"{harness.title} is not set up yet.")
        if harness.id not in self._signing:
            proc = await asyncio.create_subprocess_exec(
                str(program), *harness.sign_in, env=_clean_env(self.home), cwd=str(self.home),
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT, start_new_session=True,
            )  # fmt: skip
            self._signing[harness.id] = proc
            self._pages.pop(harness.id, None)
            task = asyncio.ensure_future(self._watch(harness, proc))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            await asyncio.sleep(1.0)  # its page, when it prints one, comes at once
        return await self.status(harness.id)

    async def _watch(self, harness: Harness, proc: asyncio.subprocess.Process) -> None:
        try:
            async with asyncio.timeout(SIGN_IN_WAIT_S):
                assert proc.stdout is not None
                async for raw in proc.stdout:
                    if harness.id not in self._pages:
                        page = page_of(harness, raw.decode(errors="replace"))
                        if page:
                            self._pages[harness.id] = page
                await proc.wait()
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
        finally:
            if self._signing.get(harness.id) is proc:
                del self._signing[harness.id]
            self._pages.pop(harness.id, None)

    async def cancel(self, harness_id: str) -> None:
        proc = self._signing.pop(harness_id, None)
        self._pages.pop(harness_id, None)
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()

    async def close(self) -> None:
        for harness_id in list(self._signing):
            await self.cancel(harness_id)
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
