
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
  The result is drawn by the action: a picture or a player where one exists, a result card with Open otherwise. The
  **estimate** is measured, not guessed: the median of this person's last runs of the action from the audit log
  ("Takes about 12 s on this computer (your last 3 runs)"), absent until one ran; a download size is not shown
  because a card never appears for an action that still needs a model (that is a `needs_setup` result with the step).
  On the desktop the card says "Pauses the chat model while it runs" for a child run that makes something.
- **Decision 5** as written: the run input `approval` (`ask`, `ask_costly`, `auto`), set per conversation by the
  Ask button in the box ("Asks first", "Asks for big things", "Doesn't ask") and by "Don't ask again in this
  chat" on a card. The taint rule holds whatever the setting.
- **Decision 7:** the executor's words (`'prompt' is required.`) go back to the model unchanged.
- **Decision 8 (A3), run 2026-10-27** (`docs/spikes/assistant-a3.md`): 58 cases of the five kinds, judged by a
  runner that answers `how_to` and `app_status` for real. On Qwen3 8B Q4_K_M (the model on this Mac): tool choice
  28 of 32, with 40 extra remote tools 7 of 7, guide 16 of 17, status 2 of 3, safety 4 of 4; guide and action together
  44 of 49 (89.8 percent, one case short of the 90 the gate names; the recommended 4B and a hosted tier were not run).
  The run changed the prompt (a request to make something goes straight to `propose_action`), the retrieval scoring,
  two help files' synonyms, and gave `how_to` each guide's readiness.
- The chat answers `open_screen` with a button on the desktop (menu routes) and the web (menu addresses).
