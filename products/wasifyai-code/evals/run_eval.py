"""Run the coding evaluation: 36 small tasks with hidden checks (ADR-0101; C0 spike 3).

    uv run python products/wasifyai-code/evals/run_eval.py --start

`--start` runs no model. It applies each hidden check to the task's untouched starting files, to
prove that every check can fail. It is the only thing this script can do by itself today: a real
run needs a real place (the Agent Server in the sandbox), which does not exist yet. The functions
below are written against the place interface (`wasifyai_code.place`), so the stage that has a
real place runs the same code: `run_all(place, load_tasks(), folder)`.

A task (`tasks.json`, schema 1) has files to start from, a request in plain words and a hidden
check the agent never sees: Python run in a **copy** of the finished workspace; exit 0 is a pass.
For a question the check reads the agent's final answer from the file named by its first argument.
A read-only task also fails if any file changed.

The hidden check is run the way the product runs any check (`wasifyai_code.checks`): in its own
process group, with a time limit, and behind an optional wrapper, which is where the sandbox goes.
"""

import argparse
import asyncio
import json
import shlex
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from wasifyai_code import place as places
from wasifyai_code.checks import Check
from wasifyai_code.place import Place, SessionSpec

TASKS = Path(__file__).with_name("tasks.json")
CHECK_FILE, ANSWER_FILE = "_hidden_check.py", "_answer.txt"
CHECK_LIMIT_S = 90.0
TASK_LIMIT_S = 420.0
STEP_LIMIT = 40
LEFT_OUT = ("__pycache__", ".git", ".pytest_cache")  # what running Python leaves, and git


def load_tasks(path: Path = TASKS, only: Sequence[str] = ()) -> list[dict[str, Any]]:
    data = json.loads(path.read_text())
    if data.get("schema") != 1:
        raise ValueError(f"{path.name}: a schema this runner does not know")
    tasks = [t for t in data["tasks"] if not only or t["id"] in only]
    missing = set(only) - {t["id"] for t in tasks}
    if missing:
        raise ValueError(f"no such task: {', '.join(sorted(missing))}")
    return tasks


def write_start(task: dict[str, Any], workspace: Path) -> None:
    """The task's starting files, in a new folder."""
    workspace.mkdir(parents=True)
    for name, content in task["files"].items():
        target = workspace / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)


def changed_files(task: dict[str, Any], workspace: Path) -> list[str]:
    """The files that are not as the task started: changed, added or gone."""
    now = {
        str(p.relative_to(workspace)): p
        for p in workspace.rglob("*")
        if p.is_file() and not any(part in LEFT_OUT for part in p.parts) and p.suffix != ".pyc"
    }
    start: dict[str, str] = task["files"]
    changed = [
        name
        for name in start
        if name not in now or now[name].read_text(errors="replace") != start[name]
    ]
    return sorted([*changed, *(name for name in now if name not in start)])


async def hidden_check(
    task: dict[str, Any],
    workspace: Path,
    answer: str,
    work: Path,
    *,
    python: str = sys.executable,
    wrapper: Sequence[str] = (),
    limit_s: float = CHECK_LIMIT_S,
) -> tuple[bool, str]:
    """Apply the task's hidden check to a copy of the workspace. Gives whether it passed and, when
    it did not, the end of what the check printed."""
    copy = work / "copy"
    shutil.copytree(workspace, copy, ignore=shutil.ignore_patterns(*LEFT_OUT))
    (copy / CHECK_FILE).write_text(task["hidden"])
    (copy / ANSWER_FILE).write_text(answer)
    command = f"{shlex.quote(python)} -B {CHECK_FILE} {ANSWER_FILE}"
    check = Check(command, copy, output=work / "check.txt", time_limit_s=limit_s, wrapper=wrapper)
    result = await check.run()
    if result.passed:
        return True, ""
    return False, result.tail.strip()[
        -500:
    ] or f"the check {result.result.replace('_', ' ')} ({result.why})"


async def check_start(
    tasks: Sequence[dict[str, Any]], folder: Path, **check: Any
) -> list[dict[str, Any]]:
    """Every hidden check on the untouched starting files. Each must fail, or the task proves
    nothing."""
    results = []
    for task in tasks:
        workspace = folder / task["id"] / "workspace"
        write_start(task, workspace)
        passed, why = await hidden_check(task, workspace, "", folder / task["id"], **check)
        results.append({"id": task["id"], "kind": task["kind"], "passed": passed, "why": why})
    return results


async def run_task(
    place: Place,
    task: dict[str, Any],
    folder: Path,
    *,
    model: str = "",
    step_limit: int = STEP_LIMIT,
    limit_s: float = TASK_LIMIT_S,
    **check: Any,
) -> dict[str, Any]:
    """One task in a new session of the place: its files, the request, the agent's turn to its
    end (or to the time limit), then the hidden check."""
    workspace = folder / task["id"] / "workspace"
    write_start(task, workspace)
    started = time.monotonic()
    session = await place.start(
        SessionSpec(workspace, model=model, step_limit=step_limit, unattended=True)
    )
    await place.send(session, task["prompt"], run=True)

    texts: list[str] = []
    steps, tools = 0, set[str]()

    async def follow() -> tuple[str, str]:
        nonlocal steps
        async for event in place.follow(session):
            if event.kind == places.TEXT:
                texts.append(str(event.data.get("text", "")))
            elif event.kind == places.STEP:
                steps += 1
                tools.add(str(event.data.get("tool", "")))
            elif event.kind == places.CONFIRM:  # nobody is there to say yes
                await place.answer(session, event.data["id"], False, "an evaluation run")
            elif event.kind == places.ENDED:
                return str(event.data.get("why", places.ERROR)), str(event.data.get("detail", ""))
        return places.ERROR, "the place stopped sending events"

    try:
        status, detail = await asyncio.wait_for(follow(), limit_s)
    except TimeoutError:
        await place.stop(session)
        status, detail = "timeout", ""
    seconds = round(time.monotonic() - started, 1)

    answer = texts[-1] if texts else ""  # the agent's final message
    passed, why = await hidden_check(task, workspace, answer, folder / task["id"], **check)
    changed = changed_files(task, workspace)
    if task["readonly"] and changed:
        passed, why = False, "files changed in a read-only task: " + ", ".join(changed)
    return {
        "id": task["id"],
        "kind": task["kind"],
        "passed": passed,
        "why": why,
        "status": status,
        "detail": detail,
        "seconds": seconds,
        "steps": steps,
        "tools": sorted(tools),
        "changed": changed,
    }


async def run_all(
    place: Place,
    tasks: Sequence[dict[str, Any]],
    folder: Path,
    *,
    on_result: Callable[[dict[str, Any]], None] | None = None,
    **more: Any,
) -> dict[str, Any]:
    """Every task, one new session each, one after another."""
    results = []
    for task in tasks:
        result = await run_task(place, task, folder, **more)
        results.append(result)
        if on_result is not None:
            on_result(result)
    return summary(results)


def summary(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    kinds: dict[str, list[int]] = {}
    for r in results:
        passed, of = kinds.setdefault(r["kind"], [0, 0])
        kinds[r["kind"]] = [passed + bool(r["passed"]), of + 1]
    return {
        "passed": sum(bool(r["passed"]) for r in results),
        "of": len(results),
        "kinds": {k: {"passed": p, "of": n} for k, (p, n) in sorted(kinds.items())},
        "results": list(results),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument(
        "--start",
        action="store_true",
        help="no model: every hidden check must fail on the starting files",
    )
    parser.add_argument("--out", type=Path, help="write the results here as JSON")
    parser.add_argument("tasks", nargs="*", help="task ids (default: all 36)")
    args = parser.parse_args(argv)
    if not args.start:
        print(
            "A run with a model needs a real place, which is not built yet. Use --start.",
            file=sys.stderr,
        )
        return 2
    tasks = load_tasks(only=args.tasks)
    with tempfile.TemporaryDirectory(prefix="wasify-code-eval-") as tmp:
        results = asyncio.run(check_start(tasks, Path(tmp)))
    for n, r in enumerate(results, 1):
        print(
            f"{n:2}/{len(results)} "
            f"{'PASSED (wrong)' if r['passed'] else 'fails, as it must'}  {r['id']}"
        )
    wrong = [r["id"] for r in results if r["passed"]]
    if args.out:
        args.out.write_text(json.dumps({"mode": "start", "results": results}, indent=1))
    print(
        f"== {len(results) - len(wrong)} of {len(results)} hidden checks fail on the starting files"
    )
    return 1 if wrong else 0


if __name__ == "__main__":
    raise SystemExit(main())
