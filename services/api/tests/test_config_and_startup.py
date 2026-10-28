import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from wasifyai_api.assemble import Injected
from wasifyai_api.graphs import default_registry
from wasifyai_api.graphs.hello import build_hello
from wasifyai_api.main import create_app
from wasifyai_platform_sdk import (
    ConfigError,
    GraphRegistry,
    InMemoryEventLog,
    InMemoryRunStore,
    InMemoryUsageRecorder,
)


def test_bad_product_config_fails_at_startup(tmp_path):
    (tmp_path / "hello").mkdir()
    (tmp_path / "hello" / "product.yaml").write_text(
        "id: hello\ncapabilities:\n  text.chat: { provider: litellm }\n"
    )
    registry = GraphRegistry()
    registry.register("hello", build_hello)
    app = create_app(
        Injected(
            registry=registry,
            products_dir=tmp_path,
            checkpointer=InMemorySaver(),
            usage=InMemoryUsageRecorder(),
            event_log=InMemoryEventLog(),
            run_store=InMemoryRunStore(),
        )
    )
    with pytest.raises(ConfigError, match="requires 'model'"):
        with TestClient(app):
            pass


def test_committed_hello_config_boots(tmp_path):
    from pathlib import Path

    products = Path(__file__).resolve().parents[3] / "products"
    app = create_app(
        Injected(
            registry=default_registry(),
            products_dir=products,
            checkpointer=InMemorySaver(),
            usage=InMemoryUsageRecorder(),
            event_log=InMemoryEventLog(),
            run_store=InMemoryRunStore(),
        )
    )
    with TestClient(app) as c:
        assert c.get("/health").json() == {"status": "ok"}


def test_every_product_route_requires_an_identity():
    """Rule 8: no endpoint skips identity. With identity resolution rejecting everyone, every
    route a product adds must answer 401 (checked black-box, from the OpenAPI document)."""
    from pathlib import Path

    from fastapi import HTTPException
    from wasifyai_api.identity import get_identity

    products = Path(__file__).resolve().parents[3] / "products"
    app = create_app(
        Injected(
            registry=default_registry(),
            products_dir=products,
            checkpointer=InMemorySaver(),
            usage=InMemoryUsageRecorder(),
            event_log=InMemoryEventLog(),
            run_store=InMemoryRunStore(),
        )
    )

    def nobody():
        raise HTTPException(401, "no identity")

    app.dependency_overrides[get_identity] = nobody
    paths = app.openapi()["paths"]
    mine = {p: ops for p, ops in paths.items() if p.startswith("/products/wasifyai-voice/")}
    assert (
        "/products/wasifyai-voice/tracks" in mine
        and "/products/wasifyai-voice/tracks/{tid}" in mine
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        for path, ops in mine.items():
            for method in ops:
                resp = client.request(
                    method.upper(),
                    path.replace("{tid}", "x")
                    .replace("{sid}", "x")
                    .replace("{vid}", "x")
                    .replace("{cid}", "x"),
                )
                assert resp.status_code == 401, (method, path, resp.status_code)
