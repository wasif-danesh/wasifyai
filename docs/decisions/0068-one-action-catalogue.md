# ADR-0068: One action catalogue: everything the product can do, described once

- **Status:** Accepted (2026-10-18, by the owner), together with the new dependencies it names.
- **Date:** 2026-10-18
- **Depends on:** ADR-0010 (capability-based configuration), ADR-0047 (safeguards), ADR-0056 (one engine, two
  shells; one memory slot), ADR-0057 (the assistant; tools are explicit, reviewed), ADR-0066 (the voice
  product), ADR-0041 (everything made is searchable).
- **Needed by:** ADR-0069 (MCP server), ADR-0070 (MCP client), ADR-0071 (assistant that knows the product).
- **Plan:** `docs/phase4-agent-plan.md`.

## Context

Three requests of 2026-10-18 look separate and are one problem seen from three sides:

1. Claude Code, Codex and OpenCode should be able to use everything the app can do, through an MCP server.
2. The app should use other people's MCP servers.
3. The in-app assistant should know the product, explain how to use it, and run it when asked.

Today what the app can do is described in **four places that drift apart**: the screens (`packages/ui`, the
menu), the API routes of each product, the assistant's four hand-written tools (`wasifyai_assistant/tools.py`:
`generate_image`, `make_music`, `search_creations`, `search_notebooks`) and the docs. Adding the MCP server and a
better assistant on top would make it six. Each copy would need its own idea of what is safe, what costs time, what
needs a person's word (voice cloning, lip sync: ADR-0044, ADR-0066), what needs a model that may not be installed,
and what to say when it is not.

What exists and is reusable:

- Every product is a graph the engine can run as a **child run** (`ToolHost.run_product`, ADR-0057), with its own
  events, safeguards, quotas and queue, saved to the same library.
- Model readiness is already computed (`AudioEngine.models()`, `ModelsService`): `ready`, `needs_runtime`,
  `can_install`.
- Requests are already **checked before work starts** (`check_speak`, `check_music`, `check_lipsync` ...), with
  sentences meant for a person.
- The search index knows every kind of creation (ADR-0041).

## Decision

1. **One catalogue of actions** in the platform SDK (`wasifyai_platform_sdk.actions`). An action is something a
   person or an agent can ask the product to do. It is data, not code, plus a binding to the code that runs it.

   | Field | Meaning |
   |---|---|
   | `id` | stable, `domain.verb` (`speech.speak`, `image.generate`, `library.search`) |
   | `title`, `summary` | for people, in English (v1 is English only) |
   | `description` | for a model: when to use it, when not to, what it returns |
   | `input` | a JSON Schema (2020-12), derived from a Pydantic model, with `examples` |
   | `output` | a JSON Schema for the small structured result (ids, kinds, seconds, file references; never bytes) |
   | `effect` | `read` (changes nothing), `make` (adds to the library, spends time or compute), `change` (edits or renames what exists), `destroy` (deletes) |
   | `flags` | any of `costly` (hosted provider, minutes of compute), `leaves_device` (text or audio goes to a third party), `needs_consent` (a person's word is required: ADR-0044, ADR-0066), `private` (reads the person's own library or notebooks) |
   | `requires` | what must be ready: a model task (`speak`), a runtime, a notebook; resolved at run time to `ready`, `needs_setup` (with the step that fixes it) or `unavailable` (with the reason) |
   | `long` | whether it can run longer than a few seconds, so it is a job with a handle |
   | `bind` | the child run of a product graph with how to build its input, or a direct function |
   | `ui` | the screen and menu item that does the same thing (`voice.speak`), so an answer can say "open Text to speech" and a card can open it |
   | `help` | a Markdown file under `docs/help/<id>.md` (steps, limits, troubleshooting), the source of the assistant's knowledge (ADR-0071) |
   | `surfaces` | an explicit allow-list: any of `assistant`, `mcp`. Nothing appears on a surface by accident (ADR-0057 decision 2 stays) |

2. **One executor.** `run_action(action_id, params, origin)` is the only way a non-window surface does anything.
   It validates `params` against the schema and the product's own `check_*`; resolves `requires`; applies the
   safeguards and quotas (ADR-0047) through the product graph it runs; decides whether a person must approve
   (decision 4); runs the child run; records usage and an **audit entry** (who, which action, which surface, how it
   ended, no content); and returns an `ActionResult` (`ok`, `refused`, `needs_setup`, `needs_approval`,
   `running` with a `job_id`, `error`) with a sentence for the model and a small structured output.
   `origin` is `window`, `assistant`, or `mcp:<connection>`; usage events and creations carry it.
3. **Jobs have handles.** A long action returns `{job_id, status}` at once; `job.status`, `job.wait` (bounded) and
   `job.cancel` are actions too. This is what keeps MCP clients with 60-second tool timeouts and a local model
   with a 4,000-token context workable (ADR-0069, ADR-0071).
4. **Approval is a property of the action, not of the surface.** Default rule, overridable per connection or
   conversation but never past the floor below: `read` runs; `make` runs after the setting the person chose
   (ask first, ask when `costly` or `leaves_device`, or never); `change` asks; `destroy` always asks; `needs_consent`
   always asks and shows the same consent statement the screen shows. **Floor:** `destroy` and `needs_consent`
   cannot be set to run without a person, from any surface. The approval is shown **in the app window**, so an
   agent cannot approve for itself (ADR-0069).
5. **Results are references.** An action returns library ids, `wasify://creation/<id>` URIs and sizes. A file leaves
   the library only through `library.export` to a folder the person allowed (ADR-0069). This is the contract of the
   existing `tool_result` event, kept.
6. **Everything derived.** The registry generates, from the catalogue and nothing else: the assistant's tool
   arguments (ADR-0071), MCP tools with annotations (ADR-0069), the help corpus (ADR-0071), a JSON export
   `docs/contracts/actions.json` that tests and docs read, and (later) form fields for a card. A test fails when a
   screen with a menu item has no action or an action's `ui` points at a screen that does not exist.
7. **The first set** (v1, desktop): `library.*` (search, list, get, export, rename, delete), `image.*` (generate,
   edit), `video.*` (generate, animate), `speech.*` (speak, transcribe), `voice.*` (list, design, clone,
   convert, edit_speech), `music.*` (generate, lyrics, separate), `dub.*`, `audiobook.*`, `lipsync.*`,
   `notebook.*` (list, create, add_source, ask, studio_output), `models.*` (list, status; downloading a model is
   `needs_consent`-like: it shows its size and waits for a yes), `app.status`, `job.*`. About 40 actions. Settings,
   account and anything that changes the person's configuration are **not** actions.
8. **Where it lives.** The catalogue and executor are Apache-2.0 platform code (`packages/platform-sdk`, with the
   engine-side binding in `services/api`). Products declare their actions next to their graphs (a `actions.py` per
   product, registered like routes and index sources), so a product without actions is not exposed. The desktop
   and the future web deployment share them; what a deployment cannot run resolves to `unavailable`.

## Consequences

- The four existing assistant tools become actions; the assistant's evaluation (11 of 11 with Qwen3 4B) is the
  regression test for the move.
- A new feature is not done until it has its action, help file and `ui` pointer, the same way ADR-0041 makes
  "searchable" part of done. CLAUDE.md gets one line for it when this ADR is accepted.
- One place to review for safety: a reviewer reads the catalogue to see everything an agent can do.
- The executor becomes a choke point (good for audit and limits) and a dependency of three surfaces (so it is
  built and tested first, before any of them).

## Alternatives considered

- **Generate tools from the OpenAPI routes.** About 140 routes, no notion of effect, consent or readiness, and
  route shapes serve the window, not a model. Rejected: it would publish internals.
- **Let each surface describe its own tools.** What happens today. Rejected: the drift is the problem.
- **A DSL or a separate spec file format.** Pydantic models already give schemas and validation, and the checks
  already exist in code. Rejected as more to learn for no gain.
- **Expose every product graph as an action automatically.** Rejected: ADR-0057 chose reviewed, explicit tools,
  and some graphs (the tests' graphs, the moderator canaries) must never be callable.

## Open questions

1. Whether `ui` can drive the window (open a screen with the fields filled in) or only name the screen. Needs the
   desktop router to accept parameters (`#/voice/speak?text=...`); small, but a window change.
2. How an action names a **file input** that is not in the library (transcribe a recording the agent has on disk):
   a path under an allowed folder (ADR-0069 decision 6) or an upload through the window. Decided in the spike S2.
3. Whether the catalogue is also the source of the **menu** (`MENU_GROUPS`). Tempting; deferred so the menu keeps
   its own order and grouping.

## Not in this version

Scheduling and chains of actions ("make a song then a lip sync"): an agent chains calls itself; a built-in
workflow engine is a later decision. Per-person custom actions. Actions for the web deployment's hosted-only
features beyond what resolves to `unavailable`.
