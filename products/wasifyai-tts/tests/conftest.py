"""Fixtures for the image product."""

import pytest
from tts_rig import CTX
from wasifyai_platform_sdk import reset_context, set_context


@pytest.fixture
def ctx():
    token = set_context(CTX)
    yield CTX
    reset_context(token)
