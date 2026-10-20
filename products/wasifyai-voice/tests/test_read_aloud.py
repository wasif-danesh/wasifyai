"""Read aloud (ADR-0083, CU3): a reply in, sound out a passage at a time, nothing kept."""

import base64
import io
import logging
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from voice_rig import FakeEngine, app_state
from wasifyai_platform_sdk import Identity, RouteDeps, VoiceEngineError
from wasifyai_voice import read_aloud
from wasifyai_voice.read_aloud import ReadAloudError, passages, plain_words
from wasifyai_voice.routes import build_routes


@pytest.fixture
def api(tmp_path):
    engine = FakeEngine()
    state = app_state(tmp_path, engine)

    async def identity() -> Identity:
        return Identity("t1", "u1")

    app = FastAPI()
    app.include_router(build_routes(RouteDeps(state, identity)), prefix="/products/wasifyai-voice")
    with TestClient(app) as c:
        c.base_url = c.base_url.join("/products/wasifyai-voice/")
        yield c, engine, state, tmp_path


def say(c, text, part=0):
    return c.post("read-aloud", json={"text": text, "part": part})


# ---- plain words -------------------------------------------------------------------------------


def test_markdown_becomes_the_words_a_person_would_say():
    text = (
        "# A title\n\nSome **bold** and _soft_ words, a [link](https://evil.example/x?a=1), `code`"
        " and https://example.com/path.\nSee [1] and [2, 3].\n\n```python\nprint('hidden')\n```\n\n"
        "- one\n- two\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
    )
    words = plain_words(text)
    assert words == (
        "A title.\nSome bold and soft words, a link, code and.\nSee and.\none.\ntwo.\na, b.\n1, 2."
    )
    for left in ("*", "_", "`", "#", "http", "hidden", "print", "|", "["):
        assert left not in words


def test_markup_a_program_would_run_is_not_spoken():
    words = plain_words(
        "Hi<script>alert(1)</script> <b>there</b> <!-- no --> ![a cat](http://x/y.png)"
        " <iframe src=x>"
    )
    assert "script" not in words and "alert" not in words and "iframe" not in words
    assert "no" not in words.split() and "http" not in words
    assert "Hi" in words and "there" in words and "a cat" in words


def test_invisible_and_bidirectional_controls_are_removed_but_joiners_stay():
    # a right-to-left override, a zero-width space, a control character and a byte-order mark
    words = plain_words("pay‮pal​ is\x00 ok﻿")
    assert words == "paypal is ok."
    # the joiner inside a Persian/Bengali word is part of the word
    assert "‌" in plain_words("می‌خواهم")


def test_a_reply_that_is_only_code_has_nothing_to_read():
    with pytest.raises(ReadAloudError) as e:
        passages("```py\nprint(1)\n```")
    assert e.value.code == "nothing_to_read"
    with pytest.raises(ReadAloudError) as e:
        passages("![](http://x/y.png)  \n---\n")
    assert e.value.code == "nothing_to_read"


def test_passages_end_at_sentences_and_stay_within_the_limit():
    reply = " ".join(f"This is sentence number {i}." for i in range(200))
    got = passages(reply)
    assert 1 < len(got.items) <= read_aloud.MAX_PASSAGES
    assert all(len(p) <= read_aloud.PASSAGE_CHARS for p in got.items)
    assert all(p.endswith(".") for p in got.items)
    assert len(got.items[0]) <= read_aloud.FIRST_PASSAGE_CHARS  # sound starts sooner
    assert got.truncated is (len(reply) > read_aloud.MAX_READ_CHARS)


def test_a_very_long_reply_is_cut_and_says_so():
    got = passages("Word. " * 5000)
    assert len(got.items) == read_aloud.MAX_PASSAGES and got.truncated


def test_one_endless_sentence_without_spaces_is_still_cut():
    got = passages("あ" * 5000)
    assert all(len(p) <= read_aloud.PASSAGE_CHARS for p in got.items) and got.items


def test_sentence_ends_of_other_scripts_split_too():
    got = passages("প্রথম বাক্য। দ্বিতীয় বাক্য। " * 60)
    assert len(got.items) > 1 and all(len(p) <= read_aloud.PASSAGE_CHARS for p in got.items)


# ---- the route ---------------------------------------------------------------------------------


def test_a_reply_is_spoken_one_passage_at_a_time_and_nothing_is_kept(api):
    c, engine, state, root = api
    before = sorted(p.name for p in root.rglob("*"))
    reply = "## Heading\n\n" + " ".join(f"Sentence {i} is here." for i in range(120))
    first = say(c, reply, 0)
    assert first.status_code == 200
    j = first.json()
    assert j["part"] == 0 and j["parts"] > 1 and j["truncated"] is False
    assert j["model"] == "kokoro-82m" and j["displaced"] is None
    with wave.open(io.BytesIO(base64.b64decode(j["audio"]))) as w:
        assert w.getframerate() == 24000 and w.getnchannels() == 1
    spoken = engine.spoken[0]
    assert spoken[1].startswith("Heading.") and "#" not in spoken[1]  # plain words, not markdown
    assert engine.beside_speak == [True]  # asks to stay beside the chat model
    last = say(c, reply, j["parts"] - 1)
    assert last.status_code == 200 and last.json()["part"] == j["parts"] - 1
    assert sorted(p.name for p in root.rglob("*")) == before  # no file, no database row
    assert c.get("speeches").json()["items"] == []  # not a creation
    assert c.get("transcripts").json()["items"] == []


def test_a_passage_past_the_end_is_not_found(api):
    c, *_ = api
    r = say(c, "One short sentence.", 3)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "no_such_part"


def test_oversized_and_malformed_requests_are_refused_before_the_model(api):
    c, engine, *_ = api
    assert say(c, "x" * (read_aloud.MAX_RAW_CHARS + 1)).status_code == 422
    assert c.post("read-aloud", json={"text": ""}).status_code == 422
    assert c.post("read-aloud", json={"text": "hi", "part": -1}).status_code == 422
    assert c.post("read-aloud", json={"text": "hi", "part": 99}).status_code == 422
    assert c.post("read-aloud", json={"text": "hi", "extra": 1}).status_code == 422
    assert c.post("read-aloud", content=b"not json").status_code == 422
    assert engine.spoken == []


def test_only_code_is_a_sentence_not_a_crash(api):
    c, engine, *_ = api
    r = say(c, "```\nrm -rf /\n```")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "nothing_to_read"
    assert "rm -rf" not in str(engine.spoken)


def test_hostile_text_never_reaches_the_model_as_markup(api):
    c, engine, *_ = api
    assert (
        say(c, "Hello <script>alert(1)</script> [x](javascript:alert(1)) ‮evil").status_code == 200
    )
    sent = engine.spoken[0][1]
    assert "<" not in sent and "javascript" not in sent and "‮" not in sent


def test_the_chat_model_being_unloaded_is_passed_on(api):
    c, engine, *_ = api
    engine.displaced = "chat"
    assert say(c, "Hello there.").json()["displaced"] == "chat"


def test_no_speech_model_yet_is_a_409_that_says_what_to_do(api):
    c, engine, *_ = api
    engine.ready = set()
    r = say(c, "Hello there.")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "model_missing"


def test_the_engine_failing_is_a_502_with_its_sentence(api):
    c, engine, *_ = api
    engine.fail_with = VoiceEngineError("busy", "The speech model is busy. Try again.")
    r = say(c, "Hello there.")
    assert (
        r.status_code == 502
        and r.json()["detail"]["message"] == "The speech model is busy. Try again."
    )


def test_no_engine_is_a_503(tmp_path):
    from types import SimpleNamespace

    async def identity() -> Identity:
        return Identity("t1", "u1")

    app = FastAPI()
    state = SimpleNamespace(desktop_dir=tmp_path, storage=None)
    app.include_router(build_routes(RouteDeps(state, identity)), prefix="/products/wasifyai-voice")
    with TestClient(app) as c:
        assert c.post("/products/wasifyai-voice/read-aloud", json={"text": "hi"}).status_code == 503


def test_the_words_are_not_written_to_the_log(api, caplog):
    c, *_ = api
    with caplog.at_level(logging.DEBUG):
        assert say(c, "My very secret sentence.").status_code == 200
    assert "secret" not in caplog.text
