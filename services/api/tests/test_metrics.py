"""Metrics (ADR-0048): runs and requests are counted, and no label carries user data."""

import re

from fastapi.testclient import TestClient
from prometheus_client import generate_latest
from wasifyai_api.metrics import UPLOADS, record_run
from wasifyai_platform_sdk import InMemoryUsageRecorder

from tests.test_runs import hello_registry, mem_app


def scrape() -> str:
    return generate_latest().decode()


def test_a_run_is_counted_by_product_and_outcome(tmp_path):
    (tmp_path / "hello").mkdir()
    (tmp_path / "hello" / "product.yaml").write_text(
        "id: hello\ncapabilities:\n  text.chat: { provider: fake, defaults: { reply: hi } }\n"
    )
    app = mem_app(hello_registry(), tmp_path, InMemoryUsageRecorder())
    with TestClient(app) as c:
        r = c.post("/products/hello/runs", json={"input": {"message": "hi"}})
        assert r.status_code == 200
        text = scrape()
    assert 'wdai_runs_total{outcome="done",product="hello"}' in text
    assert 'wdai_http_requests_total{method="POST",route="/products/{product_id}/runs"' in text


def test_refusals_and_errors_use_bounded_codes():
    record_run("wasifyai-image", "refused", refusal="real_person_photo")
    record_run("wasifyai-video", "error", code="job_failed")
    UPLOADS.labels("image", "refused").inc()
    text = scrape()
    assert 'wdai_refusals_total{category="real_person_photo",product="wasifyai-image"}' in text
    assert 'wdai_run_errors_total{code="job_failed",product="wasifyai-video"}' in text


def test_no_label_carries_a_user_id_an_email_or_a_uuid():
    record_run("wasifyai-music", "done")
    pairs = re.findall(r'(\w+)="([^"]*)"', " ".join(re.findall(r"\{([^}]*)\}", scrape())))
    names = {name for name, _ in pairs}
    # a label may be a route template like /admin/users, but never an identity or content field
    assert not names & {
        "user",
        "user_id",
        "tenant",
        "tenant_id",
        "email",
        "prompt",
        "text",
        "thread_id",
    }
    for _, value in pairs:
        assert "@" not in value
        assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}", value)
