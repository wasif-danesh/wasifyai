from uuid import uuid4

from sqlalchemy import text
from wasifyai_api.rag import DIMENSIONS, RagService, chunk_text
from wasifyai_platform_sdk import (
    CapabilityBinding,
    InMemoryUsageRecorder,
    PostgresUsageRecorder,
    RunContext,
    UsageEvent,
    set_context,
)
from wasifyai_platform_sdk.providers.fake import FakeTextProvider


async def test_usage_event_is_stored_with_tenancy(engine, run_ctx):
    run_id = f"run-{uuid4()}"
    ev = UsageEvent.for_context(
        RunContext("it-tenant", "it-product", "it-user", run_id),
        "llm.input_tokens",
        42,
        "tokens",
        alias="x",
    )
    await PostgresUsageRecorder(engine).record(ev)
    async with engine.connect() as c:
        row = (
            await c.execute(
                text(
                    "select tenant_id, product_id, user_id, kind, quantity, unit, meta "
                    "from usage_events where run_id=:r"
                ),
                {"r": run_id},
            )
        ).one()
    assert tuple(row[:6]) == (
        "it-tenant",
        "it-product",
        "it-user",
        "llm.input_tokens",
        42.0,
        "tokens",
    )
    assert row[6] == {"alias": "x"}


def fake_embedder():
    provider = FakeTextProvider(InMemoryUsageRecorder(), DIMENSIONS)

    async def embed(texts):
        return await provider.embed("text.embed", CapabilityBinding(provider="fake"), texts)

    return embed


async def test_rag_ingest_search_replace_and_isolation(engine, run_ctx):
    rag = RagService(engine, fake_embedder())
    coll = f"c-{uuid4()}"
    await rag.ingest(coll, "cats", "Cats purr and sleep all day on warm windowsills.", {"src": "a"})
    await rag.ingest(coll, "ships", "Container ships carry cargo across the ocean between ports.")

    hits = await rag.search(coll, "why do cats purr", k=2)
    assert hits[0].document_id == "cats" and hits[0].metadata == {"src": "a"}
    assert hits[0].score > hits[1].score

    # re-ingesting replaces, it does not duplicate
    await rag.ingest(coll, "cats", "Dogs bark loudly at strangers.")
    docs = [h.document_id for h in await rag.search(coll, "anything", k=10)]
    assert docs.count("cats") == 1

    # another tenant sees nothing from this collection
    token = set_context(RunContext("other-tenant", "it-product", "u"))
    assert await rag.search(coll, "cats", k=5) == []
    from wasifyai_platform_sdk import reset_context

    reset_context(token)

    await rag.delete_document(coll, "cats")
    await rag.delete_document(coll, "ships")
    assert await rag.search(coll, "cats") == []


def test_chunking_respects_size_and_overlap():
    text_ = "\n\n".join(f"Paragraph {i}. " + "word " * 60 for i in range(10))
    chunks = chunk_text(text_, size=500, overlap=50)
    assert len(chunks) > 1 and all(len(c) <= 500 for c in chunks)
    assert chunk_text("") == [] and chunk_text("short") == ["short"]
    big = chunk_text("x" * 2000, size=500, overlap=50)
    assert all(len(c) <= 500 for c in big) and sum(len(c) for c in big) >= 2000
