"""Run the coding evaluation: 36 small tasks with hidden checks (ADR-0101; C0 spike 3).

    uv run python products/wasifyai-code/evals/run_eval.py --start
    CODING_OLLAMA_URL=http://127.0.0.1:11434 uv run python \
        products/wasifyai-code/evals/run_eval.py --data "<app data with the coding engine>" \
        --model qwen-27b-ollama --out results.json

`--start` runs no model. It applies each hidden check to the task's untouched starting files, to
prove that every check can fail.

`--data` runs the tasks for real, on this computer as the place (`wasifyai_code.client`): the
coding engine that is set up in that data folder, inside its sandbox, with the model reached
through the engine's gateway for coding (which this script serves on a loopback port of its own).
The model is one of `wasifyai_api/coding_models.yaml`. A model on this computer needs no key. A
cloud model costs money and reads its key from the app's own secret store: it runs only with
`--app-keys`, and only when the owner has said so. The functions below are written against the
place interface (`wasifyai_code.place`), so the same code runs on the pretended place in tests.

A task (`tasks.json`, schema 1) has files to start from, a request in plain words and a hidden
check the agent never sees: Python run in a **copy** of the finished workspace; exit 0 is a pass.
For a question the check reads the agent's final answer from the file named by its first argument.
A read-only task also fails if any file changed.

**Undo is measured too (stage C2's gate).** With a folder for checkpoints (`--data` gives one,
under the app's data, where the sandbox lets the coding engine neither read nor write), each task
is kept before and after the agent's turn. After the hidden check the task is undone, and every
file must be exactly what it was (its bytes, its permissions, no file more and none less); then it
is brought back, and every file must be exactly what the agent left. `undo` in a result says so.

A session that changes files waits before each change, and somebody must say yes
(`wasifyai_code/rules.py`). Here nobody is there: a change to a file is let through, as in "Work
on its own", and any other question is refused.

**On the person's own agent program** (ADR-0107, stage H3): `--model claude-code:<model>` or
`codex:<model>` (`<harness>:default` lets the program choose) runs each task on that program, signed
in with the person's own plan, on the harness's own sandboxed server. The parts "Agent programs"
must be set up in `--data`. What a task cost is what the program reported; it counts against the
person's plan, not a key, and needs no `--app-keys`.

The hidden check is run the way the product runs any check (`wasifyai_code.checks`): in its own
process group, with a time limit, and behind an optional wrapper, which is where the sandbox goes.
"""

import argparse
import asyncio
import contextlib
import json
import os
import shlex
import shutil
import stat
import sys
import tempfile
import time
from collections.abc import AsyncIterator, Callable, Sequence
from pathlib import Path
from typing import Any

from wasifyai_code import place as places
from wasifyai_code import rules
from wasifyai_code.checkpoints import CheckpointError, CheckpointStore
from wasifyai_code.checks import Check
from wasifyai_code.place import Account, Place, SessionSpec
from wasifyai_code.runtime import PLAN_LIMIT

TASKS = Path(__file__).with_name("tasks.json")
ENGINE_FILES = Path(__file__).resolve().parents[3] / "services" / "coding-engine"
CHECK_FILE, ANSWER_FILE = "_hidden_check.py", "_answer.txt"
LET_THROUGH = (*rules.WRITE_TOOLS, *rules.RUN_TOOLS)
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


def exact(folder: Path) -> dict[str, tuple[str, int, bytes]]:
    """Everything under a folder, for "exactly as it was": each file with its bytes and its
    permissions, each link with where it points, each folder (an empty one counts)."""
    out: dict[str, tuple[str, int, bytes]] = {}
    for path in sorted(folder.rglob("*")):
        name = str(path.relative_to(folder))
        mode = stat.S_IMODE(path.lstat().st_mode)
        if path.is_symlink():
            out[name] = ("link", 0, os.readlink(path).encode())
        elif path.is_dir():
            out[name] = ("folder", 0, b"")
        else:
            out[name] = ("file", mode, path.read_bytes())
    return out


def measure_undo(
    store: CheckpointStore, workspace: Path, before: str, was: dict[str, Any]
) -> dict[str, Any]:
    """Undo the turn and bring it back, and say whether each was exact."""
    left = exact(workspace)
    try:
        after = store.checkpoint("after the turn")
        changed = len(store.changes(before, after.id))
        undone = store.undo(before)
        back_exact = exact(workspace) == was
        store.undo(undone.before.id)
        again_exact = exact(workspace) == left
    except CheckpointError as e:
        return {"measured": False, "why": str(e)}
    return {
        "measured": True,
        "changed": changed,
        "undone_exactly": back_exact,
        "brought_back_exactly": again_exact,
        "notes": list(undone.notes),
    }


async def run_task(
    place: Place,
    task: dict[str, Any],
    folder: Path,
    *,
    model: str = "",
    step_limit: int = STEP_LIMIT,
    limit_s: float = TASK_LIMIT_S,
    checkpoints: Path | None = None,
    account: Account | None = None,
    spent: Callable[[str], float] | None = None,
    **check: Any,
) -> dict[str, Any]:
    """One task in a new session of the place: its files, the request, the agent's turn to its
    end (or to the time limit), then the hidden check."""
    workspace = folder / task["id"] / "workspace"
    write_start(task, workspace)
    store = before = was = None
    if checkpoints is not None:
        store = CheckpointStore(checkpoints / task["id"], workspace)
        before = (await asyncio.to_thread(store.checkpoint, "before the turn")).id
        was = exact(workspace)
    started = time.monotonic()
    session = await place.start(
        SessionSpec(workspace, model=model, step_limit=step_limit, unattended=True, account=account)
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
            elif event.kind == places.CONFIRM:
                # nobody is there: steps of tools that wait are let through (a change to a file,
                # a command in the sandbox's terminal, and whatever the model asked for in the
                # same breath: the answer is for all of them); a question that names no step
                # is refused
                waits = event.data.get("steps") or []
                yes = any(s.get("tool") in LET_THROUGH for s in waits)
                await place.answer(
                    session, event.data["id"], yes, "" if yes else "an evaluation run"
                )
            elif event.kind == places.ENDED:
                return str(event.data.get("why", places.ERROR)), str(event.data.get("detail", ""))
        return places.ERROR, "the place stopped sending events"

    following = asyncio.ensure_future(follow())
    try:
        status, detail = await asyncio.wait_for(asyncio.shield(following), limit_s)
    except TimeoutError:
        await place.stop(session)
        status, detail = "timeout", ""
        # read on to the turn's own end, so that the place knows the session is at rest
        with contextlib.suppress(Exception):
            await asyncio.wait_for(following, 20)
    finally:
        following.cancel()
        await asyncio.gather(following, return_exceptions=True)
        # what the session cost is read before it is ended: the gateway forgets an ended session
        cost = spent(account.session_id) if spent is not None and account is not None else None
        # the task's session is over: a place that counts sessions in flight must not count it
        end = getattr(place, "end", None)
        if end is not None:
            with contextlib.suppress(Exception):
                await end(session)
    seconds = round(time.monotonic() - started, 1)

    answer = texts[-1] if texts else ""  # the agent's final message
    passed, why = await hidden_check(task, workspace, answer, folder / task["id"], **check)
    changed = changed_files(task, workspace)
    if task["readonly"] and changed:
        passed, why = False, "files changed in a read-only task: " + ", ".join(changed)
    undo: dict[str, Any] = {"measured": False, "why": "no folder for checkpoints was given"}
    if store is not None and before is not None and was is not None:
        undo = await asyncio.to_thread(measure_undo, store, workspace, before, was)
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
        "undo": undo,
        **({} if cost is None else {"cost_usd": round(cost, 4)}),
    }


def plan_ran_out(result: dict[str, Any]) -> bool:
    """A task that never ran because the program's plan reached its limit: not the agent's
    failure, so it is not counted, and the tasks after it are not run either."""
    return result.get("status") == "error" and bool(PLAN_LIMIT.search(result.get("detail", "")))


async def run_all(
    place: Place,
    tasks: Sequence[dict[str, Any]],
    folder: Path,
    *,
    on_result: Callable[[dict[str, Any]], None] | None = None,
    spent: Callable[[str], float] | None = None,
    limit_usd: float = 0.0,
    **more: Any,
) -> dict[str, Any]:
    """Every task, one new session each, one after another. With `limit_usd` and `spent` (what
    a session has cost so far, by its id) the run stops before the task that would begin at or
    over the limit, and no single task may cost more than what is left. A task stopped by the
    plan's limit ends the run (`stopped`), and it and the rest are `not_run`."""
    results = []
    total = 0.0
    stopped = ""
    for task in tasks:
        if limit_usd and spent is not None:
            left = limit_usd - total
            if left <= 0:
                break
            more["account"] = Account(
                "-", "wasifyai-code", "-", f"eval-{task['id']}", limit_usd=left
            )
        if spent is not None and "account" not in more:
            more["account"] = Account("-", "wasifyai-code", "-", f"eval-{task['id']}")
        result = await run_task(place, task, folder, spent=spent, **more)
        if plan_ran_out(result):
            stopped = result["detail"]
            break
        if spent is not None:
            result.setdefault("cost_usd", 0.0)
            total += result["cost_usd"]
            more.pop("account", None)
        results.append(result)
        if on_result is not None:
            on_result(result)
    out = summary(results)
    out["not_run"] = [t["id"] for t in tasks[len(results) :]]
    if stopped:
        out["stopped"] = stopped
    if spent is not None:
        out["cost_usd"] = round(total, 4)
    return out


def harness_of(model: str) -> str:
    """The person's own agent program a model names (`claude-code:haiku`); "" for a model of
    Wasify AI's own agent."""
    from wasifyai_api.coding_harness import HARNESSES
    from wasifyai_code.place import harness_model

    found = harness_model(model, tuple(HARNESSES))
    return found[0] if found else ""


@contextlib.asynccontextmanager
async def real_place(
    data: Path,
    folder: Path | None = None,
    *,
    ollama_url: str = "",
    app_keys: bool = False,
    reported: dict[str, float] | None = None,
) -> AsyncIterator[tuple[Any, Any]]:
    """This computer as the place, and the gateway that counts its model calls: the coding
    engine set up in `data`, in its sandbox. With `folder` the engine is started once and may
    write anywhere under it; without, each task's own folder is opened as the product opens a
    project (the engine starts again for each), which is what the undo measurement needs: a
    project's folder is then closed to the engine's own `git init`.

    The engine's own parts are used as they are (imported here, not by the product): the
    supervisor that starts the sandboxed server, and the gateway, served on a port of its own.
    Without `app_keys` the secret store is empty, so only a model on this computer can run.
    `reported` collects what each session's agent program reported it cost, by the session's
    account (a session on the person's own program)."""
    from wasifyai_api.coding_gateway import CodingGateway, known_in_catalogue, serve_alone
    from wasifyai_api.coding_server import CodingServer
    from wasifyai_code.client import ThisComputer
    from wasifyai_platform_sdk.secrets import InMemorySecretStore
    from wasifyai_platform_sdk.usage import InMemoryUsageRecorder

    secrets: Any = InMemorySecretStore()
    if app_keys:  # the app's own secret store, the way the desktop engine opens it
        from wasifyai_api.config import Settings
        from wasifyai_api.desktop import make_secret_store
        from wasifyai_api.web_search import load_or_create_key
        from wasifyai_platform_sdk import SecretBox

        settings = Settings(deployment_profile="desktop", desktop_secret_store="keychain")
        box = SecretBox(await asyncio.to_thread(load_or_create_key, data / "secrets.key"))
        secrets = make_secret_store(data, settings, box)
    from wasifyai_api.coding_harness import harness_hosts
    from wasifyai_api.coding_proxy import InstallProxy

    # the proxy also lets each harness reach its own provider, and nothing else (ADR-0107)
    server = CodingServer(data, ENGINE_FILES, proxy=InstallProxy(harness_hosts=harness_hosts()))
    address = [""]

    def on_call(call: Any) -> None:
        if reported is not None and getattr(call, "harness", ""):
            who = str(call.session_id)
            reported[who] = reported.get(who, 0.0) + float(call.usd or 0.0)

    gateway = CodingGateway(
        secrets=secrets,
        usage=InMemoryUsageRecorder(),
        base_url=lambda: address[0],
        ollama_url=ollama_url,
        known=known_in_catalogue,  # a vendor's model (`anthropic:<name>`) is priced as in the app
    )
    try:
        async with serve_alone(gateway) as url:
            address[0] = url
            place = ThisComputer(server, gateway, on_call=on_call)
            if folder is not None:
                await place.open_folder(folder, write=True)  # one start for every task's folder
            yield place, gateway
    finally:
        await server.close()
        await gateway.close()


def summary(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    kinds: dict[str, list[int]] = {}
    for r in results:
        passed, of = kinds.setdefault(r["kind"], [0, 0])
        kinds[r["kind"]] = [passed + bool(r["passed"]), of + 1]
    measured = [r["undo"] for r in results if r.get("undo", {}).get("measured")]
    with_changes = [u for u in measured if u["changed"]]
    return {
        "passed": sum(bool(r["passed"]) for r in results),
        "of": len(results),
        "undo": {
            "measured": len(measured),
            "changed_files": len(with_changes),
            "undone_exactly": sum(bool(u["undone_exactly"]) for u in measured),
            "brought_back_exactly": sum(bool(u["brought_back_exactly"]) for u in measured),
        },
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
    parser.add_argument("--data", type=Path, help="an app data folder with the coding engine")
    parser.add_argument(
        "--model",
        default="",
        help="a model of coding_models.yaml, or a vendor's own: anthropic:<name>, openai:<name>",
    )
    parser.add_argument(
        "--app-keys",
        action="store_true",
        help="read a cloud model's key from the app's own secret store (costs money)",
    )
    parser.add_argument("--work", type=Path, help="where the tasks' folders are made")
    parser.add_argument(
        "--limit-usd", type=float, default=0.0, help="the most the whole run may cost"
    )
    parser.add_argument("tasks", nargs="*", help="task ids (default: all 36)")
    args = parser.parse_args(argv)
    tasks = load_tasks(only=args.tasks)
    if args.data and not args.start:
        # under the home folder: the sandbox closes the system's temp folders to the engine
        made = None if args.work else tempfile.mkdtemp(prefix="wasify-code-eval-", dir=Path.home())
        folder = Path(os.path.realpath(args.work or made or "."))
        folder.mkdir(parents=True, exist_ok=True)
        try:
            return asyncio.run(_run_for_real(args, tasks, folder))
        finally:
            if made:
                shutil.rmtree(made, ignore_errors=True)
    if not args.start:
        print("Give --start (no model) or --data (the real coding engine).", file=sys.stderr)
        return 2
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


async def _run_for_real(
    args: argparse.Namespace, tasks: Sequence[dict[str, Any]], folder: Path
) -> int:
    """Every task on the real coding engine, one new session each."""
    started = time.monotonic()

    def show(r: dict[str, Any]) -> None:
        u = r["undo"]
        undo = (
            f"undo {'exact' if u['undone_exactly'] and u['brought_back_exactly'] else 'NOT EXACT'}"
            f" ({u['changed']} changed)"
            if u["measured"]
            else "undo not measured"
        )
        print(
            f"{'pass' if r['passed'] else 'FAIL'}  {r['id']:32} {r['status']:10} "
            f"{r['seconds']:6.1f} s  {r['steps']:2} steps  {undo}  {r['why'][:80]}",
            flush=True,
        )

    # under the app's data: where the sandbox lets the coding engine neither read nor write
    stores = args.data.resolve() / "code" / "eval-checkpoints" / folder.name
    harness = harness_of(args.model)
    reported: dict[str, float] = {}
    try:
        async with real_place(
            args.data,
            ollama_url=os.environ.get("CODING_OLLAMA_URL", ""),
            app_keys=args.app_keys,
            reported=reported,
        ) as (place, gateway):

            def spent(session: str) -> float:
                if harness:  # what the person's own program reported, on their plan
                    return reported.get(session, 0.0)
                try:
                    return float(gateway.spent(session)["usd"])
                except Exception:  # noqa: BLE001  (a session that made no call is not known)
                    return 0.0

            result = await run_all(
                place, tasks, folder, model=args.model, on_result=show, checkpoints=stores,
                spent=spent, limit_usd=args.limit_usd,
            )  # fmt: skip
            result["model"] = args.model if harness else gateway.model(args.model or None).id
            if harness:
                result["counted_in"] = "plan"
    finally:
        shutil.rmtree(stores, ignore_errors=True)
    result["seconds"] = round(time.monotonic() - started, 1)
    if args.out:
        args.out.write_text(json.dumps({"mode": "real", **result}, indent=1))
    u = result["undo"]
    print(f"== {result['passed']} of {result['of']} passed in {result['seconds']} s")
    if result.get("not_run"):
        why = "the plan's limit" if result.get("stopped") else "the cost limit"
        why += " was reached"
        print(f"== not run, {why}: {', '.join(result['not_run'])}")
    if result.get("stopped"):
        print(f"== the program said: {result['stopped']}")
    if harness:
        print(f"== cost as the program reported it (on the plan): ${result.get('cost_usd', 0):.3f}")
    else:
        print(f"== counted cost: ${result.get('cost_usd', 0):.2f}")
    print(
        f"== undo: {u['undone_exactly']} of {u['measured']} undone exactly, "
        f"{u['brought_back_exactly']} brought back exactly; {u['changed_files']} changed files"
    )
    exact_all = u["undone_exactly"] == u["brought_back_exactly"] == u["measured"] == result["of"]
    return 0 if result["passed"] == result["of"] and exact_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
