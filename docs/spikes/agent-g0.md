# Spike G0: Hermes Agent as a managed agent component, and Qwen3.5-9B at 64,000 tokens

Date: 2026-10-18 and 2026-10-19. Machine: MacBook Pro, Apple M5 Pro, **64 GB** (so the 32 GB case is **not measured**).
Plan: `docs/phase5-agent-training-video-builder-plan.md`, stage G0. Decisions tested: ADR-0072 (agent on Hermes) and
ADR-0078 (Qwen3.5-9B as the one default model). Nothing here changed an ADR; where a finding contradicts one, it is
listed under "What this changes".

Scratch folder (outside the repo, kept): `~/Projects/wasifyai-spikes/g0/` (scripts, raw JSON-RPC logs, reports the agent
wrote, `NOTES.md`). Every number below comes from a file there. Anything not run is marked **not verified**.

## Result in one screen

| Question | Answer |
|---|---|
| Which control path | **TUI gateway over stdio** (`python -m tui_gateway.entry`), one process per task. ACP also works and is the second choice. The HTTP API is the weakest fit |
| Per-task toolset, working folder, write-root | **Yes, with the right levers** (table below). Toolset is configuration, not a call argument; write-root is a process environment variable |
| Events, approvals from outside, stop | **Yes on all three paths**, each verified with a scripted model. Stop ends a running command in 0.15 s |
| Hermes MCP client against a stub MCP server | **Works** (2 tools discovered and called; untrusted-server approval verified) |
| Qwen3.5-9B holds 64,000 tokens | **Yes.** A 62,038-token prompt ran; 2 of 2 hidden-fact lookups at 62,056 tokens were exact. About **8 GB** of memory in total at 64k |
| Speed (Q4_K_M, llama.cpp Metal) | Reading the prompt: 1,080 / 858 / 686 tokens/s at 8k / 32k / 62k. Writing: 39.3 / 37.4 / 28.5 tokens/s |
| Thinks by default | **Yes.** Off with `--reasoning off` (server) or `chat_template_kwargs {"enable_thinking": false}` (request) |
| Tool calling | **10 of 10** small cases, thinking on and off |
| GitHub Models | **Retired on 2026-07-30.** ADR-0072's hosted line for GitHub no longer holds |
| Hugging Face Inference Providers | Serves Qwen3.5-9B at **262,144** context, with tools, three providers, pay as you go |
| The example task, local model | Ran end to end in 71 to 143 s, **but only 1 of 3 runs found the right repository** |
| The example task, hosted model | **Not run**: no key in the environment |
| **Stage G1** | **Go**, with the conditions at the end |

## 1. Hermes Agent: what was tested

Version: **v0.21.5+8505.g13dc3a7 (2026.9.24)**, commit `13dc3a73895a` (2026-10-06), MIT, Python 3.14.7, `mcp` SDK 2.0.0.
This copy was already on the owner's Mac (`~/.hermes/hermes-agent`, installed by the owner for `Hermes.app`); with the
owner's yes I ran its code with `HERMES_HOME=<scratch>/home2`, so `~/.hermes` was not read or written by my runs.
Hermes's own documentation in that checkout (`website/docs/developer-guide/programmatic-integration.md`, the generated
gateway contract `apps/shared/src/gateway-contract.openrpc.json`, 252 methods) was read, and each claim below was then
exercised. A **scripted fake model** (an OpenAI-compatible server that returns planned tool calls) made the protocol
tests deterministic and free of model memory; real-model runs are in sections 3 and 5.

### Control paths

| | **TUI gateway** (stdio JSON-RPC, ndjson) | **ACP** (`python -m acp_adapter.entry`, stdio) | **HTTP API** (`hermes gateway run`, port, bearer key) |
|---|---|---|---|
| Start cost | `gateway.ready` in 1.1 to 1.7 s; 309 MB idle | similar (not timed) | starts the whole messaging gateway process |
| Set the working folder per task | **Yes.** `session.create {cwd, cwd_explicit}`, `session.cwd.set`. Verified: the shell ran in that folder | **Yes.** `session/new {cwd}` | **No** per run. Runs use the process folder |
| Set the toolset per task | **Yes, through config.** `platform_toolsets.cli` in the config file; or `profiles.create` then `profiles.configure {name, enabled_toolsets}` then `session.create {profile}`. `tools.configure` also works but **writes the home's config**, it is not per session. `session.create` has **no** toolset argument. Verified: the model was offered only `clarify, patch, read_file, search_files, write_file` | Config only (`platform_toolsets.acp`, default `hermes-acp`, includes `terminal` and `execute_code`) | Config only (`platform_toolsets.api_server`). `POST /v1/runs` accepts `input, instructions, session_id, conversation_history, model`; no toolsets, folder or limits |
| Write-root per task | **Process environment** `HERMES_WRITE_SAFE_ROOT` (one or more folders). Verified: `write_file` outside it was refused, inside it worked. So **one gateway process per task** | same variable | same variable (whole gateway process) |
| MCP servers per task | Configured in the profile/home (`mcp.servers.add/test/list`, `enabled_mcp_servers` in `profiles.configure`) | **Per session**: `session/new {mcpServers: [...]}` (verified: 23 tools after registration) | Config |
| Stream events | `message.delta`, `tool.generating/start/complete`, `session.usage`, `message.complete`, `error` (verified) | `session/update`: `agent_message_chunk`, `tool_call`, `tool_call_update` (verified) | SSE `/v1/runs/{id}/events`: `tool.started/completed`, `approval.request`, `message.delta`, `run.completed/cancelled` (verified) |
| Answer approvals from the host | **Yes.** Server request `approval {command, description, pattern_key, allow_permanent, allow_session, request_id}`, host replies `{choice}`. The host must first call `client.capabilities {server_requests: true}`, else the request is refused. Verified `deny` (the command did not run) and `once` (it ran) | **Yes.** `session/request_permission` with five options (allow once, for session, always, deny, deny always). Verified reject and allow once | **Yes.** `approval.request` event, then `POST /v1/runs/{id}/approval {choice}`. Verified |
| Stop a task | `session.interrupt` returns `interrupted`; the running command ended in **0.15 s** with exit 130 and the child process was gone (checked with `pgrep`) | `session/cancel` gives `stopReason: cancelled` (child gone) | `POST /v1/runs/{id}/stop` gives `run.cancelled`, `turn_exit_reason: interrupted_by_user` |
| Also exposes | clarify questions to the host (`clarify`), `session.steer`, session branching, usage, 252 methods in a generated contract | editor features, session fork/list/resume | OpenAI-compatible chat and responses endpoints, steer |

**Recommended: the TUI gateway.** It is the only path where the host sets the folder per task, can ask clarifying
questions through the host, receives usage, and has a generated, versioned contract (which suits a pinned component).
ACP is a sound second choice and is the only one with per-session MCP servers; its `allow_always` options must be
filtered by the host. The HTTP API cannot set a folder or toolset per run and brings in the messaging gateway; not
recommended.

### What Hermes does not enforce (this decides the profiles in ADR-0072)

All verified with the scripted model.

1. **Default toolsets on a fresh home are wide:** `browser` (18 tools), `computer_use`, `code_execution`, `terminal`,
   `cronjob`, `memory`, `skills`, `delegation`, `image_gen`, `tts`, `connections` and more are enabled. A profile created
   with `profiles.create` also gets the defaults and **mirrors the root home's authentication** (`mirrored.auth: true`).
   The host must always write an allow-list; without it an agent gets a shell and desktop control.
2. **The write-root covers only `write_file` and `patch`.** A `terminal` command `echo x > <outside the root>` wrote the
   file with **no approval prompt**. Hermes's own security page says the same. So the Research profile is safe only
   because `terminal` and `process_manage` are not in the toolset (verified: they disappear from the model's tool list).
3. **There is no read-root.** `read_file` read a file outside the task folder and so did the MCP `read_file`. Only
   credential paths and `.env` files are refused. The ADR-0072 rule "reads of the person's own files need an attached
   folder" has to be built in our MCP server or by never giving the agent a file-read tool outside the workspace.
4. **No taint rule.** Hermes wraps MCP results in `<untrusted_tool_result ...>` with "treat as data" text, which helps a
   model but does not change what tools may run next. Taint (ADR-0070 decision 5) remains ours to build.
5. **The approval mode is a config value** (`approvals.mode`) and the model cannot change it with a tool; the host writes
   `manual`. `allow_permanent` and `allow_session` appear in every approval request, so the host must never send
   `always` or `session` back (ADR-0072 decision 5).
6. **Extra model calls:** Hermes makes a second request per session to write a title (`session.title`). On a local model
   that is a small extra cost; to be disabled or accepted.
7. **Keyless web search and page extraction go to third parties.** With no keys, Hermes rotates `web_search` and
   `web_extract` across Exa, Parallel, Firecrawl and Keenable (its documentation; `web.keyless_fallback: false` turns it
   off, **not tested**). During the example task the process connected to GitHub, Cloudflare and Google Cloud addresses
   (I did not map which vendor). The start card of ADR-0072 must say that queries leave the computer even with a local
   model.
8. **First start of a new data folder builds a runtime.** Pointing Hermes at an empty `HERMES_HOME` (through its `hermes`
   wrapper or by importing it) made it build its own Python 3.14.7 environment with the full feature set: **379 MB of
   environment plus a 272 MB package cache, about 24 s**, downloading from the Python package index. See "Deviations".
   The component installer of ADR-0072 decision 2 must therefore pre-build that environment from the hashed lock
   (`uv.lock` has 3,486 hash entries; `pm/lock.json` pins engine components) and use **one** data folder per install
   with a **profile per task**, not one data folder per task.
9. **A 64,000-token minimum is enforced.** With `context_length: 32768` the session refused to start: "Model qwen3.5-9b has a
   context window of 32,768 tokens, which is below the minimum 64,000 required by Hermes Agent."

### Hermes's MCP client against the stub server

Stub: `~/Projects/wasifyai-spikes/g0/stub/stub_mcp.py`, the official `mcp` 2.0 SDK, stdio, tools `echo` and `read_file`
(restricted to one folder), every call logged.

| Check | Result |
|---|---|
| Add and test the server over the gateway (`mcp.servers.add`, `mcp.servers.test`) | `ok`, both tools listed |
| The agent sees and calls the tools | Offered as `mcp__stub__echo` and `mcp__stub__read_file`, plus wrappers `get_prompt`, `list_prompts`, `list_resources`, `read_resource`. The stub's log shows the calls with the arguments the scripted model sent |
| Result handling | Returned wrapped in `<untrusted_tool_result source="mcp__stub__echo">` |
| `trust: untrusted` on the server | An `approval` request "MCP tool 'echo' on UNTRUSTED server 'stub' wants to run" reached the host. Deny: the stub's log shows **no call**. This is the hook for ADR-0070/0072: our real server should be configured `untrusted` so every non-read-only action asks |
| **Tool Search bridge** | By default Hermes hides MCP tools behind `tool_search`, `tool_describe`, `tool_call` (three extra steps for the model). With a small model, set `tools.tool_search.enabled: "off"` so tools are listed directly (done in all runs) |
| Transport | stdio tested. Streamable HTTP and the 2026-07-28 stateless revision **not verified** |

## 2. Qwen3.5-9B with llama.cpp on this Mac

llama.cpp: Unsloth Studio's build, `llama-server` **build 11696, commit 3ea0620de** ("0.7.0-dev", Metal, arm64), already
on disk, used with the owner's yes. **The app's own llama.cpp is not installed on this Mac**, so the pinned build the app
will ship was **not** tested. Model: `unsloth/Qwen3.5-9B-GGUF` `Qwen3.5-9B-Q4_K_M.gguf`, 5,680,522,464 bytes, SHA-256
`03b74727...52b7e8` (matches the Hugging Face listing), Apache-2.0 (tag `general.license` read from the file's metadata,
`apache-2.0`), architecture `qwen35`, 32 blocks, trained context 262,144. Flags: `-ngl 99 --jinja -fa on -np 1`, f16 cache.
Load, prompt, speed and memory were taken one context size per fresh server, with the shared memory lock.

The architecture is hybrid: **only 8 of 32 layers use attention (every 4th)**, the rest keep a small recurrent state, so
the cache is small.

| Context set | Prompt sent | Read the prompt | Write | Time for the request | Memory: server process (RSS, peak) | GPU buffers (log) |
|---|---|---|---|---|---|---|
| 8,192 | 7,009 tokens | 1,080 tokens/s | 39.3 tokens/s | 7.3 s | 5.84 GB, 6.01 GB | not logged at this level |
| 32,768 | 30,022 tokens | 858 tokens/s | 37.4 tokens/s | 36.0 s | 6.68 GB, 6.90 GB | not logged at this level |
| **65,536** | **62,038 tokens** | **686 tokens/s** | **28.5 tokens/s** | 97.4 s | **7.71 GB, 8.01 GB** | **model 4,861 MiB + cache 2,048 MiB + state 50 MiB + compute 393 MiB = 7,352 MiB on the GPU, plus 546 MiB model on the CPU** |

- **Cache size.** Measured at 65,536: key-value cache **2,048 MiB** (f16, 8 layers; 1,024 MiB keys, 1,024 MiB values),
  recurrent state 50.25 MiB. At 8,192 and 32,768 the cache is **256 and 1,024 MiB by the same formula** (32 KiB per
  token); I did not read those two lines from a log, because the first runs used a quieter log level. The 262,144 trained
  context would need 8 GiB for the cache alone (computed, not run).
- **RSS** includes the memory-mapped model file, so it overstates what is private; the GPU figure from the log is the
  better one. In short: **about 8 GB for the model and a full 64k context.** Gemma 4 E4B was quoted at about 8 GB in
  ADR-0078 with a small context; the comparison at equal context was not measured.
- Other work was running on the Mac (three other spikes, Ollama idle, 10 GB of compressed memory), so free-memory
  figures in the raw JSON are noisy; the buffer sizes are not.
- Prompt reading slows as the prompt grows (1,080 to 686 tokens/s) and writing slows from 39 to 28.5 tokens/s at 62k.
  A 62k-token prompt takes about 90 s to read the first time; Hermes's cache hit rate in the example task was 63 to 87%,
  so later steps are cheaper.
- **Does it hold 64,000 tokens?** The server accepted a 62,038-token prompt and answered correctly. Hidden-fact test
  (`needle.py`, a passphrase inserted at 10% and 90% depth of a 62,056-token prompt): **2 of 2 exact**. Two probes are a
  smoke test, not an evaluation of long-context quality.
- **Does it think by default? Yes.** With no flag, 8 of the 10 tool cases produced reasoning text (127 to 413 characters), and
  the six cases that call a tool took 70 to 181 completion tokens; with thinking off, 26 to 64. Ways to turn it off, both verified: server
  `--reasoning off`; per request `"chat_template_kwargs": {"enable_thinking": false}` (used by the memory runs above,
  answers carried no reasoning). Through Hermes, thinking off was done at the server level; Hermes's own switch
  (`model_options.reasoning.enabled: false`, from its documentation) was **not tested**.
- **Tool calling, 10 small cases** (`tool_cases.py`: one string argument, numbers, right tool of several, no tool needed,
  enum, array, two parallel calls, using a tool result, missing information, an injection inside a tool result):
  **10 of 10 with thinking on; 10 of 10 with thinking off** (the script printed 9 of 10 for thinking off because its
  check for case 4 looked for the digit "4" and the model answered "Four"; I scored that case as correct by hand). Time
  per case: 0.2 to 1.9 s off, 0.6 to 4.8 s on. These are easy cases; they show the format works, not agent-grade
  reliability.

## 3. Hosted options (documentation and public listings only; no key was available)

`HF_TOKEN`, `GITHUB_TOKEN` and `GH_TOKEN` are not set in the environment, so no hosted model was called.

| | Finding | Source (read 2026-10-18) |
|---|---|---|
| **GitHub Models** | **Retired.** "As of July 30, 2026, GitHub Models is now retired. The playground, model catalog, inference API, and bring your own key (BYOK) are no longer available to any customer." The pages suggest Microsoft Foundry or GitHub Copilot instead. There are no limits to read | `github.blog/changelog/2026-07-30-github-models-is-now-retired/`, `docs.github.com/en/github-models` |
| **Hugging Face Inference Providers** | OpenAI-compatible endpoint `https://router.huggingface.co/v1`. The public model list (`/v1/models`, 134 models, no key needed) shows `Qwen/Qwen3.5-9B` on **Together** (context **262,144**, $0.17 input / $0.25 output per million tokens, tools yes), **OVHcloud** (262,144, $0.12 / $0.18, tools yes), **DeepInfra** (262,144, $0.10 / $0.15, tools yes), Featherless AI (no figures listed). So 64,000 tokens fit on every provider that lists a figure | `router.huggingface.co/v1/models` |
| HF billing | Free accounts have **no included credits** and must buy credits; PRO gets $2.00 a month; no markup on provider prices. Provider choice by suffix: `:fastest` (default), `:cheapest`, `:preferred`, or a provider name | `huggingface.co/docs/inference-providers/pricing`, `.../index` |
| HF rate limits | **Not found** in the documentation pages read; they are not stated per model or provider. **Not verified** | |

Cost of the example task at these prices (computed, not billed): the first local run sent 303,049 prompt tokens and
wrote 2,191 over 12 model calls. At the cheapest listed price that is about $0.03, at the dearest about $0.05. A hosted
run would use a larger model in practice, so this is a floor, not a forecast.

## 4. The task end to end

Goal given to Hermes, word for word: *"Explore GitHub for the top starred repo and make a report with what it does,
technologies and results. Save the report as report.md in the current folder."* Toolsets: `web, file, clarify, todo`.
No shell. Write-root: the task folder. Model: the local Qwen3.5-9B, 65,536 context. Approvals denied (none arose).

**Hosted run: not done** (no key in the environment). The three local runs are the same task, same configuration, run
one after another:

| Run | Thinking | Time | Model calls / tool calls | Prompt tokens (total) / written | Repository chosen | Correct? |
|---|---|---|---|---|---|---|
| 1 | off | 142.6 s | 12 / 11 | 303,049 / 2,191 | `codecrafters-io/build-your-own-x` | **Yes** for the repository |
| 2 | off | 121.2 s | 6 / 5 | 83,627 / 2,597 | four repositories (Bitcoin, Go-Ethereum, Tesseract, Animate.css), "Bitcoin Core, ~90,423 stars, most starred" | **No** |
| 3 | on | 70.9 s | 5 / 3 | 45,767 / 1,767 | `freeCodeCamp/freeCodeCamp`, "457K+ stars, the most starred" | **No** |

Ground truth, read from the GitHub API on 2026-10-18 (`search/repositories?q=stars:>100000&sort=stars`):
`codecrafters-io/build-your-own-x` **554,232** stars, `sindresorhus/awesome` 520,746, `public-apis/public-apis` 489,939,
`freeCodeCamp/freeCodeCamp` 457,392, `free-programming-books` 399,422.

**Run 1 transcript (steps in order):** `web_search "site:github.com most starred repos"`, `web_search "build-your-own-x
GitHub stars what it does technologies results"`, `web_search "codecrafters-io build-your-own-x technologies used stack
results metrics"`, `web_extract github.com/codecrafters-io/build-your-own-x`, four more searches about the company's
numbers, `read_file` of the saved page, `web_search` ("13x" growth), `web_extract codecrafters.io/blog/seed`,
`write_file report.md` (6,229 bytes). It asked no clarifying question (the plan's "all time, this week or one language?"
step did not happen unprompted; the host would have answered it). Raw frames: `logs/e2e_local_off.jsonl`; the report:
`work/e2e_local_off/report.md`.

**Checking run 1's report against sources.** Correct and verified: repository, 550,000+ stars (554,232), 51,000+ forks
(51,949), 143 contributors (GitHub contributors count), Markdown, created 9 May 2018, CC0 (the README says so; the API
reports no licence), $1.8M seed on 19 Nov 2024 and "13x more users completed our core stages" (both on
`codecrafters.io/blog/seed`, which is a company claim and the report presents it as fact). **Not confirmed:** "Y Combinator
Summer 2022", "143,000+ learners on the Go track", "405+ stages", "former GitHub/Vercel leaders" (not found on the page
the agent read). The "technologies" table lists categories of tutorials in the README, not technologies of the
repository (which is a Markdown list). **The report has no source list**: it ends "Data sources: GitHub rankings,
CodeCrafters blog, web searches", with no URLs or times, so it would fail ADR-0072 decision 10. The repository was
picked from a web search, never confirmed with a stars-sorted query; run 1 is right by the ranking luck of the search
results.

**Why runs 2 and 3 failed:** the model took whatever the first search returned as "the top starred repo", never ran a
sorted query, and in run 2 wrote star counts ("~90,423") that are far below any repository in the top ten. Thinking on
(run 3) was fastest and still wrong. Three runs show the failure is **tool and prompt design plus model care**, not the
protocol. A deterministic action ("GitHub repositories sorted by stars", an `untrusted`-marked read-only tool in our
MCP server) would remove the guess, and the report step needs a required "Sources" section checked by a rule.

## Deviations from the rules, and what I could not do

- **Unasked package download, inside the scratch folder.** My first Hermes command (`hermes config path` with a new
  `HERMES_HOME`) started Hermes's runtime builder; I stopped it after 1.1 MB (`~/Projects/wasifyai-spikes/g0/home`,
  left in place because the delete was blocked by a safety check). A later import of the code with another new
  `HERMES_HOME` (`home2`) ran the same builder to completion: **662 MB in the scratch folder, 272 MB of it downloaded
  Python packages**. The owner had approved reusing the existing install with no fresh download; this build was a side
  effect of Hermes's launcher that I did not foresee and did not ask about. Nothing outside the scratch folder changed. The owner may delete `~/Projects/wasifyai-spikes/g0/home` and `home2` when the
  spike is closed. (Hermes's Python 3.14.7 interpreter came from the owner's existing `~/.hermes/tools/`; on a clean
  Mac it would be downloaded as well.)
- **Not verified:** a hosted-model run; the 32 GB Mac; the app's own pinned llama.cpp; MLX; Windows and Linux;
  per-profile MCP servers; `web.keyless_fallback: false`; Hermes's own thinking switch; the learning features (skills
  and memory were left out of the toolset, so their defaults were not exercised); MCP over Streamable HTTP; how
  Hermes behaves with Hermes.app running at the same time.
- The 8,192 and 32,768 cache sizes are computed from the 64k log line (see section 2).
- No credential was typed, stored or printed. The HTTP API test used a throwaway random key held in the test
  process only.
- Model and downloaded files stay in `~/Projects/wasifyai-spikes/g0/models/` (5.7 GB).

## What this changes

1. **ADR-0072, "Hosted models, first providers"** names GitHub Models, which no longer exists. The hosted line is
   Hugging Face Inference Providers only (or another provider the owner names). The G0 question "do GitHub Models'
   free limits allow 64,000 tokens" is closed: moot.
2. **ADR-0072 decision 3** can name its path: TUI gateway, one process per task, profile per task; ACP as fallback.
3. **ADR-0072 decision 2** (installed from a pinned, hashed lock): confirmed necessary, because Hermes builds its own
   environment on first start and downloads packages; the installer has to do that step ahead of time, offline-safe.
4. **ADR-0072 decision 4** (profiles): the Research profile holds only because the host allow-lists toolsets and leaves
   out `terminal`; the write-root is not a sandbox. Reads are unrestricted, so file reading must come only through our
   MCP server and the attached-folder rule.
5. **ADR-0078** open question 1 is answered for this Mac: 64k fits in about 8 GB. Its memory statement (minimum RAM) still
   needs a 16 and 32 GB measurement.

## Table: what works

| Item | Works? | Evidence |
|---|---|---|
| TUI gateway: start, session with folder | Yes | `logs/gw_basic.jsonl` |
| TUI gateway: toolsets by profile config | Yes | `logs/profile.jsonl`, `logs/fake_llm.jsonl` |
| TUI gateway: write-root by environment | Yes (writes only) | `logs/run_WRITE.jsonl`, `logs/run_TERMWRITE.jsonl` |
| TUI gateway: approvals answered by host | Yes | `logs/run_APPROVE.jsonl` |
| TUI gateway: stop | Yes, 0.15 s | `logs/run_stop.jsonl` |
| ACP: folder, MCP per session, approvals, cancel | Yes | `logs/acp_APPROVE.jsonl`, `logs/acp_SLEEP.jsonl` |
| HTTP API: events, approval, stop | Yes; no per-run folder or toolset | `logs/api_gateway.log` |
| Hermes MCP client with stub | Yes (stdio) | `stub/calls.log` |
| `trust: untrusted` approval on MCP writes | Yes | `logs/run_ECHO.jsonl` |
| Qwen3.5-9B holds 64k | Yes | `logs/bench_64k.json`, `logs/needle.json` |
| Thinking off | Yes, two ways | `logs/bench_*.json`, `logs/tools_*.json` |
| Tool calling, 10 cases | 10 of 10 | `logs/tools_default.json`, `logs/tools_off.json` |
| GitHub Models | No (retired) | GitHub changelog |
| Hosted task run | Not done | no key |
| Example task, local, correct repository | 1 of 3 | `logs/e2e_*_summary.json` |

## Table: the numbers

| Measure | Value |
|---|---|
| Hermes gateway start / idle memory | 1.1 to 1.7 s / 309 MB |
| Hermes first-start runtime build (new data folder) | 24 s, 379 MB environment + 272 MB downloaded packages |
| Stop latency, running command | 0.15 s |
| Qwen3.5-9B Q4_K_M file | 5.68 GB |
| Memory at 64k (GPU buffers) | 7.35 GB (+0.55 GB on the CPU); cache 2,048 MiB |
| Memory at 8k / 32k (process RSS) | 5.84 GB / 6.68 GB |
| Prompt reading 8k / 32k / 62k | 1,080 / 858 / 686 tokens/s |
| Writing 8k / 32k / 62k | 39.3 / 37.4 / 28.5 tokens/s |
| Tool cases | 10 of 10 (both thinking modes) |
| Example task, local | 71 to 143 s; 45,767 to 303,049 prompt tokens; 1,767 to 2,597 written; correct repository in 1 of 3 |
| Cheapest hosted Qwen3.5-9B on Hugging Face | $0.10 in / $0.15 out per million tokens, 262,144 context |

## Recommended control path

**TUI gateway over stdio, one `tui_gateway.entry` process per task**, launched by the engine with: one shared Hermes data
folder from the pre-built component; `HERMES_WRITE_SAFE_ROOT=<task workspace>`; a **profile per task** whose toolsets
are written by the engine (Research: `web, file, clarify, todo`; never `terminal`, `process_manage`, `code_execution`,
`browser`, `computer_use`, `cronjob`, `memory`, `skills`, `delegation`); `approvals.mode: manual`;
`tools.tool_search.enabled: off`; our MCP server added with `trust: untrusted`; `web.keyless_fallback` decided by the
owner; the host calls `client.capabilities {server_requests: true}`, answers `approval` and `clarify`, and uses
`session.interrupt` for Stop. Keep the `AgentEngine` interface of ADR-0072; nothing found requires the native fallback.

## Go or no-go for stage G1

**Go**, on these conditions:

1. G1's acceptance run uses a **hosted model** (Hugging Face), as ADR-0072 already says; the local 9B stays "limited" for
   agents until G3 shows otherwise (1 of 3 on the example task). The owner decides whether to supply a Hugging Face key
   so this spike's hosted run can be done before G1 starts.
2. Before G1, change ADR-0072's hosted-provider line (GitHub Models is retired).
3. G1 includes a deterministic "repositories sorted by stars" read action and a mandatory sources section in reports,
   because the free web search alone found the right repository once in three tries.
4. The installer builds Hermes's environment ahead of time from the hashed lock; no first-run downloads.
5. Memory for the local path is shown on the Models page as "about 8 GB for 64k context"; a 16 and 32 GB measurement is
   still needed before ADR-0078's minimum-RAM line is written.
