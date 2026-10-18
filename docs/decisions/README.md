# Architecture decision records

| ADR | Title | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-monorepo-platform-core-and-products.md) | Monorepo with platform core and thin products | Accepted |
| [0003](0003-fastapi-with-langgraph-library.md) | FastAPI hosting LangGraph as a library | Accepted |
| [0004](0004-nextjs-bff-and-sse.md) | Next.js frontend as BFF, SSE for streaming | Accepted |
| [0005](0005-litellm-gateway-for-all-inference.md) | LiteLLM gateway for all LLM inference | Accepted |
| [0006](0006-queue-based-media-jobs.md) | Queue-based media generation | Accepted |
| [0007](0007-single-postgres-with-pgvector.md) | Single Postgres for data, checkpoints and vectors | Accepted |
| [0008](0008-podman-engine-neutral-repo.md) | Podman for local development, engine-neutral repo | Accepted |
| [0009](0009-kubernetes-everywhere-three-layers.md) | Kubernetes everywhere, cloud-portable in three layers | Accepted |
| [0010](0010-capability-based-model-configuration.md) | Capability-based, swappable model configuration | Accepted |
| [0011](0011-tenancy-identity-usage-seams.md) | Tenancy, identity and usage seams from day one | Accepted |
| [0012](0012-music-model-ace-step.md) | Music model: ACE-Step 1.5, not YuE2 | Accepted |
| [0013](0013-auth-mvp-authjs.md) | MVP authentication with Auth.js | Accepted |
| [0014](0014-shared-nextjs-app.md) | One shared Next.js app with route groups | Accepted |
| [0015](0015-phase-0-tooling-choices.md) | Phase 0 tooling choices | Accepted |
| [0016](0016-helm-chart-structure.md) | One umbrella Helm chart, plain Ingress, in-cluster state for non-prod | Accepted |
| [0017](0017-platform-core-design.md) | Platform core: capability layer, usage events, storage and RAG | Accepted |
| [0018](0018-default-text-model-gemma4-e4b.md) | Default text model: Gemma 4 E4B | Accepted (default superseded alias by alias by 0078) |
| [0019](0019-cover-image-model-flux2-klein-4b.md) | Cover image model: FLUX.2 [klein] 4B | Accepted |
| [0020](0020-multimodal-input.md) | Multimodal input in the capability layer | Accepted |
| [0021](0021-media-pipeline-redis-streams.md) | Media pipeline on Redis Streams | Accepted |
| [0022](0022-song-graph-and-guardrail.md) | The song graph and its guardrail | Accepted |
| [0023](0023-product-provided-routes.md) | Product-provided API routes | Accepted |
| [0024](0024-real-model-validation.md) | Real-model validation of the music and cover workflows | Accepted |
| [0025](0025-model-access-configuration.md) | Model access configuration (local by default, admin-configurable) | Accepted |
| [0026](0026-seo.md) | SEO and discoverability | Proposed |
| [0027](0027-first-party-analytics.md) | First-party analytics | Proposed |
| [0028](0028-google-analytics-and-consent.md) | Google Analytics and consent | Proposed |
| [0029](0029-billing-and-payments.md) | Billing and payments (Stripe, prepaid credits) | Proposed |
| [0030](0030-authentication.md) | Authentication (Auth.js sign-in, signed API tokens) | Accepted |
| [0031](0031-model-access-implementation.md) | Model access: what building it taught us about LiteLLM | Accepted |
| [0032](0032-media-backends.md) | Media backends: local ComfyUI, Comfy Cloud and OpenAI-compatible image APIs | Accepted |
| [0033](0033-studio-home-and-product-urls.md) | The studio home page and product-scoped URLs | Accepted |
| [0034](0034-song-downloads.md) | Song downloads: audio with its cover inside, and a video | Accepted |
| [0035](0035-image-uploads.md) | Secured upload endpoint for user images | Accepted |
| [0036](0036-image-product.md) | The image product: text to image and image to image | Accepted |
| [0037](0037-video-product.md) | The video product: text to video and image to video (LTX-Video 2B) | Accepted |
| [0038](0038-prompt-enhancement.md) | Prompt enhancement for every product | Accepted |
| [0039](0039-picture-input.md) | Picture input: choose, drag and drop, paste | Accepted |
| [0040](0040-one-library.md) | One library: "My creations" | Accepted |
| [0041](0041-semantic-search.md) | Semantic search in My creations (multilingual, bge-m3) | Accepted |
| [0042](0042-text-to-speech.md) | Text to Speech (voice catalog; Kokoro and Indic Parler-TTS for Bengali and Indic languages) | Proposed |
| [0043](0043-speech-to-text.md) | Speech to Text (audio and video upload, recording, Whisper, chunked search) | Proposed |
| [0044](0044-lip-sync.md) | Lip Sync (MuseTalk; character image plus voice, song or script; safety policy) | Accepted |
| [0045](0045-ui-components.md) | UI components for forms and data grids (shadcn/ui, TanStack Table) | Accepted |
| [0046](0046-product-side-panel.md) | Product side panel (navigation inside a product) | Accepted |
| [0047](0047-safeguards-switch.md) | A system-wide safeguards switch (Admin on/off) | Accepted |
| [0048](0048-monitoring-and-alerting.md) | Monitoring and alerting (Prometheus stack in cluster, Telegram, external heartbeat) | Accepted |
| [0049](0049-data-inspection-tools.md) | Redis and Postgres viewers in every environment | Accepted |
| [0050](0050-langfuse-llm-observability.md) | LLM observability, analytics and cost tracking with Langfuse | Accepted |
| [0051](0051-model-catalog-variants-and-lora-chain.md) | Model catalog, capability variants and the LoRA chain | Withdrawn (moved to wasifyai-art) |
| [0052](0052-image-studio-loras-and-remix.md) | Image studio: base model, LoRAs, stored parameters and Remix | Withdrawn (moved to wasifyai-art) |
| [0053](0053-ai-tools-product.md) | AI Tools: a manifest-driven product, and Change Clothes | Withdrawn (moved to wasifyai-art) |
| [0054](0054-lora-training-product.md) | LoRA training: dataset, captions, trainer service, publish (Mac first) | Withdrawn (moved to wasifyai-art) |
| [0055](0055-rename-to-wasifyai.md) | Rename the project and every product from `wd-*` to `wasifyai` | Proposed |
| [0056](0056-desktop-app-and-web-share-one-engine.md) | The desktop app and the web product share one engine; image first | Accepted |
| [0057](0057-ai-assistant-chat-first-shell.md) | An AI assistant, ChatGPT-style, on desktop and web | Accepted |
| [0058](0058-desktop-link-runner-and-remote-ui.md) | Linking the web product to a user's desktop: a runner, and an optional remote UI | Accepted |
| [0059](0059-comfyui-managed-sidecar-image-engine.md) | ComfyUI as the managed image engine of the desktop app | Accepted |
| [0060](0060-documents-local-first-rag.md) | Documents: a local-first RAG product (ingest, search, grounded chat, generate) | Superseded by 0065 |
| [0061](0061-how-unsloth-code-enters-wasifyai.md) | How Unsloth code enters wasifyai: a reference clone and selective import, not a repo move | Accepted |
| [0062](0062-reuse-matrix-engines-per-capability.md) | Reuse matrix: which engine and which Unsloth parts, per capability | Accepted |
| [0063](0063-self-sufficient-desktop-discovers-existing-models-and-tools.md) | A self-sufficient desktop app that finds the models and tools already on the computer | Accepted |
| [0064](0064-model-hub-discover-and-on-device.md) | A model hub: discover open-weight models and see what is on the device | Accepted |
| [0065](0065-notebooks-source-grounded-workspace.md) | Notebooks: a NotebookLM-style, source-grounded workspace built on SurfSense's local code | Accepted (E0 gate) |
| [0066](0066-pluggable-speech-music-avatar-models.md) | Speech, music and lip sync run any model the person picks: descriptors, engine adapters and one dropdown | Accepted |
| [0067](0067-retire-the-older-web-products.md) | Retire the older music, speech and lip sync web products and delete what they made | Accepted |
| [0068](0068-one-action-catalogue.md) | One action catalogue: everything the product can do, described once | Accepted |
| [0069](0069-mcp-server.md) | An MCP server: Claude Code, Codex and OpenCode can use the app | Accepted |
| [0070](0070-mcp-client.md) | An MCP client: the assistant can use other people's MCP servers | Accepted |
| [0071](0071-assistant-that-knows-the-product.md) | An assistant that knows the product, guides, and runs it when the person clicks | Accepted |
| [0072](0072-agent-system-on-hermes.md) | An agent system for long tasks, built on Hermes Agent | Accepted |
| [0073](0073-training-platform.md) | Training in the app, made simple: one platform, Unsloth as the trainer, three simple cards | Accepted |
| [0074](0074-language-model-training.md) | Teach my assistant to write like me: language-model fine-tuning for non-technical people | Accepted |
| [0075](0075-decision-model-training.md) | Training a decision model: teach the app to sort and judge things | Accepted |
| [0076](0076-image-lora-training.md) | Make my own character or style: image LoRA from nothing but pictures (automatic captions and magic word) | Accepted |
| [0077](0077-compose-programmatic-video.md) | Compose (experimental): videos written as code, rendered deterministically | Accepted |
| [0078](0078-one-default-model-qwen35-9b.md) | One default model for the app: Qwen3.5-9B (switch alias by alias after checks) | Accepted |

New ADRs: run `/new-adr <title>` in Claude Code, or copy the structure of ADR-0001. Accepted ADRs are not edited; supersede them.
