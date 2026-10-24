"""The action catalogue as a whole (ADR-0068 decisions 6 and 7): everything described once, tied to
the menu, the screens and the help files, exported to docs/contracts/actions.json, and the floors
that no setting lowers."""

import json
import re
from pathlib import Path

import pytest
from pydantic import BaseModel
from wasifyai_api.actions_engine import CONTRACT, ROOT, build_registry, default_catalogue
from wasifyai_platform_sdk import GraphRegistry
from wasifyai_platform_sdk.actions import (
    LIBRARY_KINDS,
    Action,
    ActionExecutor,
    ApprovalPolicy,
    CallBinding,
    Outcome,
    decide,
    load_help,
    render,
)
from wasifyai_platform_sdk.actions.testing import FakeActionHost
from wasifyai_platform_sdk.identity import Identity

MENU_TS = ROOT / "packages" / "ui" / "src" / "shell" / "menu.ts"
DESKTOP_MENU_TS = ROOT / "apps" / "desktop" / "src" / "menu.ts"
# Menu items that have a screen and no action of their own, and why (ADR-0068: "an explicit
# exemption"). Anything else with a screen must be the `ui` of an action.
EXEMPT_SCREENS = {
    "chat": "The assistant itself: it is what runs actions, not one of them.",
    "images.library": "A view of the library filtered to pictures: library.list with kind image.",
    "video.library": "A view of the library filtered to videos: library.list with kind video.",
    "music.library": "A view of the library filtered to songs: library.list with kind track.",
}


@pytest.fixture(scope="module")
def catalogue():
    return default_catalogue()


# ---- the menu and the screens -----------------------------------------------------------------


def menu() -> tuple[dict[str, str], dict[str, str]]:
    """(item id -> its label, group id -> its label) from the menu the window and the web share."""
    text = MENU_TS.read_text(encoding="utf-8")
    items: dict[str, str] = {}
    groups: dict[str, str] = {}
    for gid, glabel, body in re.findall(
        r'id: "(\w+)",\s*label: "([^"]+)",\s*icon: \w+,\s*items: \[(.*?)\],\s*\}', text, re.S
    ):
        groups[gid] = glabel
        for iid, ilabel in re.findall(r'id: "([\w.]+)", label: "([^"]+)"', body):
            items[iid] = f"{glabel} › {ilabel}"
    for iid, ilabel in re.findall(r'\{ id: "(chat|library|models|train)", label: "([^"]+)"', text):
        items[iid] = ilabel
    return items, groups


def screens() -> set[str]:
    """The menu items the desktop window opens a screen for."""
    text = DESKTOP_MENU_TS.read_text(encoding="utf-8")
    block = text[text.index("ROUTES: Record<string, Route> = {") :]
    block = block[: block.index("};")]
    found = set(re.findall(r'^\s*"?([\w.]+)"?:\s*"\w+",?$', block, re.M))
    found |= set(re.findall(r'id === "([\w.]+)"', text))  # the items resolved by hand
    return found


def test_the_menu_was_read():
    items, groups = menu()
    assert {"voice.speak", "images.create", "library", "models", "chat"} <= set(items)
    assert groups["voice"] == "Voice" and items["voice.speak"] == "Voice › Text to speech"
    assert {"voice.speak", "notebook.create", "library", "models", "chat"} <= screens()


def test_every_menu_item_with_a_screen_has_an_action_or_an_exemption(catalogue):
    pointed = {a.ui for a in catalogue if a.ui}
    for item in sorted(screens()):
        if item in EXEMPT_SCREENS:
            assert item not in pointed, f"{item} is exempt but an action points at it"
            continue
        assert item in pointed, (
            f"the screen {item} has no action: add one, or exempt it with a reason"
        )


def test_the_exemptions_are_real_and_say_why():
    items, _ = menu()
    for item, why in EXEMPT_SCREENS.items():
        assert item in items and item in screens(), item
        assert len(why) > 20, item


def test_every_ui_pointer_is_a_screen_of_the_menu(catalogue):
    items, _ = menu()
    for a in catalogue:
        if a.ui is not None:
            assert a.ui in items, f"{a.id}: ui {a.ui!r} is not in the menu"
            assert a.ui in screens(), f"{a.id}: ui {a.ui!r} has no screen in the desktop window"


# ---- the help files ---------------------------------------------------------------------------


def test_every_action_has_a_help_file_and_every_help_file_an_action(catalogue):
    ids = {a.id for a in catalogue}
    files = {p.stem for p in (ROOT / "docs" / "help").glob("*.md")}
    assert files == ids, f"help without action: {files - ids}; action without help: {ids - files}"


def test_help_files_agree_with_their_action_and_the_shipped_menu(catalogue):
    items, groups = menu()
    labels = {
        (g, i.split(" › ", 1)[1]) for i in items.values() if " › " in i for g in [i.split(" › ")[0]]
    }
    for a in catalogue:
        h = load_help(ROOT, a.id)
        assert h.action == a.id, a.id
        assert h.screen == a.ui, f"{a.id}: screen {h.screen!r} but ui {a.ui!r}"
        assert h.synonyms, f"{a.id}: write the words people use"
        for heading in (
            "What it is for",
            "Steps in the app",
            "Limits",
            "Needs",
            "Examples",
            "Problems",
        ):
            assert f"## {heading}" in h.body, f"{a.id}: no '{heading}' section"
        for group, item in h.menu_paths:
            assert (group, item) in labels, f"{a.id}: '{group} › {item}' is not in the menu"
        if a.ui and a.ui in items and " › " in items[a.ui]:
            assert f"**{items[a.ui]}**" in h.body, f"{a.id}: name the screen {items[a.ui]!r}"
        assert a.title and a.summary and a.description


# ---- the export -------------------------------------------------------------------------------


def test_the_export_is_current(catalogue):
    assert CONTRACT.read_text(encoding="utf-8") == render(catalogue), (
        "docs/contracts/actions.json is out of date: "
        "uv run python -m wasifyai_api.actions_engine --write"
    )


def test_the_export_says_everything_a_reviewer_needs(catalogue):
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert data["version"] == 1 and len(data["actions"]) == len(catalogue)
    for a in data["actions"]:
        assert {"id", "title", "summary", "description", "input", "output", "effect", "flags",
                "requires", "long", "surfaces", "ui", "help", "examples"} <= set(a)  # fmt: skip
        assert a["input"]["type"] == "object" and a["output"]["type"] == "object"
        assert a["examples"], a["id"]
    assert [a["id"] for a in data["actions"]] == sorted(a["id"] for a in data["actions"])


# ---- the catalogue itself ---------------------------------------------------------------------


def test_the_first_set_is_there(catalogue):
    ids = {a.id for a in catalogue}
    # "about 40" (ADR-0068 decision 7); 45 at motion graphics, 46 with 3D (ADR-0080 decision 9): a
    # creation kind's list, look, rename, delete, save and read are the library's, not new actions
    assert 35 <= len(ids) <= 50
    for expected in (
        "library.search", "library.list", "library.get", "library.export", "library.rename",
        "library.delete", "image.generate", "image.edit", "video.generate", "video.animate",
        "speech.speak", "speech.transcribe", "voice.list", "voice.design", "voice.clone",
        "voice.convert", "voice.edit_speech", "music.generate", "music.lyrics", "music.separate",
        "dub.script", "dub.make", "audiobook.plan", "audiobook.make", "lipsync.make",
        "notebook.list", "notebook.create", "notebook.add_source", "notebook.ask",
        "notebook.studio_output", "models.list", "models.status", "models.download",
        "app.status", "job.status", "job.wait", "job.cancel",
    ):  # fmt: skip
        assert expected in ids, expected


def test_nothing_that_configures_the_app_is_an_action(catalogue):
    for a in catalogue:
        assert a.domain not in {"settings", "account", "config"}, a.id


def test_effects_and_flags_are_what_the_adr_says(catalogue):
    by = {a.id: a for a in catalogue}
    assert {a.id for a in catalogue if a.effect == "destroy"} == {"library.delete"}
    consent = {a.id for a in catalogue if "needs_consent" in a.flags}
    assert consent == {"voice.clone", "lipsync.make", "models.download"}
    for a in catalogue:
        assert (a.effect == "read") or a.effect in ("make", "change", "destroy")
        if a.private:
            assert a.effect in ("read", "make", "change", "destroy")
    for reads in ("library.search", "notebook.search", "app.status", "models.list"):
        assert by[reads].effect == "read"
    assert by["library.rename"].effect == "change" and by["library.export"].effect == "change"
    for long_one in ("image.generate", "video.generate", "music.generate", "audiobook.make"):
        assert by[long_one].long, long_one


def test_what_reads_the_persons_own_things_is_private(catalogue):
    by = {a.id: a for a in catalogue}
    for a in catalogue:
        if a.domain in ("library", "notebook"):
            assert a.private, a.id
    for a in ("speech.transcribe", "voice.clone", "voice.convert", "music.separate", "dub.make"):
        assert by[a].private, a  # they read a recording of the library
    for a in ("image.generate", "music.generate", "models.list", "app.status"):
        assert not by[a].private, a


def test_the_floor_holds_for_every_action_whatever_the_setting(catalogue):
    most_open = ApprovalPolicy(make="auto", change="auto")
    for a in catalogue:
        if a.effect == "destroy" or "needs_consent" in a.flags:
            assert decide(a, most_open) == "ask", a.id
            assert a.consent or a.effect == "destroy", a.id
    for key in ("destroy", "needs_consent"):
        with pytest.raises(ValueError):
            ApprovalPolicy(**{key: "auto"})  # type: ignore[arg-type]


def test_the_default_asks_before_anything_is_made_and_runs_reads(catalogue):
    default = ApprovalPolicy()
    for a in catalogue:
        want = "run" if a.effect == "read" else "ask"
        assert decide(a, default) == want, a.id


def test_nothing_is_offered_to_a_surface_by_accident(catalogue):
    for a in catalogue:
        assert a.surfaces and set(a.surfaces) <= {"assistant", "mcp"}, a.id
    # the assistant's four tools are the only ones wired in A1 (ADR-0057 decision 2 stays)
    from wasifyai_assistant.tools import TOOL_ACTIONS

    for action_id in TOOL_ACTIONS.values():
        assert "assistant" in catalogue.get(action_id).surfaces  # type: ignore[union-attr]


def test_every_kind_of_creation_can_be_reached_through_the_library():
    from wasifyai_api.actions_engine import library_kinds
    from wasifyai_api.graphs import default_registry

    assert set(library_kinds(default_registry())) == set(LIBRARY_KINDS)


def test_every_example_is_a_valid_request_and_runs_to_an_answer_not_a_validation_error(catalogue):
    import asyncio

    host = FakeActionHost()
    ex = ActionExecutor(catalogue, host)
    me = Identity("t1", "u1")

    async def run_all() -> None:
        for a in catalogue:
            for example in a.examples:
                r = await ex.run_action(
                    a.id, example, "window", actor=me,
                    policy=ApprovalPolicy(make="auto", change="auto"), person_approved=True,
                )  # fmt: skip
                assert r.code not in ("invalid_input", "unknown_action", "not_offered"), (
                    a.id,
                    r.text,
                )

    asyncio.run(run_all())


# ---- adding an action is one file -------------------------------------------------------------


def test_a_new_product_adds_its_actions_with_one_registration():
    class In(BaseModel):
        pass

    class Out(BaseModel):
        n: int

    async def run(p, ctx):
        return Outcome.ok({"n": 1}, "one")

    def actions() -> list[Action]:
        return [
            Action(
                id="train.start", title="Train", summary="s", description="d", input=In,
                output=Out, effect="make", bind=CallBinding(run), product="wasifyai-train",
                ui_exempt="Phase 5 adds its screen.", examples=({},),
            )
        ]  # fmt: skip

    reg = GraphRegistry()
    reg.add_actions("wasifyai-train", actions)  # the whole of "adding a product's actions"
    built = build_registry(reg, served=["wasifyai-train"])
    assert "train.start" in built and "library.list" in built  # beside the platform's own
    assert "train.start" not in build_registry(reg, served=[])  # not served: not exposed
    assert "train.start" in [a["id"] for a in json.loads(render(built))["actions"]]


def test_the_docs_describe_how_to_add_one():
    text = (ROOT / "docs" / "actions.md").read_text(encoding="utf-8")
    for needle in ("add_actions", "docs/help", "actions.json", "ui_exempt", "needs_consent"):
        assert needle in text, needle
    assert Path(CONTRACT).is_file()


def test_the_assistants_feature_list_is_current():
    """The screens the chat assistant is told about are made from the catalogue and the menu."""
    from wasifyai_api import assistant_features

    assert assistant_features.main(["--check"]) == 0, (
        "run: python -m wasifyai_api.assistant_features --write"
    )
    wheres = {row["where"] for row in assistant_features.build()}
    assert {"Video › Create", "Voice › Text to speech", "Images › 3D model", "Train"} <= wheres
