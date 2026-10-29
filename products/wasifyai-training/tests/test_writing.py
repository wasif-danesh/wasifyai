"""Teach it from examples: the sets, the checks, a run with a fake engine, the card."""

from pathlib import Path

from training_rig import BASE, wait
from wasifyai_training import language

W = f"{BASE}/writing"


def rows(n: int) -> list[dict[str, str]]:
    return [{"ask": f"Question {i}?", "answer": f"My answer {i}. - Wasi"} for i in range(n)]


def make_set(rig, n: int = 30, name: str = "My replies") -> dict:
    s = rig.post(f"{W}/sets", json={"name": name})
    assert s.status_code == 201, s.text
    sid = s.json()["id"]
    assert rig.put(f"{W}/sets/{sid}/examples", json={"rows": rows(n)}).status_code == 200
    return rig.get(f"{W}/sets/{sid}").json()


def run_to_end(rig, sid: str) -> dict:
    started = rig.post(f"{W}/sets/{sid}/runs")
    assert started.status_code == 202, started.text
    rid = started.json()["id"]
    return wait(rig, f"/runs/{rid}", lambda r: r["status"] != "working")


def test_the_status_says_it_can_run_and_names_the_model_to_teach(rig):
    s = rig.get(f"{W}/status").json()
    assert s["ready"] is True and s["min_examples"] == 10 and s["good_examples"] == 50
    base = s["choices"]["bases"][0]
    assert base["id"] == "qwen3-0.6b-4bit" and base["can_teach"] and base["recommended"]
    assert s["choices"]["default_method"] == "qlora"
    methods = {m["id"]: m for m in base["methods"]}
    assert methods["qlora"]["can"] and not methods["lora"]["can"] and not methods["full"]["can"]


def test_a_set_keeps_its_examples_and_says_what_is_missing(rig):
    s = rig.post(f"{W}/sets", json={"name": "Replies"}).json()
    assert s["missing"].startswith("Add at least 10 examples")
    sid = s["id"]
    put = rig.put(f"{W}/sets/{sid}/examples", json={"rows": rows(12)}).json()
    assert put["examples"] == 12 and put["missing"] is None  # nothing is asked about whose they are
    assert put["rows"][0] == {"ask": "Question 0?", "answer": "My answer 0. - Wasi"}
    done = rig.patch(f"{W}/sets/{sid}", json={"quality": "better"}).json()
    assert done["missing"] is None and done["quality"] == "better"
    assert done["plan"]["held_back"] == 2 and done["plan"]["steps"] == language.steps_for(
        10, "better"
    )
    assert rig.patch(f"{W}/sets/{sid}", json={"quality": "best"}).status_code == 422
    assert rig.patch(f"{W}/sets/{sid}", json={"base": "gpt"}).status_code == 422


def test_sets_belong_to_their_owner(rig):
    sid = make_set(rig)["id"]
    other = {"x-user": "u2"}
    assert rig.get(f"{W}/sets/{sid}", headers=other).status_code == 404
    assert rig.get(f"{W}/sets", headers=other).json()["sets"] == []
    assert rig.delete(f"{W}/sets/{sid}", headers=other).status_code == 204
    assert rig.get(f"{W}/sets/{sid}").status_code == 200  # still the owner's
    assert rig.delete(f"{W}/sets/{sid}").status_code == 204
    assert rig.get(f"{W}/sets/{sid}").status_code == 404


def test_a_run_refuses_what_is_not_ready_in_words(rig):
    few = make_set(rig, n=5)
    refused = rig.post(f"{W}/sets/{few['id']}/runs")
    assert refused.status_code == 422 and "at least 10" in refused.json()["detail"]["message"]


def test_a_run_leaves_a_model_with_the_answers_before_and_after_and_a_mark(rig):
    sid = make_set(rig, n=30)["id"]
    run = run_to_end(rig, sid)
    assert run["status"] == "done" and run["progress"] == 1 and run["model_id"]
    assert run["settings"]["family"] == "language" and run["settings"]["method"] == "qlora"
    model = rig.get(f"{BASE}/models/{run['model_id']}").json()
    assert model["kind"] == "writing" and model["base"] == "qwen3-0.6b-4bit"
    card = model["card"]
    assert card["dataset"]["examples"] == 30 and card["engine"] == "fake-mlx"
    assert card["loss"]["first_held_back"] == 5.0 and card["loss"]["last_held_back"] == 2.5
    assert (
        card["evaluation"]["passed"] is True and "50 percent closer" in card["evaluation"]["note"]
    )
    assert len(card["answers"]) == 3
    one = card["answers"][0]
    assert one["before"].startswith("original: ") and one["after"].endswith("- Wasi")
    assert "statement" not in card


def test_a_model_that_barely_learnt_is_marked_did_not_pass_but_is_kept(rig):
    engine = rig.app_state.language_training
    sid = make_set(rig, n=30)["id"]

    async def weak(job, base_id, folder, report):
        from wasifyai_training.language import LanguageResult

        adapter = folder / "adapter"
        adapter.mkdir(parents=True, exist_ok=True)
        (adapter / "adapters.safetensors").write_bytes(b"stub")
        return LanguageResult(adapter, 1.0, "fake", 5.0, 4.5, 3.0)

    engine.train = weak
    run = run_to_end(rig, sid)
    model = rig.get(f"{BASE}/models/{run['model_id']}").json()
    assert model["card"]["evaluation"]["passed"] is False
    assert "did not pass" in model["card"]["evaluation"]["note"].lower()


def test_a_failed_run_says_so_and_a_stopped_one_keeps_nothing(rig):
    engine = rig.app_state.language_training
    sid = make_set(rig, n=30)["id"]
    engine.fail_with = "boom"
    run = run_to_end(rig, sid)
    assert run["status"] == "failed" and run["error"] == "The model could not be taught. Try again."
    engine.fail_with = None
    engine.hold.clear()
    started = rig.post(f"{W}/sets/{sid}/runs").json()
    wait(rig, f"/runs/{started['id']}", lambda r: r["step"] >= 1)
    assert rig.post(f"{BASE}/runs/{started['id']}/cancel").json() == {"cancelled": True}
    run = wait(rig, f"/runs/{started['id']}", lambda r: r["status"] != "working")
    assert run["status"] == "cancelled" and run["model_id"] is None


def test_only_one_run_at_a_time_across_pictures_and_writing(rig):
    engine = rig.app_state.language_training
    sid = make_set(rig, n=30)["id"]
    engine.hold.clear()
    first = rig.post(f"{W}/sets/{sid}/runs").json()
    wait(rig, f"/runs/{first['id']}", lambda r: r["step"] >= 1)
    again = rig.post(f"{W}/sets/{sid}/runs")
    assert again.status_code == 409 and again.json()["detail"]["code"] == "busy"
    status = rig.get(f"{BASE}/status").json()
    assert status["busy"] is True and status["active_run"] == first["id"]
    engine.hold.set()
    wait(rig, f"/runs/{first['id']}", lambda r: r["status"] == "done")


def test_the_same_question_goes_to_the_original_and_to_the_taught_model(rig):
    run = run_to_end(rig, make_set(rig, n=30)["id"])
    ask = rig.post(f"{W}/models/{run['model_id']}/ask", json={"question": "How do I stop?"})
    assert ask.status_code == 200
    assert ask.json() == {
        "question": "How do I stop?",
        "original": "original: How do I stop?",
        "mine": "mine: How do I stop? - Wasi",
    }
    assert rig.post(f"{W}/models/{'0' * 32}/ask", json={"question": "x"}).status_code == 404
    assert rig.post(f"{W}/models/{run['model_id']}/ask", json={"question": ""}).status_code == 422


def test_deleting_the_model_removes_its_files_and_the_adapter_is_not_served_after(rig):
    run = run_to_end(rig, make_set(rig, n=30)["id"])
    mid = run["model_id"]
    assert rig.delete(f"{BASE}/models/{mid}").status_code == 204
    assert rig.post(f"{W}/models/{mid}/ask", json={"question": "x"}).status_code == 404


def test_a_question_can_be_asked_as_soon_as_the_model_is_kept_not_after_the_search_index(rig):
    """The usage record and the search index come after the model is kept; they may be slow (a
    model that embeds can be loading) and must not hold the next run or a question back."""
    import asyncio

    async def slow(*args, **kwargs):
        await asyncio.sleep(2)

    rig.app_state.creation_index.index = slow
    run = run_to_end(rig, make_set(rig, n=30)["id"])
    ask = rig.post(f"{W}/models/{run['model_id']}/ask", json={"question": "Now?"})
    assert ask.status_code == 200, ask.text
    assert rig.get(f"{BASE}/status").json()["busy"] is False


# ---- the action: the same `train.start`, with a set of examples ----------------------------


class ActionHarness:
    def __init__(self, rig):
        from types import SimpleNamespace

        from training_rig import user_of
        from wasifyai_platform_sdk import RouteDeps
        from wasifyai_platform_sdk.actions import ActionExecutor, ActionRegistry, builtin_actions
        from wasifyai_platform_sdk.actions.testing import FakeActionHost
        from wasifyai_training.actions import actions, library_kinds

        self.rig = rig
        state = rig.app_state
        state.creation_index = None
        state.storage = SimpleNamespace()
        deps = RouteDeps(state, user_of)
        self.ex = ActionExecutor(
            ActionRegistry([*builtin_actions(), *actions()]),
            FakeActionHost(deps),
            library={k.kind: k for k in library_kinds()},
        )

    async def go(self, params: dict):
        from wasifyai_platform_sdk.identity import Identity

        return await self.ex.run_action("train.start", params, "window", actor=Identity("t1", "u1"))


async def test_the_action_teaches_a_writing_model_from_a_set_and_says_how_it_did(rig):
    sid = make_set(rig, n=30)["id"]
    r = await ActionHarness(rig).go({"set_id": sid})
    assert r.status == "ok", r.text
    assert r.output["examples"] == 30 and r.output["passed"] is True
    assert "50 percent closer" in r.output["verdict"] and r.output["magic_word"] == ""
    assert r.output["uri"] == f"wasify://creation/lora/{r.output['model_id']}"
    assert r.text.startswith('"My replies" was taught from 30 examples.')
    model = rig.get(f"{BASE}/models/{r.output['model_id']}").json()
    assert model["kind"] == "writing"


async def test_the_action_wants_exactly_one_set_and_refuses_one_that_is_not_ready(rig):
    h = ActionHarness(rig)
    both = await h.go({"set_id": "a" * 32, "dataset_id": "b" * 32})
    assert (both.status, both.code) == ("refused", "invalid_input")
    none = await h.go({})
    assert (none.status, none.code) == ("refused", "invalid_input")
    ghost = await h.go({"set_id": "c" * 32})
    assert (ghost.status, ghost.code) == ("refused", "not_found")
    few = make_set(rig, n=5)
    short = await h.go({"set_id": few["id"]})
    assert short.status == "refused" and "at least 10" in short.text


# ---- chat with a taught model -------------------------------------------------------------------


class FakeSetup:
    """The writing setup as far as chat needs it: which bases are on this computer, and whether the
    chat form of each is there."""

    def __init__(self, chat: Path | None, models: tuple[str, ...] = ("qwen3-0.6b-4bit",)):
        from types import SimpleNamespace

        self.chat = chat
        self.models = models
        self._spec = lambda base: SimpleNamespace(id=base, chat=SimpleNamespace(size=639_446_688))

    def spec(self, base_id=None):  # noqa: ANN001
        return self._spec(base_id or "qwen3-0.6b-4bit")

    def has_model(self, spec):  # noqa: ANN001
        return spec.id in self.models

    def chat_copy(self, base_id=None):  # noqa: ANN001
        return self.chat

    def bases_state(self):
        return [{"id": b, "chat": {"have": self.chat is not None}} for b in self.models]


class FakeLang:
    """The chat's language service: what it was told to serve, and what it gives back."""

    def __init__(self, installed: bool = True):
        from types import SimpleNamespace

        self.llama = SimpleNamespace(installed=installed)
        self.selected = None
        self.calls: list = []

    async def select_style(self, base, adapter, name, style, context=8192):  # noqa: ANN001
        from types import SimpleNamespace

        self.calls.append((base, adapter, name, style))
        self.selected = SimpleNamespace(style=style, public=lambda: {"name": name, "style": style})

    async def end_style(self) -> bool:
        was = self.selected is not None
        self.selected = None
        return was


def chat_rig(rig, tmp_path: Path, have: bool = True, installed: bool = True):
    base = tmp_path / "chat.gguf"
    base.write_bytes(b"GGUF")
    rig.app_state.language_setup = FakeSetup(base if have else None)
    rig.app_state.desktop_language = FakeLang(installed)
    return rig.app_state.desktop_language


def test_using_a_taught_model_in_chat_needs_the_chat_form_of_its_base_first(rig, tmp_path):
    lang = chat_rig(rig, tmp_path, have=False)
    run = run_to_end(rig, make_set(rig, n=30)["id"])
    refused = rig.post(f"{W}/models/{run['model_id']}/use")
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert detail["code"] == "chat_copy_missing" and detail["bytes"] == 639_446_688
    assert "downloaded once" in detail["message"] and lang.calls == []
    status = rig.get(f"{W}/status").json()
    assert status["bases"] == [{"id": "qwen3-0.6b-4bit", "chat": {"have": False}}]
    assert status["in_chat"] is None and detail["base"] == "qwen3-0.6b-4bit"


def test_it_is_served_on_its_base_with_its_adapter_and_can_be_given_back(rig, tmp_path):
    lang = chat_rig(rig, tmp_path)
    run = run_to_end(rig, make_set(rig, n=30, name="Replies")["id"])
    mid = run["model_id"]
    used = rig.post(f"{W}/models/{mid}/use")
    assert used.status_code == 200, used.text
    base, adapter, name, style = lang.calls[0]
    assert base == tmp_path / "chat.gguf" and name == "My style: Replies" and style == mid
    assert adapter.name == "adapter.gguf" and adapter.read_bytes()[:4] == b"GGUF"
    assert used.json()["selected"] == {"name": "My style: Replies", "style": mid}
    assert rig.get(f"{W}/status").json()["in_chat"] == mid
    # a second use does not convert again
    stamp = adapter.stat().st_mtime_ns
    assert rig.post(f"{W}/models/{mid}/use").status_code == 200
    assert adapter.stat().st_mtime_ns == stamp
    back = rig.delete(f"{W}/use")
    assert back.status_code == 200 and back.json() == {"ended": True, "selected": None}
    assert rig.get(f"{W}/status").json()["in_chat"] is None
    assert rig.delete(f"{W}/use").json()["ended"] is False


def test_it_says_what_is_missing_before_anything_is_served(rig, tmp_path):
    chat_rig(rig, tmp_path, installed=False)
    run = run_to_end(rig, make_set(rig, n=30)["id"])
    no_engine = rig.post(f"{W}/models/{run['model_id']}/use")
    assert no_engine.status_code == 409 and no_engine.json()["detail"]["code"] == "no_engine"
    assert "Settings" in no_engine.json()["detail"]["message"]
    ghost = rig.post(f"{W}/models/{'0' * 32}/use")
    assert ghost.status_code == 404
    pictures = rig.post(f"{W}/models/{run['model_id']}/use", headers={"x-user": "u2"})
    assert pictures.status_code == 404  # not this person's model


def test_a_model_that_is_gone_is_not_the_one_chat_answers_with(rig, tmp_path):
    lang = chat_rig(rig, tmp_path)
    run = run_to_end(rig, make_set(rig, n=30)["id"])
    assert rig.post(f"{W}/models/{run['model_id']}/use").status_code == 200
    assert lang.selected is not None
    assert rig.delete(f"{BASE}/models/{run['model_id']}").status_code == 204
    assert lang.selected is None


def test_the_choice_lists_every_base_and_says_which_are_on_this_computer(rig, tmp_path):
    chat_rig(rig, tmp_path)  # only the first model is on this computer
    rig.app_state.language_training.missing = frozenset({"qwen3-1.7b-4bit", "qwen3-4b-4bit"})
    rows = {b["id"]: b for b in rig.get(f"{W}/status").json()["choices"]["bases"]}
    assert list(rows) == ["qwen3-0.6b-4bit", "qwen3-1.7b-4bit", "qwen3-4b-4bit"]
    assert rows["qwen3-0.6b-4bit"]["installed"] is True and rows["qwen3-0.6b-4bit"]["recommended"]
    for other in ("qwen3-1.7b-4bit", "qwen3-4b-4bit"):
        assert rows[other]["installed"] is False and rows[other]["can_teach"] is True
        assert not rows[other]["recommended"]
        methods = {m["id"]: m["can"] for m in rows[other]["methods"]}
        assert methods == {"lora": False, "qlora": True, "full": False}


def test_a_set_can_choose_a_larger_base_and_a_run_on_one_that_is_not_there_says_what_to_do(
    rig, tmp_path
):
    chat_rig(rig, tmp_path)
    sid = make_set(rig, n=30)["id"]
    chosen = rig.patch(f"{W}/sets/{sid}", json={"base": "qwen3-4b-4bit"}).json()
    assert chosen["base"] == "qwen3-4b-4bit" and chosen["plan"]["base_title"] == "Qwen3 4B"
    rig.app_state.language_training.missing = frozenset({"qwen3-4b-4bit"})
    refused = rig.post(f"{W}/sets/{sid}/runs")
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "not_ready"
    assert "Qwen3 4B is not on this computer yet" in refused.json()["detail"]["message"]
    rig.app_state.language_training.missing = frozenset()
    run = run_to_end(rig, sid)
    assert run["status"] == "done" and run["base"] == "qwen3-4b-4bit"
    model = rig.get(f"{BASE}/models/{run['model_id']}").json()
    assert model["base"] == "qwen3-4b-4bit" and model["card"]["base_title"] == "Qwen3 4B"


def test_chat_with_a_taught_model_asks_for_the_chat_copy_of_its_own_base(rig, tmp_path):
    chat_rig(rig, tmp_path, have=False)
    sid = make_set(rig, n=30)["id"]
    rig.patch(f"{W}/sets/{sid}", json={"base": "qwen3-1.7b-4bit"})
    run = run_to_end(rig, sid)
    refused = rig.post(f"{W}/models/{run['model_id']}/use")
    assert refused.status_code == 409
    assert refused.json()["detail"]["base"] == "qwen3-1.7b-4bit"
