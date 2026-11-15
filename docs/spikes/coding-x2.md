# Coding agent, stage X2: Extensions

Written 2026-11-15 on the owner's Mac (M5 Pro, macOS 27.0). The stage is piece 7 of
`docs/v2-coding-agent-start-plan.md`, section 9, built after C4 by the owner's order ("Do X2 next, then C6 & X3,
then the browser tab, lastly v1 gate"). What is built is described in `docs/desktop/coding.md`; the decisions
are ADR-0104 and its amendment of 2026-11-15.

## The gate

Section 7's gate for X2: a public skill from the catalogue and one of ours each fire in a real session;
switching one off stops it.

"Fires" has a plain meaning here. The coding engine puts a skill's text into the person's message when the
message has one of the skill's words, and records which skills it did that for. The chat shows that record
("Using the skill ..."). For the person's own skill the walk also checks the answer itself, against a rule
that only that skill gives.

| Gate | Result | How it was measured |
|---|---|---|
| One of ours fires in a real session | **Passed.** "Explain this project in plain words, in three sentences." in a session on the local Qwen 27B: the chat said "Using the skill Explain in plain words"; 37 s | `ui-audit.sh light code-extensions`, step 3 |
| A public skill from the catalogue fires | **Passed.** With "Security" switched on in Extensions, a question about a login: "Using the skill Security"; 30 s | The walk, step 4 |
| Switching one off stops it | **Passed.** "Explain in plain words" was switched off before that same question, which had the words "in plain words" in it: the skill was not named and not used | The walk, step 4 |
| The same, on the real engine with a scripted model, looking at what the model is sent | **Passed.** With ours on: its name is listed for the model and its text is in the message. With it off and a public one on: neither its name nor its text is anywhere in what the model is sent, and the public one's is. The agent can read a skill's own folder and cannot write it | `test_a_skill_that_is_on_is_given_to_the_model_and_fires_and_one_that_is_off_is_not` |
| A skill of the person's own, from a folder | **Passed.** A folder with a `SKILL.md` was looked at (its text shown), added and switched on. Asked for the prices, the answer ended with the line only that skill asks for ("Baked fresh every morning."); 11 s. Removed afterwards: our copy gone, the person's folder as it was | The walk, steps 5 and 6 |
| `make test-coding` | **Passed: 52** (30 hostile tests, 22 of the sessions; 1 is new) | The real server in its sandbox, a scripted model |
| `make test`, `make lint` | **Passed** on the final tree: ruff, the format check, pyright (0 errors), the design check, Biome and the TypeScript check; 3,755 Python tests passed and 495 skipped; 1,301 TypeScript tests (178 client, 220 web, 108 desktop, 795 screens) | The full chains, run while no coding engine was running |

**No paid run was made in this stage.** About 3.75 of the 25 dollars the owner allowed are used, all in stage C3.

## What is built

| Part | Where |
|---|---|
| The small reader of a `SKILL.md`, what is offered, the switch, adding from a folder, what a session is given | `products/wasifyai-code/wasifyai_code/extensions.py` |
| Wasify AI's own three skills and the short list | `wasifyai_code/own/skills/`, `own/marketplace.json` |
| Added extensions and per-project switches in the store | `store.py` (`extensions`, `extension_switches`) |
| A session is started with the skills that are on; a switch begins a new conversation | `runtime.py` (`skills_for`, `switch_extension`, `_begin_again`), `place.py` (`SessionSpec.skills`), `client.py` |
| The skills a message switched on, on the stream | `events.py`, `runtime.py`; `code_skills` in `docs/contracts/sse-events.md` |
| Routes and actions | `routes.py`; `actions.py` (`code.extension.list`, `switch`, `add`), `docs/help/` |
| The Extensions screen, its page in the window and its menu item | `packages/ui/src/code/Extensions.tsx`, `apps/desktop/src/pages/Code.tsx`, `menu.ts`, `router.ts` |
| An added skill in the Library and in search | `index.py`; "Coding skill" in `packages/ui/src/creations/`, `packages/client/src/creations.ts`; a row in `services/api/evals/search/corpus.yaml` |
| The walk of this stage | `apps/desktop/scripts/ui-audit-pictures.mjs`, scenario `code-extensions` |

## Found on the way

1. **The engine loads no skill at all unless it is told to.** Since stage C1a every loader of its own has been
   off, so until now a session had no skills, public or ours. X1's aim ("only the short list's skills are
   offered") is reached by giving a conversation its skills ourselves, with their text; none of the engine's
   loaders is switched on.
2. **A conversation's skills are fixed when it starts.** A switch could not reach a conversation that was
   already there. Letting go of the project's conversations that are at rest is what makes "switching one off
   stops it" true from the next message.
3. **The engine's record names every skill used so far in the conversation, not only the newest.** In the
   walk's third turn the chat said "Using the skills Security, House style", though only "House style" was new.
   It is shown as the engine says it.
4. **A skill with no words of its own is listed for the model and nothing more**: the agent reads it when it
   judges that it fits. Two of the four public skills on the short list are of that kind (Front-end design,
   Technical writing). That they are listed was checked; that a model then reads one was not.
5. **`search_text` drops a last full stop.** The words an added skill is found by are stored without it.

## Decided while building, for the owner to see

1. **The short list** is three of ours and four public ones (ADR-0104, amendment, point 3). It is one file.
2. **Two of ours are on for a new project** (Explain in plain words, Pictures with Wasify AI), so that a person
   who never opens Extensions still gets them. Everything else is off until switched on.
3. **Wasify AI's own skills are in the product's package**, not in a top-level `extensions/` folder.
4. **A switch begins a new conversation** for the project's sessions, as a change of mode does. The agent is
   given the last request and answer to go on from, and the turn says so.
5. **The window's item Code › Extensions is shown now**; Scheduled stays hidden until it is built.
6. **Removing an added skill** is on its details and in the Library; there is no action for it.

## Not measured, not built

- **The real Tauri window was not opened.** The walk drives the real window's page in a browser; the folder
  picker is answered by the walk's stand-in.
- **Claude Sonnet 5.5.** The local model alone was run.
- **A skill with no words** being picked up by a real model (found 4).
- **A skill that brings further files** which the agent then reads: the folder is there and readable, and no
  skill on the short list was seen to use one.
- **Plugins**, adding from the internet, the integrations list, changing a skill's text in the app, one switch
  for every project.
- **The web.** Coding is desktop only.

## For the next stage (C6 and X3)

- Plugins: `extensions.look` already tells a plugin from a skill and refuses it; X3 gives it the approval card
  with what it brings listed.
- Scheduled runs call `Loop.run_turn` with `unattended=True`; a run's skills are the project's, like a chat's.
