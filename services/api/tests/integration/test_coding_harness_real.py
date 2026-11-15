# ruff: noqa: E501  (test data is easier to read on one line)
"""Stage H1's gate (ADR-0107): a session on each harness, the person's own agent program on their
own plan, answers, changes a file, is checked and is undone. Opt-in twice over, because it uses
the person's plans and needs them signed in:

    CODING_E2E=1 CODING_HARNESS_E2E=1 uv run pytest services/api/tests/integration/test_coding_harness_real.py

Everything is real: the programs (installed by the part's own installer into a throwaway data
folder, from npm's cache when it has them), the harness's server in its sandbox, the person's own
sign-in (read by the program and by nothing of ours), the product's runtime with its check and its
undo. The model is whatever the person's plan gives. What it costs is the plan's.
"""

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from wasifyai_api.coding_harness import HarnessAccounts, harness_hosts
from wasifyai_api.coding_proxy import InstallProxy
from wasifyai_api.coding_server import SANDBOX_EXEC, CodingServer, find_install
from wasifyai_api.components.harness import HarnessComponent
from wasifyai_api.components.manifest import load_manifest

REPO = Path(__file__).resolve().parents[4]
FILES = REPO / "services" / "coding-engine"
APP_DATA = Path(
    os.environ.get("CODING_E2E_DATA")
    or Path.home() / "Library/Application Support/ai.wasifyai.desktop"
)
# the cheaper model each plan offers, so the gate takes little of the plan
MODELS = {"claude-code": os.environ.get("H1_CLAUDE_MODEL", "haiku"),
          "codex": os.environ.get("H1_CODEX_MODEL", "gpt-5.6-terra")}  # fmt: skip

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("CODING_E2E") != "1" or os.environ.get("CODING_HARNESS_E2E") != "1",
        reason="opt-in: CODING_E2E=1 CODING_HARNESS_E2E=1 (uses the person's own plans)",
    ),
    pytest.mark.skipif(
        sys.platform != "darwin" or not Path(SANDBOX_EXEC).is_file(),
        reason="the coding engine's sandbox is the Mac's",
    ),
    pytest.mark.asyncio(loop_scope="module"),
]


@pytest.fixture(scope="module")
async def world(tmp_path_factory):
    if find_install(APP_DATA) is None or not (APP_DATA / "engine" / "node").is_dir():
        pytest.fail(f"The coding engine and Node are not set up in {APP_DATA}.")
    data = tmp_path_factory.mktemp("harness-data")
    (data / "engine").mkdir()
    (data / "engine" / "coding").symlink_to(APP_DATA / "engine" / "coding")
    (data / "engine" / "node").symlink_to(APP_DATA / "engine" / "node")
    part = HarnessComponent(data, load_manifest(), FILES, True)
    part.install(None)
    await part.wait()
    assert part.status()["state"] == "installed", part.status()
    server = CodingServer(data, FILES, proxy=InstallProxy(harness_hosts=harness_hosts()))
    accounts = HarnessAccounts(data)
    from wasifyai_code.runtime import Sessions
    from wasifyai_code.store import CodeStore, Owner

    store = CodeStore.in_folder(data / "code")
    state = SimpleNamespace(
        code_store=store, code_sessions=None, coding_server=server, coding_gateway=SimpleNamespace(),
        coding_harnesses=accounts, creation_index=None, desktop_dir=data,
    )  # fmt: skip
    live = Sessions(state)
    state.code_sessions = live
    try:
        yield SimpleNamespace(
            data=data, server=server, accounts=accounts, live=live, me=Owner("t1", "u1")
        )
    finally:
        await live.stop_all()
        await live.close()
        await accounts.close()
        await server.close()
        store.close()


def shop(tmp_path_factory, name: str) -> Path:
    folder = tmp_path_factory.mktemp(name)
    (folder / "prices.py").write_text(
        'def total(prices):\n    """The sum of the prices; 0 for none."""\n    return sum(prices) if prices else None\n'
    )
    (folder / "check.py").write_text(
        "import prices\nassert prices.total([]) == 0, 'total of nothing must be 0'\n"
        "assert prices.total([2, 3]) == 5\nprint('checked')\n"
    )
    return folder


@pytest.mark.parametrize("harness", ["claude-code", "codex"])
async def test_a_session_on_the_persons_own_program_changes_a_file_is_checked_and_undone(
    world, harness, tmp_path_factory
):
    signed = await world.accounts.status(harness)
    if not signed["signed_in"]:
        pytest.skip(f"{signed['title']} is not signed in on this computer")
    assert set(signed) >= {"signed_in", "how", "plan"} and "email" not in signed
    folder = shop(tmp_path_factory, f"shop-{harness}")
    was = (folder / "prices.py").read_text()
    live, me = world.live, world.me
    made = await live.start(
        me, folder=str(folder), mode="own", model=f"{harness}:{MODELS[harness]}"
    )
    assert made["harness"] == harness and made["counted_in"] == "plan"
    live.set_check(me, made["id"], "python3 -B check.py")
    await live.send(
        me, made["id"],
        "total([]) must return 0, as its docstring says. Fix prices.py with the smallest change. "
        "Do not change check.py.",
    )  # fmt: skip
    closed = await asyncio.wait_for(live.wait(me, made["id"]), 600)
    view = live.view(me, made["id"])
    print(f"\n{harness}: {closed['why']}, rounds {closed['rounds']}, changed {closed['changed']}, "
          f"result {view['result']}, cost as reported ${view['cost_usd']}, "
          f"tokens {view['tokens_in']} in / {view['tokens_out']} out")  # fmt: skip
    assert view["result"] == "passed", (closed, view)
    assert closed["changed"] >= 1
    assert "if prices else None" not in (folder / "prices.py").read_text()
    assert view["tokens_in"] + view["tokens_out"] > 0  # what the program reported was kept
    undone = await live.undo(me, made["id"], closed["id"])
    assert (folder / "prices.py").read_text() == was, undone
