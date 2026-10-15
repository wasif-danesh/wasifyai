"""Fixtures for the assistant product."""

import pytest
from wasifyai_platform_sdk import RunContext, reset_context, set_context

CTX = RunContext("t1", "wasifyai-assistant", "u1", run_id="r1", thread_id="th1")


@pytest.fixture
def ctx():
    token = set_context(CTX)
    yield CTX
    reset_context(token)
