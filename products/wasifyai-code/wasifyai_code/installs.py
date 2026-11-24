"""Installing a project's packages for a session on the person's own program (ADR-0107, stage H4;
the owner's choice A, docs/spikes/coding-harness-h4-mockup.html).

Claude Code or Codex runs in a sandbox that holds the person's sign-in, so it never reaches a
package index: a hostile package's install script there could publish that sign-in. When the
program tries to install, the window offers to install **what the project lists** instead. Wasify AI
runs that install itself, in its own sandbox for the project (the one the person's terminal runs
in), which cannot read the person's home folder or keychain and reaches only the package indexes
through the install proxy. Then the program is told, and carries on.

    what_installs   the project's own install, from the files it has; None when it has none
    run             run it in a sandbox, and say how it went

Only the project's own files decide what is run, never a command of the program's: a package it
wants that the project does not list yet, it adds to the list first.
"""

import asyncio
import contextlib
import os
import signal
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LIMIT_S = 15 * 60
TAIL = 4000
# the files a project lists its packages in, at its top: the program changing one offers the install
LISTS = ("package.json", "requirements.txt", "pyproject.toml", "setup.py")

Sandbox = Callable[[Path], Awaitable[tuple[Sequence[str], Mapping[str, str] | None]]]


@dataclass(frozen=True)
class Install:
    """What is run, step by step, and how it is said to the person."""

    steps: tuple[tuple[str, ...], ...]
    shown: str  # e.g. "npm install"
    source: str  # e.g. "package.json and package-lock.json"

    def view(self) -> dict[str, str]:
        return {"command": self.shown, "from": self.source}


def _and(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def what_installs(folder: Path) -> Install | None:
    """The project's own install, from the files at its top. Node first, then Python."""
    steps: list[tuple[str, ...]] = []
    shown: list[str] = []
    source: list[str] = []
    if (folder / "package.json").is_file():
        steps.append(("npm", "install", "--no-fund", "--no-audit"))
        shown.append("npm install")
        source.append("package.json")
        source += [n for n in ("package-lock.json",) if (folder / n).is_file()]
    python = None
    if (folder / "requirements.txt").is_file():
        python = ("-r", "requirements.txt")
        source.append("requirements.txt")
    elif (folder / "pyproject.toml").is_file() or (folder / "setup.py").is_file():
        python = ("-e", ".")
        source.append("pyproject.toml" if (folder / "pyproject.toml").is_file() else "setup.py")
    if python is not None:
        if not (folder / ".venv" / "bin" / "python").exists():
            steps.append(("python3", "-m", "venv", ".venv"))
        steps.append((".venv/bin/python", "-m", "pip", "install", "--disable-pip-version-check",
                      *python))  # fmt: skip
        shown.append(f"pip install {' '.join(python)} (into .venv)")
    if not steps:
        return None
    return Install(tuple(steps), " && ".join(shown), _and(source))


async def run(
    sandbox: Sandbox, folder: Path, install: Install, *, limit_s: float = LIMIT_S
) -> dict[str, Any]:
    """Run each step in the project's own sandbox until one fails. Never outside a sandbox."""
    wrapper, env = await sandbox(folder)
    if not wrapper:
        return {"ok": False, "exit_code": None, "output": "", "seconds": 0.0,
                "why": "There is no sandbox here to install in."}  # fmt: skip
    started = time.monotonic()
    output = b""
    code: int | None = 0
    for step in install.steps:
        left = limit_s - (time.monotonic() - started)
        proc = await asyncio.create_subprocess_exec(
            *wrapper, *step, cwd=folder, env=dict(env or {}),
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT, start_new_session=True,
        )  # fmt: skip
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=max(left, 1))
        except TimeoutError:
            with contextlib.suppress(OSError):
                os.killpg(proc.pid, signal.SIGKILL)
            await proc.wait()
            took = f"{int(limit_s // 60)} minutes" if limit_s >= 60 else f"{limit_s:g} seconds"
            return {
                "ok": False,
                "exit_code": None,
                "output": output.decode(errors="replace")[-TAIL:],
                "seconds": round(time.monotonic() - started, 1),
                "why": f"It took longer than {took} and was stopped.",
            }
        output += out
        code = proc.returncode
        if code != 0:
            break
    return {
        "ok": code == 0,
        "exit_code": code,
        "output": output.decode(errors="replace")[-TAIL:],
        "seconds": round(time.monotonic() - started, 1),
        "why": "" if code == 0 else f"It ended with code {code}.",
    }


def carry_on(title: str, install: Install, done: Mapping[str, Any]) -> str:
    """What the program is told once the install has run."""
    if done.get("ok"):
        said = (
            f"I installed the project's packages for you: `{install.shown}` finished without "
            "errors."
        )
    else:
        said = (f"I tried to install the project's packages for you with `{install.shown}`, but it "
                f"did not work. {done.get('why') or ''} Its last lines:\n\n```\n"
                f"{str(done.get('output') or '')[-1500:]}\n```")  # fmt: skip
    return (
        f"{said}\n\n{title} cannot reach a package index from its sandbox, so installs are run by "
        "Wasify AI from what the project lists (package.json, requirements.txt or pyproject.toml). "
        "Do not run an install yourself: it cannot work. If you need a package that is not listed "
        "yet, add it to that file and end your turn saying so; I will be offered to install it. "
        "Otherwise carry on with what you were doing."
    )
