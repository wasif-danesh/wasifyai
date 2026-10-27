# The assistant on the desktop

Part of [the desktop profile](../desktop-profile.md): what is built, how it is wired, what is not done.

## The assistant (ADR-0057, stage D3 and D4)

`wasifyai-assistant` is a product like the others, enabled on the desktop by default. A turn is a run of its
graph: `POST /products/wasifyai-assistant/runs` with `{"text": ..., "conversation_id"?: ...}` streams `token`,
`tool_call`, `tool_result` and `job_progress` events and ends with `done` (`conversation_id`, `title`, `reply`).
Conversations are listed, read, renamed and deleted under `/products/wasifyai-assistant/conversations`. It
answers with the model chosen in Models; with none chosen the run ends with an error that says to choose one.

Tools are an explicit list in `wasifyai_assistant/tools.py`, fixed at eight whatever the catalogue holds (ADR-0071
decision 3, built 2026-10-27): `how_to` reads the help corpus (`help.json`, written from `docs/help/`), `app_status`
runs `app.status`, `propose_action` asks the executor to run any catalogue action (a card first, unless the chat's
`auto_run` is on), `open_screen` offers a button, and the two searches and the two web tools are as before. A
picture proposed and approved runs the image product as a child run, so it is saved, indexed and has its recipe like
any other; `search_creations` looks in the person's own library and names what it finds (notebooks by title) but does
not read inside documents.
`search_notebooks` (stage E6) looks inside the person's notebooks: the engine embeds the question once, runs the
notebooks' hybrid retrieval over up to 40 notebooks that have a ready source (the most recently used), keeps 3
passages per notebook, merges by score, and returns the best 5 with at most 2 per source. The model gets each
passage (up to 700 characters) with its notebook and source, told that it is quoted material and not
instructions; the window shows the source, the notebook and a snippet, with "Open notebook". If the search model
is not installed or notebooks are not part of the build the tool answers that in words. The model never sees a
file or a link, only a sentence, passages and ids.

### The tools are catalogue actions (ADR-0068, stage A1)

Every tool that does something runs through the action executor (`wasifyai_platform_sdk.actions`, `docs/actions.md`):
`propose_action` names the action (`image.generate`, `speech.speak` ...), `app_status` is `app.status`,
`search_creations` is `library.search`, `search_notebooks` is `notebook.search`, all with the origin `assistant`.
The default is the card (`ApprovalPolicy()`): a `make` waits for the person's Run; with the run input `auto_run` it
runs at once (`ApprovalPolicy(make="auto")`). Deleting and anything that needs a person's word always ask, from any
origin. The card (`ConfirmActionCard`) is drawn from the action's input schema and can be edited before Run; the
result is drawn by the action (a picture, a player, or a result card with Open). The engine builds the catalogue
for the products it serves (`app.state.actions`, `wasifyai_api.actions_engine`), with the audit log and the
pending approvals in the same SQLite file (`action_audit`, `action_approvals`, created on first use, additive
only). Every call writes one audit entry (no content) and one `action.run` usage event. `docs/contracts/actions.json`
is the catalogue as a file; `docs/help/` holds the help for every action.

### Evaluating a model for the assistant

`uv run python products/wasifyai-assistant/evals/run_tool_eval.py --gguf <file> --data-dir <app data>` runs the
tool-choice cases in `evals/cases.yaml` against a model with the assistant's own prompt and tools and prints
accuracy, answer time, speed and the server's memory. Add a case for every mistake a model makes in real use.
The recommended model on the hub shelf is the one that scores best here.
