# Tests run without sign-in unless a test asks for it (ADR-0030); the API default is "jwt".
import os

os.environ.setdefault("AUTH_MODE", "stub")


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_vendor_lists(monkeypatch):
    """No test asks a real vendor for its models; a test that wants a list passes a `lister`."""
    from wasifyai_api import own_keys

    async def nothing(provider, key):
        return []

    monkeypatch.setattr(own_keys, "list_models", nothing)
