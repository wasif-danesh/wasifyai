# Coding agent, stage C1b: a session that only reads (the engine side)

Written 2026-11-14 on the owner's Mac (M5 Pro, macOS 27.0). The stage is piece 4 of
`docs/v2-coding-agent-start-plan.md`, section 9. **Only the engine side is built: there is no screen.** The
mockups (`docs/spikes/coding-mockups.html`) wait for the owner's approval, and the stream to the window waits
for the owner's yes to the new event kinds proposed below. What is built is described in
`docs/desktop/coding.md`.

## The gate

The owner allowed the fetch of the 12 missing packages on 2026-11-14 ("Yes, fetch them"). The coding engine
was then set up by the app's own installer in a throwaway data folder
(`~/Library/Application Support/ai.wasifyai.coding-c1b`), from the hashed lock, and answers as 1.62.0.
The gate was measured with `docs/spikes/coding-c1b-gate.py`: the desktop engine started as the shell starts
it, a token signed as the window's is, and only the coding product's routes.

| Gate (section 9, piece 4) | Result | How it was measured |
|---|---|---|
| "Analyse this codebase" gives a correct map of three real projects, on the local Qwen 27B (Ollama) | **Not passed: 1 of 3.** `ScreenshotOrganiser`: a correct map in 247 s and 26 steps. `openhands-integration` and `kinofold`: no answer after 15 minutes (85 and 120 steps), stopped by the measuring script | The routes; the one answer checked against the project by hand (the two modules, the eight Kotlin files, the template code, the placeholder tests: all as it said) |
| The same on Claude Sonnet 5.5 (the first model) | **Passed: 3 of 3.** `ScreenshotOrganiser` 53 s, 29 steps, $0.20; `openhands-integration` 56 s, 26 steps, $0.25; `kinofold` 50 s, 29 steps, $0.22. Each answer says what it read and what it did not, and what was not run | The routes, the key read by the engine from the app's own secret store (the owner's yes, 2026-11-14, limit $2). Checked by hand: modules, file names and roles, versions, the pinned servers, what is template code |
| Nothing is written anywhere | **Passed.** No file of the three projects differed (2,100, 1,610 and 137 entries listed before and after: path, size, time of last change, mode) | The gate script; and on the real server `make test-coding`: a write is refused by the tool, by the plan file's folder and by the sandbox |
| Stop works within one second at any moment | **Passed.** Stop after 0, 0.5, 2, 5 and 10 seconds of a turn: 0.002, 0.016, 0.016, 0.016 and 0.015 s until the stop route answered with the turn closed | The gate script. With a scripted model that was being waited for: under 1 s (`make test-coding`) |
| The key is found nowhere inside the sandbox | **Passed.** With a stand-in key: it reached the scripted provider and was in no file the engine wrote, its log or its environment. After the runs with the real key: 2,149 files searched in what the coding engine can write and in its log, none with anything shaped like a provider's key. The key was never printed, logged or written by this work | `make test-coding`; the gate script, which searches by shape and never reads the key |
| `make test-coding` | **39 passed** (30 hostile tests of C1a, 9 new: the contract, the tools offered, three ways a write is refused, a refusal, the step limit, Stop, streaming, the count and the key) | The real server in its sandbox, a scripted model, the real gateway |
| `make test`, `make lint` | **Passed** on the final tree: ruff, the format check, pyright (0 errors), Biome and the TypeScript check; 3,632 Python tests passed and 482 skipped (the skipped ones need services or are opt-in); 108 desktop, 178 client, 220 web and 744 screen tests passed. Nothing was left in `/tmp` | The same commands as the two make targets, with packages from the local caches |

**Counted cost on Claude Sonnet 5.5: $0.66** (three analyses, $0.197, $0.249 and $0.216; three turns that
failed at once before the fix below cost $0.0014 together). About 1.15 million input tokens in all, most
of them read from the prompt cache, and 19,000 output tokens. No evaluation and no other run was made on the
paid model.

**The evaluation on the local model** (`run_eval.py --data`, the real place, Qwen 27B through Ollama, the
gateway on a port of its own): **34 of 36** in 51 minutes; `hard-kv-store` and `hard-cli` failed their hidden
checks. The C0 spike had 33 of 36.

**About the local model's two misses.** Both turns were still reading files when the 15 minutes ended; neither
failed. The model is given 24,000 tokens of input (the C0 spikes' setting), and the Agent Server's own
instructions take about 10,300 of them, so on a larger project it reads, forgets and reads again. Whether a
larger window or a tighter request fixes it was not tried. The step count went past the session's limit of
60 because the limit counts the model's turns and one turn can use several tools.

**Still by hand in the tree:** `tests/fixtures/coding/engine-error.json` (an error of the engine could not be
made to order); the other four streams are recordings from the real server with a scripted model. The types
(`agent_types.py`) are now generated from the running server's API description.

## What is built

| Piece | Where | Tests in `make test` |
|---|---|---|
| The place "this computer": the only file that knows the Agent Server's API | `products/wasifyai-code/wasifyai_code/client.py` | `services/api/tests/test_coding_sessions.py` (22) |
| The Agent Server's events in the place's own words, and how a turn ended | `wasifyai_code/events.py`; the shapes in `agent_types.py`, generated by `scripts/coding-engine-types.py` from `services/coding-engine/api-excerpt.json` | `products/wasifyai-code/tests/test_code_events.py` (11) |
| The model gateway | `services/api/src/wasifyai_api/coding_gateway.py`, `coding_models.yaml` | `services/api/tests/test_coding_gateway.py` (21) |
| A session that only reads | `client.py` (three tools), `coding_server.py` (workspaces opened for reading only; a plan file the server cannot write) | `test_coding_sessions.py`, and on the real server `make test-coding` |
| The product wired in | `wasifyai_code/__init__.py` (entry point), `runtime.py`, `actions.py`, `routes.py`, `index.py`; the store opened in `assemble.py`; `docs/help/code.session.*.md`; `docs/contracts/actions.json` | `products/wasifyai-code/tests/test_code_sessions.py` (18), `test_actions_catalogue.py` |
| The fake Agent Server replays recorded streams | `services/api/tests/fake_agent_server.py`, `tests/fixtures/coding/*.json` | every test above that names a session |
| The evaluation on the real place | `products/wasifyai-code/evals/run_eval.py --data ...` | `tests/test_evals.py` (the pretended place) |

## Decided

`docs/spikes/coding-c1a.md` left three points for this stage. Each is what the code does now.

**1. One server for several sessions with different workspaces: one profile that names all of them.**
The server is started with every folder the person has opened as a workspace (every row of `workspaces`), so
a session on a known folder starts nothing and disturbs nobody. Only a folder that is new makes the server
start again, because a sandbox profile cannot change while its process runs. That start is refused, in
words, while any session is in the middle of a turn ("The coding engine must start again to open this
folder, and another session is in the middle of a turn"). Starting again for every change of session was
rejected: it would cut off whoever was working.

Each workspace is opened for reading only, unless a session that may write is on it. In this stage no
session may write, so every workspace is read-only for the whole server. When a mode that edits arrives
(C2), a folder moving from "read" to "write" is one more start of the server, under the same rule.

**2. The routes `/desktop/coding-engine/start` and `/stop`: `start` is removed, `stop` and the status stay.**
A start from outside has no folders to give. With the product starting the server, a second start with other
folders would start the server again and cut off every session in the middle of its turn, so a route that
does that should not exist. `stop` stays: it gives 370 MB of memory back, it first ends the turns in flight
as "stopped", and the next message of a session starts the server again. The status route stays for
diagnostics. No screen used any of the three.

**3. How the coding product's own connection to Wasify's tools reaches the server now that `engine.json` is
closed to it: through the session's settings, by the same hand-over as the model.** Not built (it is C4);
this is the decision for it. The launcher's file holds the engine's port and the secret of the connection
made for outside apps, and it stays closed. Instead, when a session is made, the Wasify engine makes a
short-lived token for a connection that belongs to the coding product (its own row in the connections
list, its own scopes, a short fixed set of tools) and gives the Agent Server the tool server's address on
loopback and that token in the session's `mcp_config`, exactly as the gateway's address and the model token
are given in its `llm` settings today. Nothing is written to a file the sandbox can read, the token dies
with the session, and an approval the session causes is known to belong to it. The Agent Server keeps a
session's settings in its own state folder, which is inside the sandbox: that is acceptable for a token
that opens one session's tools and nothing else, and it is why it must never be the launcher's secret.

Other points settled on the way:

4. **Action ids have three parts** (`code.session.start`). The catalogue's rule was `domain.verb` (ADR-0068,
   decision 1); the plan and ADR-0104 name the coding actions with three parts (`code.extension.*`). The
   rule in `actions/model.py` now takes `domain.verb` or `domain.thing.verb`, and `docs/actions.md` says so.
   **For the owner:** if two parts must stay, the three ids become `code.start`, `code.send`, `code.stop`.
5. **The three actions are offered to the assistant, not to outside apps.** An outside app that could open
   a session on any folder would be handed that folder's content. The owner may want them on the MCP
   server later, behind its approvals.
6. **Which key.** A coding session uses the key saved for Chat and writing (`keys.chat.anthropic`). A row of
   its own in Settings › Your keys is a screen change and was left for the screens.
7. **The local model is offered only when its address is set** (`CODING_OLLAMA_URL`). It is there for the
   gates' second run. On the desktop the app has no Ollama of its own; the model picker that exists
   (llama.cpp) takes the list over with the screens.
8. **A turn that only reads changes no word and takes no checkpoint.** The session's result stays what it
   was, the turn's `why` says how it ended (finished, stopped, step_limit, error, refused). The loop of
   `loop.py` is not used until a mode can change files.
9. **Which folders can be a workspace** (`runtime.check_folder`): one project's folder. Refused: the home
   folder and anything above it, the app's own data folder (and anything that holds it or is inside it),
   the Library, and hidden folders at the top of the home folder. The sandbox opens a workspace to the
   engine, so opening one of these would undo what the sandbox is for.
10. **A session after the app was closed and opened again starts a new conversation with the agent.** Its
    gateway token lived in memory. The turn says so in a note. Giving a kept conversation a new token is
    not built.
11. **Search.** A session is indexed as kind `code_session` by its title, its project's name and what was
    asked first; `CreationKind` has the new kind and the evaluation corpus has a row. The card and the
    filter in the Library come with the screens. A session is not a library kind (`library.delete` does not
    reach it); its own route deletes it and takes it out of search.
12. **The store's new columns** (`sessions.mode`, the cost and token counts, `turns.answer`, `turns.steps`)
    were added to the table definitions in place. No app has ever opened this store, so there is nothing to
    migrate; from now on a change needs a migration step.

## The stream's event kinds: agreed

Proposed here and agreed by the owner on 2026-11-14 ("Reuse existing kinds"): four kinds of the contract are
reused (`tool_call`, `tool_result`, `token`, `reasoning`) and three are new (`code_state`, `code_message`,
`code_refusal`). The fields are in `docs/contracts/sse-events.md`, "A coding session's stream", and the decision
is an amendment to ADR-0101. **Nothing is sent to the window yet**: the route that streams, and the Pydantic
models of the three new kinds, come with the session view. The relay inside the engine (`runtime.Feed`) still
uses its own names (`code_step`, `code_piece`, `code_text`); the route will map them to the agreed kinds.

## Found on the way

0. **The provider compressed its streamed answer, and the gateway passed the compressed bytes on as plain.**
   The Agent Server then saw empty answers and ended each turn as "stuck" within seconds. It showed only on
   the real provider: the pretended one and Ollama do not compress. The gateway now asks for an
   uncompressed answer, and a test holds that. It also writes the provider's own words to the log when the
   provider answers with an error (never the request, never a key).

1. **A Stop that arrives while the coding engine is starting cut the start in half.** The supervisor's
   start was cancelled between making its terminal folder in `/tmp` and recording it, and the folder was
   left behind. The place now lets a start run to its end whatever happens to the turn that asked for it.
   The supervisor itself is unchanged; a caller that cancels `ensure_running` directly can still do this.
2. **A Stop that arrives after the session is made and before the message is sent** was followed by the
   message, and the agent ran with nobody stopping it. The turn now looks at Stop again just before and
   just after it sends.
3. **Words as they are written are sent only to who is listening at that moment** (the Agent Server does not
   keep them). A turn therefore opens its socket first and sends its message when the socket listens.
4. **Closing a socket waits for the other side to say goodbye**, ten seconds by default in the library
   used. It is one second here, so a Stop is not held up by a server that is slow to answer.
5. **A route model's name is part of the API description.** Two products with a model called `StartIn` make
   the description rename both, which changes generated TypeScript names. The coding routes' models have
   names of their own.

## Not measured, not built

- The local model on the two larger projects with other settings (a larger window, a tighter request).
- Stop while Claude Sonnet 5.5 is being waited for (measured on the local model and with a scripted model).
- A refusal by the real model: the gateway's handling was shown with a scripted provider only.
- Whether the Agent Server keeps a conversation across its own restart (a new workspace while sessions exist).
- The evaluation on Claude Sonnet 5.5 (not allowed for this stage).
- No screen, no stream to the window, no Library card for a session.
- Windows, Linux and Intel Macs.

## The first screens (2026-11-14, after the mockups were approved)

Built on branch `coding-c1b-screens`: the stream route in the agreed kinds, the window's client, the menu
group Code, Projects, and the session view in Plan (`docs/desktop/coding.md`, "The screens").

| | Result |
|---|---|
| A real walk in a browser, the window's own code against the real engine, the real coding engine and the local Qwen 27B | **Worked.** First screen, a folder chosen in the folder window (stood in for by the walk), a question asked, the agent's five steps, its answer and "Nothing was changed" after 37 s, then the projects list. Pictures: `docs/ui-audit/desktop/code-*.png` |
| The Tauri window itself | **Not seen.** The walk runs the window's code in a browser with a stand-in for the shell, so the real folder window was not opened |
| Tests | 11 screen tests (`packages/ui/src/code/code.test.tsx`), 2 for the stream route; every event the product makes is held to the contract's models |

**The Files tab** was added the same day: a folder at a time, a file to read with line numbers, nothing to
change it (2 more screen tests, 3 for its routes: listing, a file that is not text, a long file cut, and
nothing outside the project reachable by `..`, an absolute path or a link). The walk now also opens a folder
and reads a file, and its last step, the projects list, passes.

Not built of the approved mockups, and left for the next pieces: "Find a file by name" in Files,
"Carry out this plan", the mode menu, the cost window, "Start in a new, empty folder", a session's own
address, the Library card. Two differences from the mockups, both because this stage only reads: the rules
cards say the agent cannot change or run anything, and the plan card has no "Carry out this plan" button.

## The rest of the first screens (2026-11-14, branch `coding-c1b-rest`)

Four small pieces of the approved mockups, each walked for real in the same walk (`code-plan`): a session's
own address (the window loaded again, the session still open), "Find a file by name", the cost window with a
limit that can be changed, and the session as a card in the Library under "Coding sessions". Pictures:
`docs/ui-audit/desktop/code-session-find-cost.png`, `code-library.png`.

Not walked: changing the limit with a paid model (the walk uses the local model, which has no cost; the
change is tested against the gateway in `test_coding_sessions.py`), and opening a session from a search
result. Still not built: "Carry out this plan", the mode menu, "Start in a new, empty folder".

## For the next stages

- **The screens (C1b, second half):** the session view and the Files tab, after the mockups are approved
  and the event kinds agreed. The relay (`runtime.Feed`) already has everything in order; the route that
  streams it is the only thing missing on the engine side. The Library card and filter for `code_session`.
- **C2:** modes that edit. `Sessions._turn` hands the turn to `Loop.run_turn` for a session that may write;
  the folder moves from the read-only list to the writable one (one start of the server); the rules module
  and the confirmation card (`places.CONFIRM` is translated already, and answered "no" in Plan mode).
- **C4:** the coding product's own connection, as decided in point 3.
- `CLAUDE.md` lives in the main checkout only. Its row "Working on the coding agent" should say that the
  engine side of C1b is built (the product wired in, the gateway, a session that only reads, no screen), and
  name `docs/spikes/coding-c1b.md`, `coding_gateway.py`, `coding_models.yaml`, `scripts/coding-engine-types.py`
  and the tests `test_coding_gateway.py`, `test_coding_sessions.py` and
  `tests/integration/test_coding_session_real.py`.
