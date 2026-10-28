import uuid

import pytest
from voice_rig import pg_dsn
from wasifyai_voice.store import VoiceStore


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(params=["sqlite", "postgres"])
def new_store(request, tmp_path):
    """Makes a voice store on SQLite or on Postgres: the same tests run against both. Each
    Postgres test has a schema of its own, dropped at the end, so nothing real is touched."""

    made: list[VoiceStore] = []

    def make(name: str = "voice"):
        if request.param == "sqlite":
            return VoiceStore.in_folder(tmp_path / name)
        store = VoiceStore.on_postgres(pg_dsn(), schema=f"vt_{uuid.uuid4().hex[:10]}_{name}")
        made.append(store)
        return store

    make.backend = request.param  # type: ignore[attr-defined]
    yield make
    for store in made:
        store.drop_schema()
        store.close()


@pytest.fixture
def use_backends(new_store, monkeypatch):
    """Runs a module's tests on both databases: the rigs build the engine's app state with
    `app_state`, which gets the web's Postgres store for the Postgres run."""
    import sys

    import voice_rig

    def with_store(tmp_path, engine=None, store=None):
        chosen = new_store() if new_store.backend == "postgres" else store
        return voice_rig.app_state(tmp_path, engine, chosen)

    for name in ("test_voice_graph", "test_voice_dub", "test_voice_book"):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, "app_state"):
            monkeypatch.setattr(module, "app_state", with_store)
