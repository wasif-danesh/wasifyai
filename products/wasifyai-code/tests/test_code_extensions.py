# ruff: noqa: E501, F811, ASYNC240  (test data on one line; `world` is a fixture of another file; small files read in tests)
"""Extensions (stage X2) on the pretended place: the small reader, what is offered, the switch for
a project, adding a skill from a folder, what a session is started with, and the skills a message
switched on. Real files and a real store; only the agent is pretended."""

import json
from pathlib import Path

import pytest
from test_code_edits import kept, sessions, start, turn_of, world  # noqa: F401
from test_code_sessions import ME
from wasifyai_code import extensions
from wasifyai_code import place as places
from wasifyai_code.place import FakeTurn
from wasifyai_code.runtime import SKILLS_USED, Refused
from wasifyai_code.store import Owner

HOUSE = """---
name: house-style
description: How this shop's pages are worded and laid out.
triggers: [prices, opening hours]
---

Write short sentences. Prices always with the pound sign.
"""


def a_skill(folder: Path, text: str = HOUSE) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(text)
    return folder


def catalogue(tmp: Path) -> Path:
    """Stands for the pinned catalogue: the entries our short list names, as skills."""
    root = tmp / "catalogue"
    for entry in extensions.short_list():
        if entry["source"] == extensions.CATALOGUE:
            a_skill(
                root / "skills" / entry["name"],
                f"---\nname: {entry['name']}\ndescription: The public {entry['name']} skill.\ntriggers:\n- {entry['name']}\n---\n\nPublic text of {entry['name']}.\n",
            )
    return root


async def answers(turn: FakeTurn) -> None:
    turn.say("Here.")


# ---- the reader ----------------------------------------------------------------------------------


def test_the_first_lines_of_a_skill_are_read_in_the_forms_skills_use():
    front, body = extensions.read_front(
        "---\nname: code-review\ndescription: >\n  Review the changes\n  of a turn.\nlicense: MIT\n"
        "triggers:\n  - /codereview\n  - 'check my changes'\n# a note\nmetadata:\n  author: x\n---\n\n# Code review\n\nRead it.\n"
    )
    assert front["name"] == "code-review" and front["license"] == "MIT"
    assert front["description"] == "Review the changes of a turn."
    assert front["triggers"] == ["/codereview", "check my changes"]
    assert body == "# Code review\n\nRead it.\n"
    assert extensions.read_front("no first lines")[0] == {}
    assert extensions.read_front("---\nname: x\nnever closed")[0] == {}
    assert (
        extensions.read_front('---\ntriggers: review, "what could go wrong"\n---\nx')[0]["triggers"]
        == 'review, "what could go wrong"'
    )


def test_a_skill_is_read_from_its_folder_or_refused_in_words(tmp_path):
    skill = extensions.read_skill(a_skill(tmp_path / "house-style"), id="added:1", source="added")
    assert (skill.name, skill.title) == ("house-style", "House style")
    assert skill.triggers == ("prices", "opening hours")
    assert skill.content == "Write short sentences. Prices always with the pound sign.\n"
    assert skill.text == HOUSE and skill.view(with_text=True)["lines"] == 8
    for text, code in (
        ("---\nname: Bad Name\ndescription: x\n---\ntext", "bad_name"),
        ("---\nname: ok\n---\ntext", "no_description"),
        ("---\nname: ok\ndescription: x\n---\n", "no_text"),
    ):
        with pytest.raises(extensions.ExtensionError) as no:
            extensions.read_skill(a_skill(tmp_path / code, text), id="x", source="added")
        assert no.value.code == code
    with pytest.raises(extensions.ExtensionError) as no:
        extensions.read_skill(tmp_path / "nothing-here", id="x", source="added")
    assert no.value.code == "no_skill"
    # a name is taken from the folder when the file gives none
    named = a_skill(tmp_path / "from-folder", "---\ndescription: x\n---\ntext")
    assert extensions.read_skill(named, id="x", source="added").name == "from-folder"


def test_every_skill_of_ours_and_the_short_list_itself_can_be_read():
    listed = extensions.short_list()
    assert [e["name"] for e in listed if e["source"] == "own"] == [
        "explain-in-plain-words",
        "pictures-with-wasify",
        "write-the-tests-first",
    ]
    ours = extensions.offered(None, [])  # no catalogue: ours alone, and nothing is guessed
    assert [s.id for s in ours] == [
        "own:explain-in-plain-words",
        "own:pictures-with-wasify",
        "own:write-the-tests-first",
    ]
    for skill in ours:
        assert skill.description and skill.triggers and skill.content.startswith("# ")
        assert len(skill.description) <= 1024
    assert [s.default_on for s in ours] == [True, True, False]
    assert "wasify-make picture" in ours[1].content


# ---- what is offered, and the switch ----------------------------------------------------------------


def with_catalogue(world, tmp_path) -> None:
    world.state.coding_server = type(
        "S", (), {"install": type("I", (), {"extensions": catalogue(tmp_path)})()}
    )()


async def test_the_short_list_is_offered_and_a_switch_holds_for_one_project(world, tmp_path):
    with_catalogue(world, tmp_path)
    live, _ = sessions(world, answers)
    made = await start(live, world)
    (project,) = live.workspaces(ME)
    assert project["name"] == "bakery-site" and project["folder"] == made["folder"]
    listed = live.list_extensions(ME, project["id"])
    assert [(e["id"], e["on"]) for e in listed] == [
        ("own:explain-in-plain-words", True), ("own:pictures-with-wasify", True), ("own:write-the-tests-first", False),
        ("catalogue:code-review", False), ("catalogue:frontend-design", False), ("catalogue:security", False),
        ("catalogue:technical-writing", False),
    ]  # fmt: skip
    assert [e["on"] for e in live.list_extensions(ME)] == [None] * 7  # no project named
    done = await live.switch_extension(ME, "catalogue:code-review", project["id"], True)
    assert done["on"] is True and done["title"] == "Code review"
    await live.switch_extension(ME, "own:explain-in-plain-words", project["id"], False)
    on = [e["id"] for e in live.list_extensions(ME, project["id"]) if e["on"]]
    assert on == ["own:pictures-with-wasify", "catalogue:code-review"]
    detail = live.extension(ME, "catalogue:code-review")
    assert detail["text"].startswith("---\nname: code-review") and detail["where"] == [
        {**project, "on": True}
    ]
    # another person has their own switches, and cannot reach this project's
    other = Owner("t1", "someone-else")
    assert [e["on"] for e in live.list_extensions(other)][:1] == [None]
    for call in (
        lambda: live.list_extensions(other, project["id"]),
        lambda: live.extension(ME, "catalogue:not-on-the-list"),
        lambda: live.extension(ME, "added:nothing"),
    ):
        with pytest.raises(Refused) as no:
            call()
        assert no.value.code == "not_found"
    with pytest.raises(Refused):
        await live.switch_extension(other, "own:explain-in-plain-words", project["id"], True)


async def test_a_session_starts_with_the_skills_that_are_on_and_a_change_begins_a_new_conversation(
    world, tmp_path
):
    with_catalogue(world, tmp_path)
    live, place = sessions(world, answers)
    made = await start(live, world)
    (project,) = live.workspaces(ME)
    await turn_of(live, made, "What is here?")
    spec = place.calls[0][2]
    assert [s["name"] for s in spec.skills] == ["explain-in-plain-words", "pictures-with-wasify"]
    first = spec.skills[0]
    assert first["is_agentskills_format"] is True and first["content"].startswith(
        "# Explain in plain words"
    )
    assert first["trigger"] == {
        "type": "keyword",
        "keywords": ["plain words", "explain this", "in simple terms", "what does this do"],
    }
    # the skill's folder is where the sandbox reads it, and holds the file
    shown = Path(first["source"])
    assert shown.name == "SKILL.md" and shown.is_file()
    assert world.data / "coding-fixed" / "skills" in shown.parents
    # a switch lets go of the conversation: the next message starts one with the new skills
    await live.switch_extension(ME, "catalogue:security", project["id"], True)
    await live.switch_extension(ME, "own:pictures-with-wasify", project["id"], False)
    closed = await turn_of(live, made, "And now?")
    starts = [c for c in place.calls if c[0] == "start"]
    assert len(starts) == 2
    assert [s["name"] for s in starts[1][2].skills] == ["explain-in-plain-words", "security"]
    assert "extensions changed" in closed["notes"][0]
    # the folder of a skill that is no longer on is gone from where the sandbox reads
    names = sorted(
        p.name.rsplit("-", 1)[0] for p in (world.data / "coding-fixed" / "skills").iterdir()
    )
    assert names == ["catalogue-security", "own-explain-in-plain-words"]


async def test_the_skills_a_message_switched_on_are_said_on_the_stream(world, tmp_path):
    with_catalogue(world, tmp_path)

    async def agent(turn: FakeTurn) -> None:
        turn._place._emit(
            turn._session, places.SKILLS, {"names": ["explain-in-plain-words", "their-own-one"]}
        )
        turn.say("Here.")

    live, _ = sessions(world, agent)
    made = await start(live, world)
    await turn_of(live, made, "Explain this in plain words")
    (used,) = kept(live, made, SKILLS_USED)
    assert used["names"] == ["explain-in-plain-words", "their-own-one"]
    assert used["titles"] == ["Explain in plain words", "Their own one"]


# ---- adding one from a folder -----------------------------------------------------------------------


async def test_a_skill_is_looked_at_copied_in_switched_on_and_removed(world, tmp_path):
    with_catalogue(world, tmp_path)
    live, place = sessions(world, answers)
    made = await start(live, world)
    (project,) = live.workspaces(ME)
    mine = a_skill(tmp_path / "Documents" / "house-style")
    (mine / "examples.md").write_text("An example.\n")
    (mine / "link").symlink_to(tmp_path)  # never followed, never copied
    seen = live.look_at_folder(str(mine))
    assert (seen["name"], seen["title"], seen["brings"]) == ("house-style", "House style", "text")
    assert (
        seen["text"] == HOUSE
        and seen["bytes"] == len(HOUSE.encode())
        and seen["folder"] == str(mine.resolve())
    )
    assert live.store.list_extensions(ME) == []  # looking adds nothing
    added = await live.add_extension(ME, str(mine), project["id"])
    assert added["source"] == "added" and added["on"] is True and added["id"].startswith("added:")
    copy = Path(live.store.list_extensions(ME)[0]["path"])
    assert world.data / "code" / "extensions" in copy.parents
    assert sorted(p.name for p in copy.iterdir()) == ["SKILL.md", "examples.md"]
    assert (mine / "SKILL.md").read_text() == HOUSE  # the person's folder is not changed
    listed = live.list_extensions(ME, project["id"])
    assert listed[-1]["id"] == added["id"] and listed[-1]["on"] is True
    await turn_of(live, made, "What are the prices?")
    assert "house-style" in [s["name"] for s in place.calls[0][2].skills]
    # it is found by search: the index was told, with what it says it is for
    item = added["id"].split(":")[1]
    assert world.state.creation_index.items[item][3:] == (
        "code_extension",
        "House style. A skill for the coding agent. How this shop's pages are worded and laid out",
    )
    # the same name twice, a plugin, a folder with no skill, and one of the short list's are refused
    for folder, code in (
        (mine, "taken"),
        (tmp_path, "no_skill"),
        (tmp_path / "nowhere", "no_folder"),
    ):
        with pytest.raises(Refused) as no:
            await live.add_extension(ME, str(folder))
        assert no.value.code == code
    plugin = a_skill(tmp_path / "a-plugin")
    (plugin / ".plugin").mkdir()
    (plugin / ".plugin" / "plugin.json").write_text("{}")
    with pytest.raises(Refused) as no:
        live.look_at_folder(str(plugin))
    assert no.value.code == "is_plugin"
    with pytest.raises(Refused) as no:
        await live.remove_extension(ME, "own:explain-in-plain-words")
    assert no.value.code == "not_yours"
    # removing: our copy goes, the switch goes, theirs stays
    assert await live.remove_extension(ME, added["id"]) is True
    assert not copy.exists() and mine.is_dir()
    assert added["id"] not in [e["id"] for e in live.list_extensions(ME, project["id"])]
    assert await live.remove_extension(ME, added["id"]) is False


def test_a_folder_that_is_too_large_is_not_a_skill(tmp_path):
    big = a_skill(tmp_path / "big")
    (big / "data.bin").write_bytes(b"0" * (extensions.MAX_FOLDER_BYTES + 1))
    with pytest.raises(extensions.ExtensionError) as no:
        extensions.look(big)
    assert no.value.code == "too_large"


def test_what_the_engine_is_given_holds_the_text_and_never_a_path_it_cannot_read(tmp_path):
    skill = extensions.read_skill(a_skill(tmp_path / "house-style"), id="added:1", source="added")
    plain = extensions.read_skill(
        a_skill(tmp_path / "plain", "---\nname: plain\ndescription: No words.\n---\nText.\n"),
        id="added:2",
        source="added",
    )
    shown = extensions.show_to_sandbox([skill, plain], tmp_path / "fixed")
    given = extensions.for_engine([skill, plain], shown)
    assert given[0]["content"].startswith("Write short sentences") and "trigger" in given[0]
    assert "trigger" not in given[1]  # no words: the agent reads it when it fits
    assert all(str(tmp_path / "fixed" / "skills") in g["source"] for g in given)
    assert json.dumps(given)  # plain data, as the place sends it
    # shown again with one of them off: its folder is removed, the other is left as it is
    again = extensions.show_to_sandbox([plain], tmp_path / "fixed")
    assert again["added:2"] == shown["added:2"] and not shown["added:1"].exists()
