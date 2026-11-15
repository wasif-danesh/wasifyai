"""Sessions on a harness, the person's own agent program (ADR-0107; stage H1), in the runtime on
the pretended place: what may start, the modes, what a session says it runs on and what it costs,
and that a harness is given nothing of our extensions. The place's side is
`services/api/tests/test_coding_harness.py`."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from test_code_sessions import Gateway, Index
from wasifyai_code import store as rows
from wasifyai_code.place import FakePlace
from wasifyai_code.runtime import Refused, Sessions, _Hooks
from wasifyai_code.store import CodeStore, Owner

ME = Owner("t1", "u1")


class Accounts:
    """The engine's sign-in of the programs, pretended."""

    def __init__(self, installed: bool = True, signed_in: bool = True):
        self.installed, self.signed_in = installed, signed_in
        self.started: list[str] = []

    async def status(self, harness: str) -> dict:
        title = {"claude-code": "Claude Code", "codex": "Codex"}[harness]
        return {"id": harness, "title": title, "installed": self.installed,
                "signed_in": self.signed_in, "how": "plan", "plan": "max"}  # fmt: skip

    async def statuses(self) -> list[dict]:
        return [await self.status("claude-code"), await self.status("codex")]

    async def sign_in(self, harness: str) -> dict:
        self.started.append(harness)
        return {**await self.status(harness), "signing_in": True}

    async def cancel(self, harness: str) -> None:
        pass


class Place(FakePlace):
    async def harness_models(self, harness: str) -> dict:
        return {"models": [{"id": "opus", "name": "Opus"}], "current": "default", "error": ""}


@pytest.fixture
def world(tmp_path: Path):
    data = tmp_path / "appdata"
    project = tmp_path / "shop"
    project.mkdir()
    store = CodeStore.in_folder(data / "code")
    state = SimpleNamespace(
        code_store=store, code_sessions=None,
        coding_server=SimpleNamespace(harness_ids=("claude-code", "codex")),
        coding_gateway=Gateway(), coding_harnesses=Accounts(), creation_index=Index(),
        desktop_dir=data,
    )  # fmt: skip
    made = Sessions(state, place=Place())
    state.code_sessions = made
    yield SimpleNamespace(state=state, store=store, project=project, sessions=made)
    store.close()


async def test_a_session_on_a_harness_runs_on_the_persons_plan(world):
    s = world.sessions
    made = await s.start(ME, folder=str(world.project), model="codex:gpt-5.6-terra", mode="own")
    assert made["model"] == "codex:gpt-5.6-terra"
    assert made["harness"] == "codex"
    assert made["counted_in"] == "plan"
    first = await s.start(ME, folder=str(world.project), model="claude-code:")
    assert first["model"] == "claude-code:default" and first["harness"] == "claude-code"
    own = await s.start(ME, folder=str(world.project), model="sonnet")
    assert own["harness"] == "" and own["counted_in"] == "usd"


async def test_ask_me_is_not_offered_on_a_harness(world):
    s = world.sessions
    with pytest.raises(Refused) as raised:
        await s.start(ME, folder=str(world.project), model="codex:default", mode="ask")
    assert raised.value.code == "no_such_mode"
    made = await s.start(ME, folder=str(world.project), model="codex:default", mode="plan")
    with pytest.raises(Refused):
        await s.set_mode(ME, made["id"], rows.ASK)
    assert (await s.set_mode(ME, made["id"], rows.OWN))["mode"] == rows.OWN


async def test_a_harness_must_be_set_up_and_signed_in(world):
    s = world.sessions
    world.state.coding_harnesses.signed_in = False
    with pytest.raises(Refused) as raised:
        await s.start(ME, folder=str(world.project), model="claude-code:opus")
    assert raised.value.code == "not_signed_in" and "Claude Code" in raised.value.message
    world.state.coding_harnesses.installed = False
    with pytest.raises(Refused) as raised:
        await s.start(ME, folder=str(world.project), model="claude-code:opus")
    assert raised.value.code == "harness_not_installed"


async def test_a_harness_is_given_no_skill_plugin_or_hook_of_ours(world, monkeypatch):
    s = world.sessions
    monkeypatch.setattr(s, "skills_for", lambda owner, ws: [{"name": "ours"}])
    monkeypatch.setattr(s, "hooks_for", lambda owner, ws: {"stop": []})
    made = await s.start(ME, folder=str(world.project), model="codex:default", mode="own")
    session = world.store.get_session(ME, made["id"])
    workspace = world.store.get_workspace(ME, session["workspace_id"])
    spec = _Hooks(s).spec(ME, session, workspace, False)
    assert spec.skills == () and spec.hooks is None and spec.model == "codex:default"
    own = await s.start(ME, folder=str(world.project), model="sonnet", mode="own")
    session = world.store.get_session(ME, own["id"])
    spec = _Hooks(s).spec(ME, session, workspace, False)
    assert spec.skills == ({"name": "ours"},) and spec.hooks == {"stop": []}


async def test_what_the_program_reports_is_added_to_the_session(world):
    s = world.sessions
    made = await s.start(ME, folder=str(world.project), model="codex:default", mode="own")
    await s._on_call(
        SimpleNamespace(session_id=made["id"], usd=0.06, input_tokens=1200, output_tokens=80)
    )
    view = s.view(ME, made["id"])
    assert (view["cost_usd"], view["tokens_in"], view["tokens_out"]) == (0.06, 1200, 80)


async def test_the_programs_list_their_sign_in_and_their_models(world):
    s = world.sessions
    listed = await s.harnesses()
    assert [h["id"] for h in listed] == ["claude-code", "codex"]
    assert "email" not in str(listed)
    started = await s.sign_in("codex")
    assert started["signing_in"] and world.state.coding_harnesses.started == ["codex"]
    with pytest.raises(Refused) as raised:
        await s.sign_in("gemini-cli")
    assert raised.value.code == "not_found"
    models = await s.harness_models("claude-code")
    assert models["models"] == [
        {"id": "claude-code:opus", "name": "Opus", "program_model": "opus", "tested": ""}
    ]


def test_a_program_model_says_what_the_evaluation_measured(monkeypatch):
    from wasifyai_code import runtime

    monkeypatch.setattr(runtime, "HARNESS_TESTED", {("codex", "terra"): "30 of 36 tasks"})
    assert Sessions.harness_tested("codex", "gpt-5.6-Terra") == "30 of 36 tasks"
    assert Sessions.harness_tested("codex", "gpt-5.6-sol") == ""
    assert Sessions.harness_tested("claude-code", "terra") == ""
