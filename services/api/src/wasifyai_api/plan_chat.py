"""The chat on the person's own Claude or ChatGPT plan (ADR-0110).

While the chat's model button is set to a plan (the Your plan tab), each round of a chat turn is
answered by the person's own program, Claude Code or Codex, started by its own non-interactive
command (`claude -p`, `codex exec`; decision 2, option A). The programs are the ones Code already
sets up and signs in (ADR-0107: the optional part "harness", `coding_harness.py`). **Wasify AI
never reads, stores, copies or sends a plan's login or token**: the program finds its own sign-in
in the person's home.

**The graph keeps the loop.** The program is given the round's conversation as text and, as its
only tools, the tools the chat offers this round, through a tiny MCP server of ours
(`plan_tools_server.py`) that runs nothing. When the program asks for a tool, the call is read
from its own event stream, the program is stopped, and the call goes back to the assistant graph
as the model's tool call. So every action runs where it always does, with the same cards, the
same floor and the same taint rule (decisions 3 and 4); the next round starts the program again
with the result in the text. Its built-in tools (shell, files, its web search) are switched off
by its own options.

**The program runs in a sandbox** (decision 5; macOS `sandbox-exec`): it may write only its own
folders in the home folder and this round's own folder, and read nothing else of the person's
folders or the app's data. The network is not narrowed here (the coding engine's proxy belongs to
the coding part, which the chat does not need); its tools being off is what keeps it from
fetching anything.

Only the assistant's chat follows the plan. Every other text product (lyrics, notebooks, prompt
help) keeps the model chosen on this computer or the person's key (`KeyedTextProvider`).
"""

import asyncio
import contextlib
import json
import logging
import os
import shutil
import signal
import sys
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk import ChatChunk, RunError
from wasifyai_platform_sdk.capabilities import ToolCall
from wasifyai_platform_sdk.config import CapabilityBinding
from wasifyai_platform_sdk.context import current_context
from wasifyai_platform_sdk.parts import Prompt

from wasifyai_api.coding_harness import (
    HARNESSES,
    Harness,
    find_harness_install,
    real_home,
)

log = logging.getLogger(__name__)

PRODUCT = "wasifyai-assistant"  # the one product whose chat follows the plan
SERVER = "wasify"  # the tool server's name, as the program shows it
CHOICE_FILE = "chat-plan.json"
WORK_DIR = "chat-plan"  # under the app's data: one folder per round, removed after it
ROUND_WAIT_S = 600.0  # a round the program has not finished in ten minutes is stopped
SANDBOX_EXEC = "/usr/bin/sandbox-exec"
TOOLS_SERVER = Path(__file__).with_name("plan_tools_server.py")
# closed to reading whatever else is asked: people's folders, other disks, temp folders
CLOSED = ("/Users", "/Volumes", "/private/var/folders", "/private/tmp")
PATH = "/usr/bin:/bin:/usr/sbin:/sbin"

# The models the chat offers on each plan: what the program's own `--model` takes. "" is the
# program's own choice. Codex's models change with the person's plan, so only its own choice.
MODELS: dict[str, tuple[tuple[str, str], ...]] = {
    "claude-code": (("", "Its own choice"), ("opus", "Opus"), ("sonnet", "Sonnet"),
                    ("haiku", "Haiku")),
    "codex": (("", "Its own choice"),),
}  # fmt: skip

PROFILE = """(version 1)
; The sandbox of the chat's plan program (ADR-0110, decision 5), filled by plan_chat.py.
(allow default)
(deny file-write*)
(allow file-write*
{{WRITE}}
  (literal "/dev/null") (literal "/dev/zero") (literal "/dev/tty") (literal "/dev/ptmx")
  (literal "/dev/dtracehelper") (regex #"^/dev/ttys[0-9]+$") (regex #"^/dev/fd/"))
{{NO_WRITE}}
(deny file-read*
{{CLOSED}})
(allow file-read*
{{OPEN}})
(allow file-read-metadata
{{WAY}})
(deny signal)
(allow signal (target same-sandbox))
(deny lsopen)
(deny appleevent-send)
(deny job-creation)
"""

FRAME = (
    "You answer in a chat inside Wasify AI, a desktop app. The conversation so far is below, "
    "oldest first; write only your next reply to the person, in the language they write in. "
    "Your only tools are Wasify AI's: use them as the instructions say, and never claim you did "
    "something a tool did not report.\n\n"
)


# ---- the choice ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanChoice:
    harness: str
    model: str = ""  # "" is the program's own choice

    def as_dict(self) -> dict[str, str]:
        return {"harness": self.harness, "model": self.model}


def valid_choice(harness: str, model: str) -> PlanChoice | None:
    if harness not in HARNESSES or model not in {m for m, _ in MODELS.get(harness, ())}:
        return None
    return PlanChoice(harness, model)


class PlanChoiceStore:
    """Which plan the chat answers on, if any: a small file in the app's data."""

    def __init__(self, data_dir: Path):
        self.path = data_dir / CHOICE_FILE

    def get(self) -> PlanChoice | None:
        try:
            raw = json.loads(self.path.read_text())
            return valid_choice(str(raw["harness"]), str(raw.get("model") or ""))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def set(self, choice: PlanChoice | None) -> None:
        if choice is None:
            with contextlib.suppress(FileNotFoundError):
                self.path.unlink()
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(choice.as_dict()))
        tmp.replace(self.path)


# ---- the conversation as text --------------------------------------------------------------------


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    out: list[str] = []
    for part in content or []:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            out.append(str(part.get("text") or ""))
        elif part.get("type") in ("image_url", "input_image", "image"):
            out.append("[a picture is attached here; it cannot be shown to you]")
    return "\n".join(t for t in out if t)


def transcript(messages: list[dict[str, Any]]) -> tuple[str, str]:
    """The chat's OpenAI-style messages as the program's instructions and one prompt."""
    system: list[str] = []
    lines: list[str] = []
    for m in messages:
        role = m.get("role")
        text = _text_of(m.get("content")).strip()
        if role == "system":
            system.append(text)
        elif role == "user":
            lines.append(f"[The person]\n{text}")
        elif role == "assistant":
            if text:
                lines.append(f"[You]\n{text}")
            for c in m.get("tool_calls") or []:
                fn = c.get("function") or {}
                lines.append(
                    f"[You called the tool {fn.get('name', '')} with]\n{fn.get('arguments', '{}')}"
                )
        elif role == "tool":
            name = m.get("name") or "the tool"
            lines.append(f"[What {name} answered]\n{text}")
    prompt = FRAME + "\n\n".join(lines) + "\n\n[Your reply]"
    return "\n\n".join(s for s in system if s), prompt


def mcp_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """The chat's offered tools (OpenAI function form) as MCP tools."""
    out = []
    for t in tools or []:
        fn = t.get("function") or {}
        name = str(fn.get("name") or "")
        if not name:
            continue
        out.append(
            {
                "name": name,
                "description": str(fn.get("description") or ""),
                "inputSchema": fn.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    return out


# ---- the programs' commands and what they say ----------------------------------------------------


def claude_args(system: str, model: str, mcp_config: Path) -> list[str]:
    return [
        "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
        "--tools", "",  # none of its own tools
        "--strict-mcp-config", "--mcp-config", str(mcp_config),
        "--allowedTools", f"mcp__{SERVER}",
        "--system-prompt", system or "You are a helpful assistant.",
        "--setting-sources", "",  # none of the person's settings, hooks or CLAUDE.md
        "--disable-slash-commands", "--no-session-persistence",
        *(["--model", model] if model else []),
    ]  # fmt: skip


# Codex's own tools and features, switched off for the chat (`codex features list`, 0.160)
CODEX_OFF = (
    "shell_tool", "unified_exec", "apps", "plugins", "image_generation", "multi_agent",
    "browser_use", "browser_use_external", "computer_use", "view_image", "in_app_browser",
    "hooks", "memories", "skill_search", "tool_suggest", "goals", "sleep_tool",
    "workspace_dependencies", "remote_plugin",
)  # fmt: skip


def codex_args(system: str, model: str, python: Path, server: Path, tools: Path, cwd: Path):
    out = [
        "exec", "--json", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config",
        "--ignore-rules", "-s", "read-only", "-C", str(cwd),
    ]  # fmt: skip
    for feature in CODEX_OFF:
        out += ["--disable", feature]
    out += [
        "-c", 'web_search="disabled"',
        "-c", f"mcp_servers.{SERVER}.command={json.dumps(str(python))}",
        "-c", f"mcp_servers.{SERVER}.args={json.dumps(['-I', str(server), str(tools)])}",
        "-c", f"developer_instructions={json.dumps(system)}",
        *(["-m", model] if model else []),
    ]  # fmt: skip
    return out


@dataclass
class Reader:
    """What one program said, read event by event: text, thinking, tool calls, an error."""

    harness: str
    calls: list[ToolCall] = field(default_factory=list)
    error: str = ""
    stop: bool = False  # nothing more is wanted from the program
    done: bool = False  # it finished its answer by itself
    _seen: set[str] = field(default_factory=set)

    def feed(self, e: dict[str, Any]) -> list[ChatChunk]:
        return self._claude(e) if self.harness == "claude-code" else self._codex(e)

    def _call(self, ident: str, name: str, arguments: Any) -> None:
        if ident in self._seen:
            return
        self._seen.add(ident)
        if name.startswith(f"mcp__{SERVER}__"):
            name = name[len(f"mcp__{SERVER}__") :]
        args = arguments if isinstance(arguments, str) else json.dumps(arguments or {})
        self.calls.append(ToolCall(id=ident or f"call_{uuid.uuid4().hex[:12]}", name=name,
                                   arguments=args))  # fmt: skip

    def _claude(self, e: dict[str, Any]) -> list[ChatChunk]:
        kind = e.get("type")
        if kind == "stream_event":
            ev = e.get("event") or {}
            if ev.get("type") == "content_block_delta":
                d = ev.get("delta") or {}
                if d.get("type") == "text_delta" and d.get("text"):
                    return [ChatChunk(text=str(d["text"]))]
                if d.get("type") == "thinking_delta" and d.get("thinking"):
                    return [ChatChunk(reasoning=str(d["thinking"]))]
        elif kind == "assistant":
            for c in (e.get("message") or {}).get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    self._call(str(c.get("id") or ""), str(c.get("name") or ""), c.get("input"))
        elif kind == "user" and self.calls:
            self.stop = True  # our server answered; the graph runs the calls
        elif kind == "result":
            self.done = True
            if e.get("is_error") or e.get("subtype") != "success":
                self.error = str(e.get("result") or "") or "; ".join(
                    map(str, e.get("errors") or [])
                )
        return []

    def _codex(self, e: dict[str, Any]) -> list[ChatChunk]:
        kind = e.get("type")
        item = e.get("item") or {}
        if kind in ("item.started", "item.updated", "item.completed"):
            if item.get("type") == "mcp_tool_call":
                self._call(str(item.get("id") or ""), str(item.get("tool") or ""),
                           item.get("arguments"))  # fmt: skip
                self.stop = True
            elif kind == "item.completed" and item.get("type") == "agent_message":
                return [ChatChunk(text=str(item.get("text") or ""))]
            elif kind == "item.completed" and item.get("type") == "reasoning":
                return [ChatChunk(reasoning=str(item.get("text") or ""))]
        elif kind == "turn.completed":
            self.done = True
        elif kind in ("turn.failed", "error"):
            self.done = True
            said = (e.get("error") or {}).get("message") if kind == "turn.failed" else None
            self.error = str(said or e.get("message") or "")
        return []


def said_of(harness: Harness, error: str) -> str:
    """A program's refusal, in its own words when it gave some (decision 7)."""
    low = error.lower()
    if "not logged in" in low or "/login" in low or "please log in" in low:
        return (
            f"{harness.title} is not signed in. Sign in under Your plan in the chat's model "
            "button, or choose another model."
        )
    if error:
        return f"{harness.title} said: {error.strip()[:400]}"
    return f"{harness.title} stopped without answering. Try again, or choose another model."


# ---- running a round -----------------------------------------------------------------------------


class PlanChat:
    """The plan the chat answers on, and the rounds run on it."""

    def __init__(self, data_dir: Path, *, home: Path | None = None, sandbox: bool | None = None):
        self.data_dir = data_dir
        self.home = home or real_home()
        self.choices = PlanChoiceStore(data_dir)
        self.sandbox = (
            sandbox
            if sandbox is not None
            else sys.platform == "darwin" and Path(SANDBOX_EXEC).exists()
        )

    def in_use(self) -> PlanChoice | None:
        """The plan, when the run is the assistant's chat."""
        ctx = current_context()
        if ctx is None or ctx.product_id != PRODUCT:
            return None
        return self.choices.get()

    def program(self, harness: Harness) -> tuple[Path, Path]:
        """The program and the folder it was installed in, or a refusal in words."""
        found = find_harness_install(self.data_dir)
        program = found.program(harness) if found else None
        if found is None or program is None or not program.is_file():
            raise RunError(
                "plan_not_set_up",
                f"{harness.title} is not set up on this computer. Set it up under Your plan in "
                "the chat's model button, or choose another model.",
            )
        return program, found.root

    def _profile(self, harness: Harness, work: Path, program_root: Path, python: Path) -> str:
        from wasifyai_api.coding_server import fill_profile  # noqa: PLC0415  (Mac only)

        real = lambda p: Path(os.path.realpath(p))  # noqa: E731
        return fill_profile(
            PROFILE,
            write=[real(work), *(real(p) for p in harness.write_paths(self.home))],
            read_only=[
                real(program_root),
                real(python).parents[1],  # the Python our tool server runs on
                *(real(p) for p in harness.read_paths(self.home)),
            ],
            closed=[*(Path(c) for c in CLOSED), real(self.data_dir)],
            write_starting=[real(self.home) / p.name for p in harness.prefixes(self.home)],
        )

    def _env(self, harness: Harness, tmp: Path) -> dict[str, str]:
        """The person's home (where the program keeps its sign-in), a temp folder of the round's
        own and nothing of this engine's environment, so no key of ours can be in it."""
        env = {
            "HOME": str(self.home),
            "USER": os.environ.get("USER", "user"),
            "LOGNAME": os.environ.get("USER", "user"),
            "LANG": "en_US.UTF-8",
            "PATH": PATH,
            "TMPDIR": str(tmp),
        }
        env.update({k: v.replace("{tmp}", str(tmp)) for k, v in harness.env})
        return env

    def command(
        self, choice: PlanChoice, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None,  # noqa: E501
        work: Path,
    ) -> tuple[list[str], str, dict[str, str]]:  # fmt: skip
        """The round's command line, its input and its environment; writes the round's files."""
        harness = HARNESSES[choice.harness]
        program, root = self.program(harness)
        python = Path(os.path.realpath(sys.executable))
        tmp, cwd = work / "tmp", work / "empty"
        for folder in (tmp, cwd):
            folder.mkdir(parents=True, exist_ok=True)
        server = work / "tools_server.py"
        shutil.copyfile(TOOLS_SERVER, server)
        tools_file = work / "tools.json"
        tools_file.write_text(json.dumps(mcp_tools(tools)))
        system, prompt = transcript(messages)
        if harness.id == "claude-code":
            config = work / "mcp.json"
            config.write_text(json.dumps({"mcpServers": {SERVER: {
                "type": "stdio", "command": str(python),
                "args": ["-I", str(server), str(tools_file)],
            }}}))  # fmt: skip
            argv = [str(program), *claude_args(system, choice.model, config)]
        else:
            argv = [
                str(program),
                *codex_args(system, choice.model, python, server, tools_file, cwd),
            ]
        if self.sandbox:
            profile = work / "plan.sb"
            profile.write_text(self._profile(harness, work, root, python))
            argv = [SANDBOX_EXEC, "-f", str(profile), *argv]
        return argv, prompt, self._env(harness, tmp)

    async def run(
        self, choice: PlanChoice, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
    ) -> AsyncIterator[ChatChunk]:
        """One round on the program: its text and thinking as they come, then its tool calls."""
        harness = HARNESSES[choice.harness]
        work = Path(os.path.realpath(self.data_dir)) / WORK_DIR / uuid.uuid4().hex  # noqa: ASYNC240
        work.mkdir(parents=True)
        proc: asyncio.subprocess.Process | None = None
        try:
            argv, prompt, env = self.command(choice, messages, tools, work)
            proc = await asyncio.create_subprocess_exec(
                *argv, env=env, cwd=str(work / "empty"), stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True, limit=16 * 1024 * 1024,
            )  # fmt: skip
            assert proc.stdin is not None and proc.stdout is not None
            proc.stdin.write(prompt.encode())
            await proc.stdin.drain()
            proc.stdin.close()
            reader = Reader(harness.id)
            async with asyncio.timeout(ROUND_WAIT_S):
                async for raw in proc.stdout:
                    try:
                        event = json.loads(raw)
                    except ValueError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    for chunk in reader.feed(event):
                        yield chunk
                    if reader.stop or reader.done:
                        break
            if reader.calls:
                yield ChatChunk(tool_calls=reader.calls)
                return
            if reader.error or not reader.done:
                raise RunError("plan_refused", said_of(harness, reader.error), retryable=True)
        except TimeoutError:
            raise RunError(
                "plan_refused",
                f"{harness.title} took too long to answer. Try again.",
                retryable=True,
            ) from None
        finally:
            if proc is not None:
                _end(proc)
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(proc.wait(), 5)
            await asyncio.to_thread(shutil.rmtree, work, True)


def _end(proc: asyncio.subprocess.Process) -> None:
    """The program and everything it started (our tool server)."""
    if proc.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)


# ---- the text provider ---------------------------------------------------------------------------


class PlanTextProvider:
    """The desktop's text provider with the plan in front: the assistant's chat goes to the
    program while a plan is chosen; everything else to `inner`."""

    def __init__(self, inner: Any, plan: PlanChat):
        self._inner = inner
        self.plan = plan

    def stream(
        self,
        capability: str,
        binding: CapabilityBinding,
        system: str,
        prompt: Prompt,
        schema: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        return self._inner.stream(capability, binding, system, prompt, schema)

    async def chat(
        self,
        capability: str,
        binding: CapabilityBinding,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        thinking: bool = False,
    ) -> AsyncIterator[ChatChunk]:
        choice = self.plan.in_use()
        if choice is None:
            async for chunk in self._inner.chat(capability, binding, messages, tools, thinking):
                yield chunk
            return
        async for chunk in self.plan.run(choice, messages, tools):
            yield chunk

    async def embed(
        self, capability: str, binding: CapabilityBinding, texts: list[str]
    ) -> list[list[float]]:
        return await self._inner.embed(capability, binding, texts)
