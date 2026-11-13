"""What is particular to the Postgres store: its schema, several replicas starting at once, and the
vectors living in the passage row."""

import threading

import pytest
from notebooks_rig import SPEC, pg_dsn
from wasifyai_notebooks.chunking import Passage
from wasifyai_notebooks.retrieval import retrieve
from wasifyai_notebooks.store import NotebookStore
from wasifyai_platform_sdk.pg import translate, vector_text


def test_the_schema_name_is_checked_before_it_is_used_in_sql():
    for bad in ("Notebooks", "a;drop table x", "", "1abc", 'a"b'):
        with pytest.raises(ValueError, match="schema name"):
            NotebookStore.on_postgres("postgresql://x", dimension=4, embedder_id="e", schema=bad)


def test_sql_parameters_are_translated_and_percent_signs_kept():
    assert (
        translate("SELECT 1 WHERE a = ? AND b LIKE '50%'")
        == "SELECT 1 WHERE a = %s AND b LIKE '50%%'"
    )
    assert vector_text([0.5, 1, -2.25]) == "[0.5,1.0,-2.25]"


def test_several_replicas_can_start_on_a_new_schema_at_once(new_store):
    if new_store.backend != "postgres":
        pytest.skip("Postgres only")
    first = new_store(dimension=SPEC.dimension, embedder_id=SPEC.id, name="shared")
    errors: list[BaseException] = []
    started: list[NotebookStore] = []

    def start():
        try:
            started.append(
                NotebookStore.on_postgres(
                    pg_dsn(), dimension=SPEC.dimension, embedder_id=SPEC.id, schema=first.schema
                )
            )
        except BaseException as e:  # noqa: BLE001 - reported below
            errors.append(e)

    threads = [threading.Thread(target=start) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    try:
        assert errors == []
        nb = first.create_notebook("t", "u", "seen by all")
        assert all(s.get_notebook("t", "u", nb["id"])["title"] == "seen by all" for s in started)
    finally:
        for s in started:
            s.close()


def test_a_passage_and_its_vector_go_together_and_a_search_stays_in_its_notebook(new_store):
    if new_store.backend != "postgres":
        pytest.skip("Postgres only")
    store = new_store(dimension=SPEC.dimension, embedder_id=SPEC.id)
    one, two = (store.create_notebook("t", "u", n) for n in ("one", "two"))

    def add(nb, name, text, axis):
        d, _ = store.add_file(
            "t",
            "u",
            nb["id"],
            title=name,
            suffix=".txt",
            mime="text/plain",
            size_bytes=1,
            sha256=name,
        )
        store.begin(d["id"])
        vector = [0.0] * SPEC.dimension
        vector[axis] = 1.0
        store.finish(
            d["id"], markdown=text, pages=1, passages=[Passage(text, 1, 1)], vectors=[vector],
            embedder=SPEC.id,
        )  # fmt: skip
        return d

    add(one, "a.txt", "warranty lasts eighteen months", 0)
    add(two, "b.txt", "warranty lasts two years", 0)  # the same direction, in another notebook
    query = [0.0] * SPEC.dimension
    query[0] = 1.0
    with store.connect() as db:
        hits = retrieve(db, one["id"], "warranty", query, weight=0.65, mode="dense")
        assert [h.title for h in hits] == ["a.txt"]
        assert hits[0].score == pytest.approx(1.0, abs=1e-6)
    with store.connect() as db:
        assert (
            db.execute("SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL").fetchone()[0] == 2
        )
    store.delete_notebook("t", "u", one["id"])
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 1


def test_the_vector_extension_goes_in_public_where_the_migrations_look_for_it():
    """The API can start before the migrations (a fresh cluster): the store's search path begins
    with its own schema, and an extension made there made the migrations fail with `type "vector"
    does not exist`. A database of its own, so the test sees the extension being created."""
    import uuid

    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    base = pg_dsn()
    name = f"vec_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        dsn = make_conninfo(base, dbname=name)
        store = NotebookStore.on_postgres(dsn, dimension=4, embedder_id="e", schema="nbt_vec")
        store.close()
        with psycopg.connect(dsn) as conn:
            where = conn.execute(
                "SELECT n.nspname FROM pg_extension e "
                "JOIN pg_namespace n ON n.oid = e.extnamespace WHERE e.extname = 'vector'"
            ).fetchone()
            # and a migration's `vector(768)` resolves on a connection that knows only `public`
            conn.execute("CREATE TABLE t (embedding vector(768))")
        assert where == ("public",)
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )
