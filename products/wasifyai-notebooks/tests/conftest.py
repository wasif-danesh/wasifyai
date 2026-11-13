import uuid

import pytest
from notebooks_rig import pg_dsn
from wasifyai_notebooks.store import NotebookStore


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(params=["sqlite", "postgres"])
def new_store(request, tmp_path):
    """Makes a notebook store on SQLite or on Postgres: the same tests run against both. A store of
    the same `name` opens the same library again. Each Postgres test has schemas of its own, dropped
    at the end, so nothing of a real library is touched."""

    prefix = f"nbt_{uuid.uuid4().hex[:10]}"
    made: list[NotebookStore] = []

    def make(*, dimension: int, embedder_id: str, name: str = "db"):
        if request.param == "sqlite":
            return NotebookStore.in_folder(
                tmp_path / name, dimension=dimension, embedder_id=embedder_id
            )
        store = NotebookStore.on_postgres(
            pg_dsn(), dimension=dimension, embedder_id=embedder_id, schema=f"{prefix}_{name}"
        )
        made.append(store)
        return store

    make.backend = request.param  # type: ignore[attr-defined]
    yield make
    for store in made:
        store.drop_schema()
        store.close()


@pytest.fixture
def use_backends(new_store, monkeypatch):
    """Runs a module's tests on both databases: the test rigs make their store through the
    `NotebookStore` name of their module, which is pointed at `new_store` for the test."""
    import sys
    from pathlib import Path
    from types import SimpleNamespace

    def factory(root, *, dimension, embedder_id):
        Path(root).mkdir(parents=True, exist_ok=True)  # the SQLite store makes its folder
        return new_store(dimension=dimension, embedder_id=embedder_id, name=Path(root).name)

    for name in ("test_notebooks_chat", "test_notebooks_routes"):
        module = sys.modules.get(name)
        if module is not None:
            # the rigs call `NotebookStore.in_folder(...)`
            stand_in = SimpleNamespace(in_folder=factory)
            monkeypatch.setattr(module, "NotebookStore", stand_in, raising=False)
