# The action catalogue: how to add an action

ADR-0068. Everything the product can do for a person or an agent is described once, as an **action**, and
run by one **executor**. The assistant's tools (ADR-0071) and the MCP tools (ADR-0069) are read from it; nothing
is exposed that is not in it. `docs/contracts/actions.json` is the catalogue as one file, so a reviewer can read
everything an agent can do in one place. Stage A1 (this document) built the catalogue and executor and moved the
assistant's tools onto it; stage A2 (2026-10-27) gave the assistant its meta-tools, so any action a product
declares can be proposed in the chat and run from its card (ADR-0071).

## What is where

| Piece | Where |
|---|---|
| `Action`, `ActionRegistry`, `ActionExecutor`, `ActionResult`, approvals policy, audit and approval stores, job handles | `packages/platform-sdk/src/wasifyai_platform_sdk/actions/` |
| `library.*`, `app.status`, `job.*` (they belong to no product) | `actions/builtin.py` |
| `models.*` (the desktop's model library), the catalogue of this engine, the export | `services/api/src/wasifyai_api/actions_engine.py` |
| `image.*`, `video.*`, `speech.*`, `voice.*`, `music.*`, `dub.*`, `audiobook.*`, `lipsync.*`, `notebook.*` | `actions.py` of the product that owns them |
| The engine's side (readiness, stores, child runs) | `ApiToolHost` in `services/api/src/wasifyai_api/tool_host.py` |
| Help for each action | `docs/help/<action id>.md` |
| The assistant's list of screens (interim, ADR-0071) | `wasifyai_api/assistant_features.py` writes `products/wasifyai-assistant/wasifyai_assistant/features.json`; rerun `--write` after a menu or action change |
| Audit and approvals tables | Postgres: Alembic `0020_actions`; desktop: created on first use by `SqlAuditStore` and `SqlApprovalStore` |

## Adding an action (one file, plus its help)

1. In the product that owns it, add an `Action` to `actions()` in `actions.py`. It needs:
   - `id` as `domain.verb`, a `title`, a one-line `summary`, and a `description` written for a model (when to use
     it, when not to, what it returns);
   - `input` and `output` Pydantic models (extra fields forbidden for input) and at least one entry in `examples`;
   - `effect`: `read` (changes nothing), `make` (adds to the library, spends time or compute), `change` (edits
     what exists) or `destroy` (deletes);
   - `flags`: `costly`, `leaves_device`, `private` (reads the person's own library or notebooks) and
     `needs_consent` (then `consent` carries the statement the person agrees to);
   - `requires`: what must be ready (`need_product`, `need_model`, `need_runtime`, `NOTEBOOKS`, `CHAT`);
   - `long=True` if it can take more than a few seconds (it can then be a job with a handle);
   - `bind`: a `RunBinding` (a child run of the product's graph: its checks, safeguards, quotas and queue are
     the screens' own) or a `CallBinding` (a direct function on the product's store);
   - `ui`: the menu item that does the same thing (`voice.speak`), or `ui_exempt` with the reason there is none;
   - `surfaces`: where it may be offered, `assistant` and/or `mcp`. Nothing appears on a surface by accident.
2. Register it once: `registry.add_actions(PRODUCT_ID, actions)` in the product's `register()`. A product
   that is not served exposes nothing. A product that keeps something the person made also declares a
   `LibraryKind` with `registry.add_library_kinds(...)`, so the `library.*` actions reach it.
3. Write `docs/help/<id>.md` (copy a neighbour: front matter with `action`, `screen` and `synonyms`; sections
   What it is for, Steps in the app, Fields, Limits, Needs, Examples, Problems). A menu path is written in bold
   with ` › `, for example **Voice › Text to speech**; a test checks it against the shipped menu.
4. Add a test next to the product's other tests that runs the action through `ActionExecutor` (copy
   `products/wasifyai-image/tests/test_image_actions.py`). `FakeActionHost` in
   `wasifyai_platform_sdk.actions.testing` scripts child runs and readiness.
5. Regenerate the export and commit it: `uv run python -m wasifyai_api.actions_engine --write`
   (`make contracts` does it too). A test fails when `docs/contracts/actions.json` is out of date.

`services/api/tests/test_actions_catalogue.py` then checks, for every action, that it has help, a real menu item
or an exemption, valid examples, the floor below, and that the export is current. A new product (Phase 5: `train.*`,
`video_builder.*`, `motion.*`, `model3d.*`, `decision.decide` and the agent actions) adds its `actions.py`, its help
files and its registration line and changes nothing else.

## How a call is run

`ActionExecutor.run_action(action_id, params, origin, ...)` is the only way a surface other than the window does
anything. `origin` is `window`, `assistant`, `mcp:<connection>` or `api:<key id>`. `actor` may be an `Identity` (the
person) or a `Principal` (ADR-0092: a connection or an API key with scopes; it acts as the person who made it). In
order it:

1. finds the action and checks that the surface may be offered it (`not_offered`), and that the principal's scopes
   cover it (`not_offered`, with the missing scope in the sentence; `scope_of(action)`: the domain's group for
   `library`, `notebook`, `voice` and `models`, else `read` for a read and `make` for the rest);
2. validates `params` against the input model and answers in words what to fix (`invalid_input`);
3. resolves `requires`: `needs_setup` (with the step that fixes it and the screen) or `refused` with code
   `unavailable` (with the reason);
4. runs the product's own check (the `check_*` sentences) before anything is loaded;
5. decides whether a person must approve, from the action and the caller's `ApprovalPolicy`;
6. runs the child run or the function, and checks that a good answer matches the documented `output`;
7. writes one **audit entry** (who asked, which action, how it ended, how long; no content) and one `action.run`
   **usage event**, and returns an `ActionResult`.

`ActionResult.status` is `ok`, `refused`, `needs_setup`, `needs_approval`, `running` (with a `job_id`) or `error`.
A call never raises.

### Approvals

| Effect | Default |
|---|---|
| `read` | runs |
| `make` | the caller's setting: `ask` (the default), `ask_costly` (ask when `costly` or `leaves_device`) or `auto` |
| `change` | asks (a setting may make it `auto`) |
| `destroy` | **always asks** |
| `needs_consent` | **always asks**, and the statement is part of the question |

The floor is not a field of `ApprovalPolicy`: `ApprovalPolicy(destroy="auto")` is an error, and
`ApprovalPolicy.from_settings` refuses it in words. An action that has to ask stores a pending approval (the exact
parameters, hashed) and answers `needs_approval` with an `approval_id`. The window answers it
(`executor.decide_approval(...)`: no action exposes it, so an agent cannot approve for itself) and the caller
retries with `approval_id=...`; an approval is for exactly those parameters, works once, and drops the stored
parameters when decided. `person_approved=True` exists for the window only, for its own click.

### Jobs

A `long` action called with `wait_seconds` waits at most that long (never more than 50) and then answers
`running` with a `job_id`. `job.status`, `job.wait` and `job.cancel` follow it. A job that is a direct function
can be stopped; a child run of a product graph cannot once it started (the engine has no way to stop a run), and
`job.cancel` says so. The job book is in memory; after a restart `job.status` answers from the audit log how the job
ended.

## Results are references

An action returns ids, `wasify://creation/<kind>/<id>` URIs, sizes and a sentence, never bytes. A file leaves the
library only through `library.export`, into the export folder.

## Not actions

Settings, account and anything that changes the person's configuration. Downloading a model is an action
(`models.download`) because it shows its size and waits for a yes.

**Dictation** (the Mic in the chat box, `POST /products/wasifyai-voice/dictation`, ADR-0083) is not an action: it is the person's own
voice, recorded by the window while they press the button, and it returns text to the box and nothing else (no creation, no library
row, no audit of the words). There is nothing for an agent to call; writing down a recording that is in the library is
`speech.transcribe`.

**Read aloud** (the speaker button under a reply, `POST /products/wasifyai-voice/read-aloud`, ADR-0083) is not an action either: it speaks the text of
a reply the person is looking at, only when they press the button, and returns sound to the window and nothing else (no creation, no library row,
no audit of the words). Making a speech that is kept in the library is `speech.speak`.
