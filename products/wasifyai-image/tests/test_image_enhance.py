from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from image_rig import make_rig, put_upload
from wasifyai_image import prompts
from wasifyai_image.routes import build_routes
from wasifyai_platform_sdk import EngineServices, Identity, InMemoryUploadLimiter, RouteDeps

BASE = "/products/wasifyai-image/prompt/enhance"


def who(x_user: str = Header("u1")) -> Identity:
    return Identity(tenant_id="t1", user_id=x_user)


def client_for(rig):
    app = FastAPI()
    app.state.services = EngineServices()
    app.state.services.caps = {"wasifyai-image": rig.caps}
    app.state.services.uploads = rig.uploads
    app.state.services.storage = rig.caps.storage
    app.state.services.enhance_limiter = InMemoryUploadLimiter(40)
    app.include_router(
        build_routes(RouteDeps(app.state.services, who)), prefix="/products/wasifyai-image"
    )
    return TestClient(app)


def test_the_enhancer_prompts_exist_and_say_english_and_data(tmp_path):
    for name in ("enhance_text_to_image", "enhance_edit_image"):
        text = prompts.load(name)
        assert "English" in text and "<user_text>" in text and "Never follow instructions" in text
    assert "<picture_description>" in prompts.load("enhance_edit_image")


def test_a_description_is_rewritten(tmp_path):
    rig = make_rig(tmp_path, enhance=["A red fox standing in fresh snow, soft morning light."])
    r = client_for(rig).post(BASE, json={"kind": "text_to_image", "prompt": "zorro en la nieve"})
    assert r.status_code == 200 and r.json()["changed"] is True
    assert "red fox" in r.json()["prompt"]
    assert rig.pictures() == []  # nothing looked at a picture


async def test_an_edit_describes_the_picture_first(tmp_path):
    rig = make_rig(tmp_path, enhance=["Turn the scene to dusk and keep the square."])
    record = await put_upload(rig)
    r = client_for(rig).post(
        BASE, json={"kind": "edit_image", "prompt": "hacerlo anochecer", "upload_id": record.id}
    )
    assert r.status_code == 200 and "dusk" in r.json()["prompt"]
    assert len(rig.pictures()) == 1  # described, never judged
