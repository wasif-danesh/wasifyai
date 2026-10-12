"""Fixtures for the video product."""

import pytest
from video_rig import CTX
from wasifyai_platform_sdk import reset_context, set_context


@pytest.fixture
def ctx():
    token = set_context(CTX)
    yield CTX
    reset_context(token)
