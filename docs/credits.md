# Open-source credits

Written 2026-10-20 from the ADRs, the package manifests (`package.json`, `pyproject.toml`, `Cargo.toml`), the engine manifest
(`apps/desktop/src-tauri/engine-manifest.json`), the model descriptors (`products/*/models.yaml`) and the spike reports. Each repository and
its licence was checked on GitHub on the same day (a licence shown there as "Other" is explained in the notes). **This is the list of the
projects we chose to use, adapt or learn from; it is not the full inventory.** The several hundred packages these pull in are in `uv.lock`
and `pnpm-lock.yaml`; list their licences with `pnpm licenses list` and `uv pip list` plus the licence metadata, and add anything with a
copyleft or "other" licence here before a release. This file is not legal advice.

Status words: **Built** (in the app today), **Planned** (an Accepted ADR, not built), **Adapted** (we reused code, prompts or structure
under the licence), **Inspired** (we read it and built our own), **Considered** (evaluated, not adopted).

## 1. Obligations that need action

These are the places where a licence asks for more than "keep the notice". Items 1 to 6 matter for the first public release.

1. **Unsloth Studio** (`unslothai/unsloth`; Apache-2.0 repository, but `studio/*` and `unsloth_cli/*` are AGPL-3.0 and many files in the
   "Apache" packages carry AGPL headers; the MLX trainer `unsloth_zoo/mlx` is AGPL by header and LGPL by package metadata; spike T0).
   Planned as a **separate, unmodified process** with its `COPYING` and a source link; a qualified person must read the boundary before
   release (ADR-0073). We never copy its frontend into `packages/ui` or `apps/web` (ADR-0082).
2. **`apps/desktop`** is AGPL-3.0-only because it imported Tauri-shell ideas and code from Unsloth Studio (ADR-0056, ADR-0061); the
   rest of the repository is Apache-2.0. Keep the notices in `apps/desktop`.
3. **ComfyUI** (`Comfy-Org/ComfyUI`, **GPL-3.0**). Run as a separate sidecar process, never linked into our code; ship its licence with the
   component. Custom nodes run inside it (ADR-0059: we ship none).
4. **DINOv3** (Meta, a custom licence): a copy of the agreement must accompany any redistribution and "Built with DINOv3" is shown in the 3D
   feature's About and on each model card (ADR-0080).
5. **Parakeet TDT 0.6B v3** (NVIDIA, **CC-BY-4.0**): credit NVIDIA in the app's About page.
6. **LTX-Video 2B** (**OpenRAIL-M**: commercial use allowed; its use restrictions pass on to what people make) and the **Stability AI
   Community Licence** (Stable Audio 3 Small: free below a revenue threshold, never recommended automatically). Both are marked in the
   model catalogue with their conditions.
7. **psycopg** (**LGPL-3.0**): used as an unmodified library dependency; keep its licence text in the notices.
8. **`dompurify`** (a dependency of mermaid; MPL-2.0 OR Apache-2.0): we use the Apache-2.0 option.
9. **GSAP** (GreenSock "Standard No Charge" licence, not an OSI licence): fine for the free open-source desktop; ask again before any paid or
   hosted Video Builder (ADR-0077).
10. **OpenTofu** (MPL-2.0) and the **GPL/AGPL training tools we did not adopt** are tools or alternatives, not shipped.

## 2. Platform and backend (Built)

| Project | Repository | Licence | How we use it |
|---|---|---|---|
| FastAPI | `fastapi/fastapi` | MIT | The engine's HTTP API |
| uvicorn | `Kludex/uvicorn` | BSD-3-Clause | The server |
| Pydantic | `pydantic/pydantic` | MIT | Contracts and settings; the source of the TypeScript types |
| SQLAlchemy, Alembic | `sqlalchemy/sqlalchemy`, `sqlalchemy/alembic` | MIT | Records and migrations on the web profile |
| asyncpg | `MagicStack/asyncpg` | Apache-2.0 | Postgres driver |
| psycopg | `psycopg/psycopg` | LGPL-3.0 | The LangGraph Postgres saver and pgvector access (see section 1) |
| HTTPX | `encode/httpx` | BSD-3-Clause | HTTP client |
| PyJWT | `jpadilla/pyjwt` | MIT | Signing and checking the request token |
| LangGraph | `langchain-ai/langgraph` | MIT | The graph runtime for every product, with its Postgres and SQLite checkpointers |
| LiteLLM | `BerriAI/litellm` | MIT core (an `enterprise` folder is under its own licence; we use neither) | The model gateway and aliases on the web side (GitHub shows "Other") |
| Ollama | `ollama/ollama` | MIT | Optional local provider; the web stack's local model |
| OpenAI Python SDK | `openai/openai-python` | Apache-2.0 | OpenAI-compatible client |
| redis-py | `redis/redis-py` | MIT | Job queue and event streams (web) |
| pgvector | `pgvector/pgvector` | PostgreSQL licence | Vector search on the web profile (GitHub shows "Other") |
| sqlite-vec | `asg017/sqlite-vec` | Apache-2.0 | Vector search on the desktop profile |
| SeaweedFS | `seaweedfs/seaweedfs` | Apache-2.0 | S3-compatible object storage (replaced MinIO) |
| obstore | `developmentseed/obstore` | MIT | The storage interface |
| Pillow | `python-pillow/Pillow` | HPND (MIT-CMU), GitHub shows "Other" | Upload hardening and image handling |
| imageio-ffmpeg | `imageio/imageio-ffmpeg` | BSD-2-Clause | The FFmpeg binary for stills and mixing (FFmpeg itself is LGPL/GPL builds: see its notice) |
| prometheus client | `prometheus/client_python` | Apache-2.0 | Metrics |
| OpenTelemetry Python | `open-telemetry/opentelemetry-python` | Apache-2.0 | Tracing |
| Docling | `docling-project/docling` | MIT | The notebooks' document reader (PDF, Office, pictures of text) |
| chonkie | `feyninc/chonkie` | MIT | Chunking |
| onnxruntime | `microsoft/onnxruntime` | MIT | Runs the search model on the desktop |
| tokenizers | `huggingface/tokenizers` | Apache-2.0 | Token counting for chunking |
| markdown-it-py, python-pptx, python-docx, openpyxl, reportlab | `executablebooks/markdown-it-py`, `scanny/python-pptx`, `python-openxml/python-docx`, openpyxl (Heptapod), reportlab | MIT, MIT, MIT, MIT, BSD | Notebook Studio outputs (decks, Word, tables, PDF) |

## 3. Desktop shell (Built)

| Project | Repository | Licence | How we use it |
|---|---|---|---|
| Tauri 2 | `tauri-apps/tauri` | Apache-2.0 or MIT | The desktop shell, with the single-instance and updater plugins |
| tokio, reqwest | `tokio-rs/tokio`, `seanmonstar/reqwest` | MIT, Apache-2.0 | The shell's async runtime and HTTP |
| uv | `astral-sh/uv` | Apache-2.0 | Installs the engine's Python from a pinned, checksummed release |
| Python (CPython) | `python/cpython` | PSF (GitHub shows "Other") | The engine's interpreter |

## 4. Web and shared UI (Built)

| Project | Repository | Licence | How we use it |
|---|---|---|---|
| Next.js | `vercel/next.js` | MIT | The web app |
| React | `react/react` | MIT | UI |
| Tailwind CSS | `tailwindlabs/tailwindcss` | MIT | Styling on the design tokens |
| shadcn/ui | `shadcn-ui/ui` | MIT | Component source copied into `apps/web/components/ui` |
| Radix UI | `radix-ui/primitives` | MIT | Accessible primitives under the components |
| cmdk, sonner | `dip/cmdk`, `emilkowalski/sonner` | MIT | Command menu, toasts |
| Lucide | `lucide-icons/lucide` | ISC (GitHub shows "Other") | Icons |
| class-variance-authority, clsx, tailwind-merge | `joe-bell/cva`, `lukeed/clsx`, `dcastil/tailwind-merge` | Apache-2.0, MIT, MIT | Class helpers |
| TanStack Table | `TanStack/table` | MIT | Data grids |
| react-hook-form, Zod | `react-hook-form/react-hook-form`, `colinhacks/zod` | MIT | Forms and validation |
| Auth.js | `nextauthjs/next-auth` | ISC | Sign-in on the web |
| Vite | `vitejs/vite` | MIT | The desktop window's build |
| openapi-typescript | `openapi-ts/openapi-typescript` | MIT | Generates the TypeScript API types |
| assistant-ui | `assistant-ui/assistant-ui` | MIT | The chat thread runtime and primitives (ADR-0082) |
| streamdown and plugins | `vercel/streamdown` | Apache-2.0 (npm; GitHub shows "Other") | Streaming markdown in the new chat, hardened (ADR-0082) |
| KaTeX, Mermaid, Shiki | `KaTeX/KaTeX`, `mermaid-js/mermaid`, `shikijs/shiki` | MIT | Math, diagrams and code highlighting, loaded lazily |

## 5. Tooling, deployment and monitoring (Built)

| Project | Repository | Licence | How we use it |
|---|---|---|---|
| Biome, Turborepo, pnpm, TypeScript | `biomejs/biome`, `vercel/turborepo`, `pnpm/pnpm`, `microsoft/TypeScript` | Apache-2.0, MIT, MIT, Apache-2.0 | Lint, builds, packages, types |
| ruff, pyright, pytest | `astral-sh/ruff`, `microsoft/pyright`, `pytest-dev/pytest` | MIT, MIT, MIT | Python quality and tests |
| Vitest, Playwright | `vitest-dev/vitest`, `microsoft/playwright` | MIT, Apache-2.0 | Unit and browser tests |
| Podman, kind, Helm, Argo CD | `podman-container-tools/podman`, `kubernetes-sigs/kind`, `helm/helm`, `argoproj/argo-cd` | Apache-2.0 | Containers, local Kubernetes, charts, GitOps |
| OpenTofu, k3s | `opentofu/opentofu`, `k3s-io/k3s` | MPL-2.0, Apache-2.0 | Infrastructure code (staging, GCP) |
| Prometheus, Alertmanager | `prometheus/prometheus`, `prometheus/alertmanager` | Apache-2.0 | Monitoring and alerts (ADR-0048) |

## 6. Engines the desktop app runs (Built)

| Project | Repository | Licence | How we use it |
|---|---|---|---|
| ComfyUI | `Comfy-Org/ComfyUI` | GPL-3.0 | The image and video engine, as a sidecar process (section 1) |
| llama.cpp | `ggml-org/llama.cpp` | MIT | The local language engine (a pinned prebuilt release, run as a managed process) |
| audio.cpp | `0xShug0/audio.cpp` | Apache-2.0 per ADR-0066 (GitHub shows "Other") | Speech, music and audio tools runtime |
| MuseTalk | `TMElyralab/MuseTalk` | MIT (GitHub shows "Other") | Lip sync, an optional component |
| mflux | `mflux-community/mflux` | MIT | Image LoRA training on the Mac (a spike; planned in ADR-0076) |

## 7. Models in the catalogue (Built) and their projects

Weights have their own licences, recorded per model in `products/*/models.yaml` with a `commercial_use` flag (ADR-0012).

| Model | Project | Weights licence | Notes |
|---|---|---|---|
| FLUX.2 klein 4B | `black-forest-labs/flux2` | Apache-2.0 | Images |
| LTX-Video 2B | `Lightricks/LTX-Video` | OpenRAIL-M | Video; see section 1 |
| Kokoro 82M | `hexgrad/kokoro` | Apache-2.0 | Speech |
| Qwen3-TTS 0.6B, 1.7B | `QwenLM/Qwen3-TTS` | Apache-2.0 | Voice cloning and design |
| VoxCPM2 | `OpenBMB/VoxCPM` | Apache-2.0 | Speech |
| Parakeet TDT 0.6B v3 | `NVIDIA-NeMo` (NeMo) | CC-BY-4.0 | Speech to text; credit NVIDIA |
| ACE-Step 1.5 Turbo | `ace-step/ACE-Step-1.5` | MIT | Music |
| Stable Audio 3 Small | `Stability-AI/stable-audio-tools` | Stability AI Community Licence | Music and sound effects, never recommended automatically |
| HTDemucs (4 and 6 stems), Mel-Band RoFormer | `facebookresearch/demucs`, an MLX port | MIT | Splitting recordings into parts |
| Tone Color VC | `myshell-ai/OpenVoice` | MIT | Change a voice |
| MeanVC2 | `ASLP-lab/MeanVC2` | Apache-2.0 | Change a voice |
| dots.tts Edit | `dots-studio/dots.tts.edit` | Apache-2.0 project, the weights card says "other" | Edit speech; conditional |
| MuseTalk 1.5 | `TMElyralab/MuseTalk` | MIT | Lip sync |
| bge-small-en-v1.5 (ONNX) | `FlagOpen/FlagEmbedding` | MIT | Notebook and help search |

## 8. Adapted, or the model for our own build

| Project | Repository | Licence | What we took |
|---|---|---|---|
| Unsloth | `unslothai/unsloth` | Apache-2.0 with AGPL parts (section 1) | The gallery with a restorable recipe, the load, progress and cancel route shapes, the single-resident-model design, the provisioning and install approach (ADR-0061, ADR-0062); Studio's trainer is planned as a separate component |
| SurfSense | `MODSetter/SurfSense` | Apache-2.0 | The notebooks' hybrid retrieval blend, grounding prompts, recursive chunking rules and Studio output prompts (ADR-0065) |
| assistant-ui (the project Unsloth Studio uses) | see section 4 | MIT | Adopted as the chat runtime after the CU0 spike |

## 9. Accepted, not built yet

| Project | Repository | Licence | Use (ADR) |
|---|---|---|---|
| Hermes Agent | `NousResearch/hermes-agent` | MIT | The agent engine behind our `AgentEngine` interface (0072) |
| MCP Python SDK | `modelcontextprotocol/python-sdk` | MIT | Our MCP server and client (0069, 0070) |
| Claude Code, Codex, OpenCode | Anthropic (closed), `openai/codex`, `anomalyco/opencode` | Apache-2.0, MIT | MCP clients tested in spike S1; not dependencies |
| HyperFrames | `heygen-com/hyperframes` | Apache-2.0 | Video Builder's render engine (0077) |
| motion-skills (iart.ai) | `iart-ai/motion-skills` and its packs | MIT (one pack has no licence and is excluded) | Reviewed, pinned, adapted content for Motion graphics (0079) |
| Pixal3D | `TencentARC/Pixal3D` | MIT | Text and image to 3D (0080) |
| pixal3d.cpp, trellis.cpp | `raven38/pixal3d.cpp`, `pwilkin/trellis.cpp` | MIT | The native runtime that runs Pixal3D (0080) |
| TRELLIS.2 | `microsoft/TRELLIS.2` | MIT | The backbone Pixal3D builds on; not offered in v1 |
| BiRefNet, MoGe-2 | `ZhengPeng7/BiRefNet`, `microsoft/MoGe` | MIT | Background removal and camera estimate inside the 3D runtime |
| DINOv3 | `facebookresearch/dinov3` | Meta's DINOv3 licence (section 1) | The image encoder carried in the 3D weights |
| Laya (and Cloudflare's Clef) | `NandhaKishorM/laya` (the `laya` package on PyPI, 0.4.15), Hugging Face `convaiinnovations/laya`, `Cloudflare/clef-flash` | Apache-2.0 (the package ships a `LICENSE`; the weights repository declares it in its card and has no licence file; T0). Clef is not used | "Teach it to decide" decision models (0075): the trainer and runtime, in an environment of its own |
| PyTorch | `pytorch/pytorch` | BSD-3-Clause | Runs Laya on the Mac's graphics chip (MPS) in the decision trainer's environment (0075) |
| mlx, mlx-lm | `ml-explore/mlx`, `ml-explore/mlx-lm` | MIT | The Mac training and serving backends behind Unsloth |
| Hugging Face Transformers | `huggingface/transformers` | Apache-2.0 | Behind the training component |
| Qwen3.5-9B | Qwen (Hugging Face) | Apache-2.0 | The planned default chat and agent model (0078) |
| `ddgs` (DuckDuckGo metasearch) and `trafilatura` | `deedy5/ddgs`, `adbar/trafilatura` | MIT, Apache-2.0 | Web search and page reading for the composer (0083, CO3; pinned in `packages/platform-sdk`) |

## 10. Inspired by, or read as a reference

| Project | Repository | Licence | What we learned |
|---|---|---|---|
| Unsloth Studio | `unslothai/unsloth` (`studio/`) | AGPL-3.0 | The chat and training UIs; read for ideas, never copied |
| AssetFurnace | `Bingeljell/image-to-3dlab` | Apache-2.0 | A full text to picture to 3D studio with finishing and per-file licence provenance |
| trellis-mac, trellis2mlx | `shivampkumar/trellis-mac`, `lyonsno/trellis2mlx` | MIT (the second shows "Other"; its README says MIT) | Evidence that TRELLIS.2 runs on the Mac |
| build-your-own-x | `codecrafters-io/build-your-own-x` | none shown | A learning reference mentioned in the docs |

## 11. Considered and not adopted

| Project | Repository | Licence | Why not |
|---|---|---|---|
| Open WebUI | `open-webui/open-webui` | Custom (BSD-3 with a branding clause) | A whole product with its own server |
| LibreChat | `LibreChat-AI/LibreChat` | MIT | Same |
| Ostris AI Toolkit | `ostris/ai-toolkit` | MIT | Kept as an optional NVIDIA training engine; not on the Mac |
| Kohya, SimpleTuner, OneTrainer | `bmaltais/kohya_ss`, `bghira/SimpleTuner`, `Nerogar/OneTrainer` | Apache-2.0, AGPL-3.0, AGPL-3.0 | NVIDIA trainers with no Mac path; the last two are AGPL |
| stable-diffusion.cpp, whisper.cpp | `leejet/stable-diffusion.cpp`, `ggml-org/whisper.cpp` | MIT | Measured against ComfyUI and audio.cpp; kept as fallbacks |
| Remotion | `remotion-dev/remotion` | Custom (free for individuals and up to 3 employees; paid beyond) | A paid licence for larger companies |
| Style Dictionary | `style-dictionary/style-dictionary` | Apache-2.0 | Our own 200-line generator does the job for now |
| TripoSR, Hunyuan3D-2, Stable Fast 3D | `VAST-AI-Research/TripoSR`, `Tencent-Hunyuan/Hunyuan3D-2`, `Stability-AI/stable-fast-3d` | MIT, Tencent Hunyuan Community Licence (reported not valid in the EU, UK and South Korea), Stability Community Licence | Licence or quality limits; read before any use |
| `@assistant-ui/react-langgraph`, the Vercel AI SDK `useChat` | within `assistant-ui/assistant-ui`, `vercel/ai` | MIT, Apache-2.0 (GitHub shows "Other" for the AI SDK) | Assume a different server protocol than our engine |

## 12. Keeping this file true

- Add a row when a dependency or a component is added or adopted, in the same change (rule 12, and ADR-0012 for models).
- Re-check the licence when a version is bumped in a way that could change it (the 3D stack, streamdown, Unsloth and the notebooks reader are the ones to watch).
- Before a public release: generate the full licence lists from the lock files, confirm nothing copyleft or "other" is missing here, and
  ship the notices for sections 1 and 7 inside the app's About page.
