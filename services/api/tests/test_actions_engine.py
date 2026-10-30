"""The action executor on the real desktop engine (ADR-0068): SQLite, the in-process queue and
worker, local files, the shell's token, the stub image engine. Nothing is faked but the GPU.

This is the check that the catalogue is bound to the engine's own child runs, stores, usage and
database, and that the assistant's tools run through it."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from wasifyai_api.main import create_app
from wasifyai_platform_sdk.actions import ApprovalPolicy
from wasifyai_platform_sdk.identity import Identity

from tests.test_desktop_profile import auth, data_dir  # noqa: F401

OPEN = ApprovalPolicy(make="auto", change="auto")


class Engine:
    """The running app, and a way to call the executor on its event loop."""

    def __init__(self, client: TestClient):
        self.client = client
        me = client.get("/me", headers=auth()).json()
        self.me = Identity(me["tenant_id"], me["user_id"])
        self.executor = client.app.state.services.actions  # type: ignore[attr-defined]

    def run(self, action_id: str, params: dict | None = None, origin="window", **kw):
        return self.client.portal.call(  # type: ignore[union-attr]
            lambda: self.executor.run_action(action_id, params or {}, origin, actor=self.me, **kw)
        )

    def sql(self, query: str, **params):
        async def go():
            async with self.client.app.state.services.engine.connect() as conn:  # type: ignore[attr-defined]
                return [dict(r._mapping) for r in await conn.execute(text(query), params)]

        return self.client.portal.call(go)  # type: ignore[union-attr]


@pytest.fixture
def engine(data_dir):  # noqa: F811
    with TestClient(create_app()) as c:
        yield Engine(c)


def test_the_catalogue_is_built_for_what_this_engine_serves(engine):
    reg = engine.executor.registry
    assert len(reg) >= 35 and "image.generate" in reg and "models.list" in reg
    kinds = set(engine.executor.library)
    assert {"image", "track", "speech", "transcript", "voice", "lipsync", "notebook"} <= kinds
    assert engine.executor.audit.__class__.__name__ == "SqlAuditStore"  # the desktop's database


def test_a_picture_is_made_through_the_executor_and_everything_is_recorded(engine):
    r = engine.run("image.generate", {"prompt": "a red teapot on a wooden table"})
    assert r.status == "ok", r.text
    image_id = r.output["image_id"]
    assert r.output["uri"] == f"wasify://creation/image/{image_id}"

    listed = engine.run("library.list", {"kind": "image"})
    assert [i["id"] for i in listed.output["items"]] == [image_id]
    found = engine.run("library.get", {"kind": "image", "id": image_id})
    assert found.output["item"]["title"] == "a red teapot on a wooden table"

    # the product's own usage event, and the executor's
    kinds = [
        u["kind"] for u in engine.sql("select kind, meta from usage_events order by created_at")
    ]
    assert "action.run" in kinds and kinds.count("action.run") >= 3
    audit = engine.sql("select * from action_audit order by created_at")
    assert [(a["action_id"], a["origin"], a["status"]) for a in audit][:1] == [
        ("image.generate", "window", "ok")
    ]
    assert all(
        a["tenant_id"] == engine.me.tenant_id and a["user_id"] == engine.me.user_id for a in audit
    )
    assert "teapot" not in json.dumps(audit, default=str)  # no content in the audit log


def test_the_floor_holds_on_the_real_engine_and_a_yes_in_the_window_is_a_yes_once(engine):
    image_id = engine.run("image.generate", {"prompt": "a fox"}).output["image_id"]
    asked = engine.run(
        "library.delete", {"kind": "image", "id": image_id}, origin="assistant", policy=OPEN
    )
    assert asked.status == "needs_approval" and asked.approval_id
    pending = engine.sql("select * from action_approvals where status = 'pending'")
    assert (
        pending[0]["origin"] == "assistant" and json.loads(pending[0]["params"])["id"] == image_id
    )

    # the person says yes in the window
    assert engine.client.portal.call(  # type: ignore[union-attr]
        lambda: engine.executor.decide_approval(engine.me, asked.approval_id, True)
    )
    gone = engine.run(
        "library.delete", {"kind": "image", "id": image_id}, origin="assistant", policy=OPEN,
        approval_id=asked.approval_id,
    )  # fmt: skip
    assert gone.ok
    row = engine.sql("select status, params from action_approvals")[0]
    assert (row["status"], row["params"]) == ("used", None)  # spent, and the parameters dropped
    assert engine.run("library.list", {"kind": "image"}).output == {"items": []}
    again = engine.run(
        "library.delete", {"kind": "image", "id": image_id}, origin="assistant", policy=OPEN,
        approval_id=asked.approval_id,
    )  # fmt: skip
    assert again.code == "used_approval"


def test_a_long_action_hands_back_a_job_that_can_be_followed(engine):
    started = engine.run("image.generate", {"prompt": "a fox"}, wait_seconds=0)
    assert started.job_id and started.status in ("running", "ok")
    done = engine.run("job.wait", {"job_id": started.job_id, "seconds": 20})
    assert done.ok and done.output["status"] == "ok"
    assert done.output["result"]["output"]["image_id"]
    stop = engine.run("job.cancel", {"job_id": started.job_id})
    assert stop.ok  # already over: it just says how it ended


def test_what_this_computer_can_do_says_what_is_missing(engine):
    r = engine.run("app.status")
    assert r.ok
    states = {a["id"]: a for a in r.output["actions"]}
    assert states["image.generate"]["state"] == "ready"
    assert states["library.search"]["state"] == "ready"
    speak = states["speech.speak"]
    assert speak["state"] == "needs_setup" and speak["step"]  # no speech model on a fresh install
    assert "speech.speak" in r.text
    assert "disk_free_bytes" in r.output["facts"]
    setup = engine.run("speech.speak", {"text": "Hello"})
    assert setup.status == "needs_setup" and setup.setup.ui == "models"  # type: ignore[union-attr]


def test_models_are_listed_and_a_download_waits_for_the_person(engine):
    r = engine.run("models.list", {})
    assert r.ok and r.output["models"], r.text
    first = r.output["models"][0]
    status = engine.run("models.status", {"model_id": first["model_id"]})
    assert status.ok and status.output["model"]["model_id"] == first["model_id"]
    assert status.output["disk_free_bytes"] > 0
    missing = next((m for m in r.output["models"] if m["status"] != "ready"), None)
    if missing is not None:
        ask = engine.run("models.download", {"model_id": missing["model_id"]}, policy=OPEN)
        assert ask.status in ("needs_approval", "refused")  # never started without a person
    unknown = engine.run("models.status", {"model_id": "no-such-model"})
    assert unknown.code == "unknown_model"


def test_the_assistant_origin_only_reaches_what_the_action_offers(engine):
    r = engine.run("image.generate", {"prompt": "a fox"}, origin="assistant", policy=OPEN)
    assert r.ok
    audit = engine.sql("select origin from action_audit where action_id = 'image.generate'")
    assert audit[-1]["origin"] == "assistant"
    nope = engine.run("image.generate", {"prompt": "a fox"}, origin="mcp:Codex")
    assert nope.status == "needs_approval"  # the default asks; nothing runs behind a connection


def test_styles_are_listed_used_in_a_picture_and_deleted_only_with_a_yes(engine, data_dir):  # noqa: F811
    """ADR-0091 S4: the assistant lists the styles, makes a picture with one (the recipe keeps its
    id and checksum), and deleting one always asks."""
    from tests.test_desktop_styles import lora

    folder = data_dir / "models" / "loras"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "ink.safetensors").write_bytes(lora(meta={"trigger": "inkwash"}))
    (folder / "nine.safetensors").write_bytes(lora(4096, 8, 24))

    listed = engine.run("styles.list", origin="assistant")
    assert listed.ok, listed.text
    rows = {r["title"]: r for r in listed.output["styles"]}
    ink, nine = rows["ink"], rows["nine"]
    assert ink["usable"] and ink["word"] == "inkwash" and not nine["usable"]
    assert "inkwash" in listed.text and ink["style_id"] in listed.text

    made = engine.run(
        "image.generate",
        {"prompt": "a fox, inkwash", "styles": [{"id": ink["style_id"], "strength": 0.8}]},
        origin="assistant", policy=OPEN,
    )  # fmt: skip
    assert made.ok, made.text
    recipe = engine.client.get(
        f"/products/wasifyai-image/images/{made.output['image_id']}", headers=auth()
    ).json()["recipe"]
    assert recipe["styles"][0]["id"] == ink["style_id"] and recipe["styles"][0]["sha256"]

    wrong = engine.run(
        "image.generate", {"prompt": "a fox", "styles": [{"id": nine["style_id"]}]},
        origin="assistant", policy=OPEN,
    )  # fmt: skip
    assert not wrong.ok and "another model" in wrong.text

    asked = engine.run(
        "styles.remove", {"style_id": ink["style_id"]}, origin="assistant", policy=OPEN
    )
    assert asked.status == "needs_approval"  # destroy always asks, whatever the setting
    assert (folder / "ink.safetensors").is_file()
