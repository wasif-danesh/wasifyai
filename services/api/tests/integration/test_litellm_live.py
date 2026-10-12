from pathlib import Path

from sqlalchemy import text
from wasifyai_api.rag import DIMENSIONS, RagService
from wasifyai_platform_sdk import (
    PostgresUsageRecorder,
    ProviderDeps,
    build_capabilities,
    load_product_config,
)

PRODUCTS = Path(__file__).resolve().parents[4] / "products"


async def test_real_chat_and_embeddings_record_usage_and_rag_works(
    engine, run_ctx, litellm_settings
):
    """Real LiteLLM -> Ollama: streamed tokens, usage rows, searchable 768-dim embeddings."""
    s = litellm_settings
    cfg = load_product_config(PRODUCTS, "hello", environ={})
    cfg.capabilities["text.embed"] = cfg.capabilities["text.chat"].model_copy(
        update={"model": "embedder"}
    )
    deps = ProviderDeps(
        PRODUCTS,
        usage=PostgresUsageRecorder(engine),
        litellm_base_url=s.litellm_base_url,
        litellm_api_key=s.litellm_api_key,
        embedding_dims=DIMENSIONS,
    )
    caps = build_capabilities(cfg, deps)

    reply = await caps.text.complete("chat", "Answer in one short sentence.", "Say hello.")
    assert reply.strip()

    vectors = await caps.text.embed("embed", ["a cat purring", "stock market crash"])
    assert len(vectors) == 2 and len(vectors[0]) == DIMENSIONS

    rag = RagService(engine, lambda t: caps.text.embed("embed", t))
    await rag.ingest("live", "d1", "The cat purred softly on the sofa.")
    await rag.ingest("live", "d2", "Interest rates rose and bond markets fell sharply.")
    assert (await rag.search("live", "kitten sound", k=1))[0].document_id == "d1"
    await rag.delete_document("live", "d1")
    await rag.delete_document("live", "d2")

    async with engine.connect() as c:
        kinds = {
            r[0]
            for r in await c.execute(
                text("select kind from usage_events where run_id=:r"), {"r": run_ctx.run_id}
            )
        }
    assert {"llm.input_tokens", "llm.output_tokens", "llm.embedding_tokens"} <= kinds
