
## Built 2026-10-27 (stage A2, first slice)

- **Decision 3** as written: the meta-tools `how_to`, `app_status`, `propose_action` and `open_screen` replaced
  `generate_image` and `make_music` (`wasifyai_assistant/tools.py`); the searches and the web tools stay. The tool list
  is eight whatever the catalogue holds. The system prompt carries the rules of decision 6 and the generated map of
  the actions this engine serves (`features.actions_prompt`, about 600 tokens; the web, app and job actions are left
  out because they have tools of their own).
- **Decisions 1 and 2:** the help corpus ships inside the assistant's package as `help.json`, written from
  `docs/help/*.md` by `wasifyai_api.assistant_features --write` (a test fails when it is stale). Retrieval is words,
  stems, synonyms and action ids (`wasifyai_assistant/help.py`); the embedder is not used yet (open question 1, for A3).
- **Decision 4:** the card carries `action_id`, `effect`, `badges`, `consent`, `screen` and `fields` drawn from the
  action's input schema; the window edits the fields in place and **Run** sends them back (`{approved, params}`); an
  edited request runs on the person's click, and the floor shows a second card. `needs_consent` is a tick of its own.
  The result is drawn by the action: a picture or a player where one exists, a result card with Open otherwise. No
  estimate yet (nothing is measured per machine), and no "pauses the chat model" note.
- **Decision 5** in part: the run input `auto_run` (per turn, sent by the client) makes the assistant run `make`
  actions without a card; the composer switch "Don't ask again in this chat" and the "ask only for long or
  leaving" level are not built. The taint rule holds whatever the setting.
- **Decision 7:** the executor's words (`'prompt' is required.`) go back to the model unchanged.
- **Decision 8 (A3)** is not started: the tool-choice cases moved to `propose_action` (`evals/cases.yaml`), but no
  guide, status, safety or tool-count cases exist yet and nothing was measured against a model.
- The chat answers `open_screen` with a button on the desktop (menu routes) and the web (menu addresses).
