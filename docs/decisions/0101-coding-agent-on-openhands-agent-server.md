# ADR-0101: The coding agent is built on OpenHands' Agent Server, with our own screens

- **Status:** Accepted (2026-11-14, by the owner: "Accept all"). The owner's words behind it:
  - "The project is very close what I'm also trying to achieve. We need to adjust our plan accordingly." (2026-11-13,
    after the first guideline advised an agent core of our own)
  - "Coding, automation and extensions will be part of v1. Do desktop and mac first." and "web browser, file
    browser, file changes, result preview will be part of v1." (2026-11-13)
  - "Use Sonnet 5.5 first" (2026-11-13)
- **Date:** 2026-11-14
- **Plan:** `docs/v2-coding-agent-start-plan.md`. Background: `docs/v2-coding-agent-guideline.md` (version 2).
  Measurements: `docs/spikes/coding-c0.md` (ten spikes, all run).
- **Keeps:** ADR-0068 (every feature an action), ADR-0041 (every creation searchable), ADR-0092 (who may call the
  engine, where keys live), ADR-0094, rule 7 (tenancy), rule 8 (identity), rule 9 (usage).
- **Goes with:** ADR-0102 (how the engine is installed, run and held), ADR-0103 (the check loop and undo),
  ADR-0104 (extensions), ADR-0105 (the scheduler).

## Context

The owner's aim is a coding agent inside Wasify AI: a chat that reads, edits and runs code, with a file browser, file
changes, a web browser, a result preview, scheduled runs and extensions.

Two ways were weighed. An agent core of our own was the first guideline's advice and was set aside by the owner.
OpenHands is an open project that already has the engine: an Agent Server with tools for a terminal, a file editor,
search and a task list, sub-agents, a way to shorten long sessions, hooks, a confirmation step, and an API of 151
paths with a live socket. Its screen (Agent Canvas), its automation service and its extensions catalogue are separate
parts.

The spikes showed that the Agent Server can be driven wholly from outside:

- A session was started, sent to, followed live and stopped over its API (spikes 2 and 7).
- An evaluation of 36 tasks with hidden checks passed 36 of 36 twice with Claude Sonnet 5.5 (median 13 s and about
  $0.07 a task) and 33 of 36 with the local Qwen 27B (spike 3).
- It runs inside an operating system sandbox with no internet and without the model key (spikes 2 and 4).
- Rules of ours load into it without changing its packages (spike 5).

The owner's test app (`~/Projects/openhands-integration`) showed what goes wrong when the window talks to the Agent
Server directly: there is no place for our rules, our search, our usage records, or a check the agent cannot skip.

## Decision

1. **The engine is OpenHands' Agent Server and SDK**, taken as four packages at one pinned version
   (`openhands-agent-server`, `openhands-sdk`, `openhands-tools`, `openhands-workspace`; 1.62.0 when this was
   written). We never fork them, never copy their source into this repository and never patch them.
2. **We do not write an agent core of our own.**
3. **The screens are ours.** Agent Canvas is not used. The session view, Files, Changes, Terminal, Browser, Preview,
   Scheduled and Extensions live in `packages/ui/src/code/` and serve the desktop and, later, the web.
4. **The window never talks to the Agent Server.** It calls actions of a new product, `wasifyai-code`. In that
   product one file (`client.py`) knows the Agent Server's API. The Wasify API never imports the OpenHands SDK.
5. **A "place" interface** sits between the product and the engine, with one implementation in v1: this computer.
   It exists so that a server or a cloud can be added later without changing the product.
6. **The Agent Server's "finished" is not our "done".** What counts as done, what is asked of the person, what is
   recorded and what is charged are decided in the Wasify engine (ADR-0102, ADR-0103).
7. **The first model is Claude Sonnet 5.5**, with the gates measured on it. The local Qwen 27B is the second run of
   every gate. Other models follow the picker that exists.
8. **In v1:** coding sessions with the check loop, the file browser, file changes with undo, the web browser, the
   result preview, Scheduled and Extensions, on the desktop and the Mac first. **Not in v1 unless the owner says
   so:** outside agents such as Claude Code and Codex, the starters for apps and games, the web version of coding,
   Windows and Linux, teams and the cloud.
9. **The version moves as its own piece of work**, about monthly, and only when the contract test and the
   evaluation pass (Sonnet 5.5 stays at 36 of 36). The types for the events we show are generated from the Agent
   Server's API description at the pinned version, so a change breaks the build and not a screen.
10. **A change we need in the engine is proposed to OpenHands.** Until it lands, the need is met in our own code or
    not at all.

## Consequences

- We gain an engine that would have taken many months to write, and we take on its pace: five versions shipped in
  one week of November 2026.
- A second Python environment ships as an optional part (ADR-0102).
- Every screen is ours to build. None of OpenHands' screen work is reused.
- The evaluation set (`docs/spikes/coding-eval-tasks.json`) moves into the product with a runner of its own in the
  first stage that has the product (C1b). It is too easy to show where Sonnet 5.5 stops; real projects in the stage
  gates do that.
- The stages are C1a, C1b, C2, C3, the Extensions screen, C4, and C6 with the scheduler, in that order
  (`docs/v2-coding-agent-start-plan.md`, section 9). Each has a measured gate.

## Amendment (2026-11-14, owner): the event kinds of a coding session's stream

The plan said the session stream needs new event kinds in the SSE contract, to be agreed in stage C1b before
any code sends them. The proposal is in `docs/spikes/coding-c1b.md`. The owner's words: "Reuse existing kinds".

1. A coding session's stream reuses four kinds of the contract where the shape fits: `tool_call` and
   `tool_result` for a tool step, `token` and `reasoning` for words as they are written.
2. It adds three: `code_state` (a turn's state, how it ended, the session's word and cost), `code_message` (a
   finished message of the agent) and `code_refusal` (the model declined; not an error).
3. `token` and `reasoning` are not kept on this stream. A client that connects later gets the `code_message`.
4. The stream is one per session and stays open across turns; a turn's end is `code_state` with `state: "done"`.

The fields are in `docs/contracts/sse-events.md`, "A coding session's stream". The route and the models are
built with the session view; until then the engine relays inside itself.


## Amendment (2026-11-14, owner): the approval card on the stream, and a turn's changes

For stage C2 the owner chose again to reuse an existing kind (asked on 2026-11-14: "Reuse interrupt").

1. The approval card is the contract's `interrupt` with `kind: "code_ask"`; its payload names the kind of request,
   the step that waits, the file and whether Undo covers it. No new event kind.
2. The answer is not a stream event. It is `POST .../sessions/{id}/asks/{interrupt_id}`; the step's `tool_result`
   then says how it was answered (`output.answer`), with `status: "refused"` after a no.
3. `code_state` with `state: "done"` gains the optional `changed`: how many files the turn changed.
4. The coding API gains, as additions only: `mode` on a session, a turn's changes and one changed file before and
   after, undo and "bring it back", the answer to a card, and what a project may do.

## Amendment (2026-11-15, owner): the check on the stream, and the routes of stage C3

The owner agreed on 2026-11-15 to one new event and three new fields on a coding session's stream, and to new
routes of the coding product. They are written in `docs/contracts/sse-events.md` and listed in
`docs/desktop/coding.md`.

1. **`code_check`**: one run of the project's check has ended: its round, command, result, exit code, seconds,
   the end of its output and the tests the agent changed.
2. **`code_state`** gains `round`, `needs_you` and `check_why`. Within one turn `working` and `turn_ended` now
   come once for each round.
3. **Routes:** the project's check (`GET`, `PUT .../check`, `POST .../check/run`, `GET .../checks/{id}`,
   `POST .../check/again`) and the person's terminals (`GET`, `POST .../terminals`, and for one terminal its
   events as a stream, `input`, `size` and `DELETE`). A terminal's output is a stream of its own, not part of the
   session's stream: it is the person's, and the agent does not see it.
4. **One new action:** `code.session.check` (read, set and run the check). The person's terminal is a tool of the
   screen and has no action: an assistant that could type into it would be a second way to run commands, outside
   the rules.

## Amendment (2026-11-15, owner): the routes and actions of stage C4

The owner agreed on 2026-11-15 to routes and actions for the preview and for a new project. Nothing changes
on a coding session's stream.

1. **Routes:** the project's preview (`GET`, `PUT .../preview`, `POST .../preview/start`,
   `POST .../preview/stop`), the starters (`GET /code/starters`) and a new project from one
   (`POST /code/projects`).
2. **Actions:** `code.session.preview` (start, stop, or say where it is) and `code.project.new`.
3. **A starter is plain files of ours**, copied into a new folder inside a folder the person chose
   (`starters.py`, `starters/web/`). The first one is a small web app with no build step and nothing to
   install; its check (`npm test`) and its preview (`npm run dev`) are set with it, because they are part of
   what was made.

## Amendment (2026-11-15, owner): Claude Haiku 5.5 is a model a coding session can choose

Decision 7 named two models, Claude Sonnet 5.5 first and the local Qwen 27B second. The owner asked for
Claude Haiku 5.5 to be measured and then said "Yes, add Haiku".

1. **Claude Haiku 5.5 is the second entry of `coding_models.yaml`**, on the same key as Sonnet (Settings ›
   Your keys, Anthropic). Sonnet stays the first choice.
2. **Why:** on the 36 evaluation tasks it passed 35 and 36 in two runs, with every change undone exactly, at
   about a thirteenth of Sonnet's counted cost. It takes about a third more steps (`docs/spikes/coding-haiku.md`).
3. **Its long-prompt price is counted.** A call whose prompt is over 100,000 tokens costs five times as much.
   The gateway prices each call by itself, so a session's cost and its limit stay true in a long session.

Nothing else of the decision changes.

## Amendment (2026-11-15, owner): every model a saved key lists can be chosen

Decision 7 and the Haiku amendment made the models a short list in a file, each added after it was measured.
The owner: "We should display opus and fable in the list and let user select a model when Anthropic key is
provided. It applies to ChatGPT and Gemini as well when a key is provided. It shouldn't be hardcoded to 1/2
options." The model is chosen for a new session; a session keeps the model it began with ("Choosing per new
session for now").

1. **Every chat model a saved key lists is a choice**, for Anthropic, OpenAI and Google Gemini, on the key
   saved for Chat and writing (Settings › Your keys). The list is the vendor's own, asked as chat asks it. A
   model is named `<vendor>:<the vendor's model name>`. The vendors are the `vendors` of `coding_models.yaml`.
2. **The measured models stay first and are marked "Tested for coding"**: Sonnet 5.5, Haiku 5.5 and the local
   Qwen 27B. The others say "Not tested for coding here". Nothing is hidden because it was not measured.
3. **Sonnet 5.5 stays the first choice.**
4. **A price is the one chat's catalogue knows.** A model with no known price is counted in tokens, and its
   session stops at a limit in tokens (3,000,000 in and out unless the person sets another) where a priced
   one stops at a limit in dollars.
5. **Code is on the model button**, like every other product, and has a line in "What this computer can do".
6. **Proven:** Claude Opus 5.5 and Claude Fable 5.2 each ran two evaluation tasks through the real coding
   engine (`docs/desktop/coding.md`, "The models"). **Not proven:** an OpenAI or a Gemini model in a real
   session; no key for either was saved when this was built. They are called as chat completions at the
   vendor's OpenAI-compatible address, which is tested against a pretended provider only.

Nothing else of the decision changes.

## Amendment (2026-11-15, owner; accepted with ADR-0107): a session's harness

The owner: "This 'Harness' feature is an absolute requirement for us. It's okay to change the sandbox rules."
This amendment holds from 2026-11-15, the day ADR-0107 was accepted.

1. **A coding session has a harness** (ADR-0107). "Wasify AI" is OpenHands' own agent, as decided here. The
   others are the person's own agent programs (Claude Code, Codex, Gemini CLI), run by the same Agent Server
   through its ACP agent (`agent_kind: "acp"`).
2. **Decision 1 stands and is what makes this possible:** the Agent Server is still the only engine, and
   `client.py` the only file that knows it. No engine of ours is written and no other harness project is taken.
3. **Decision 7 and its two amendments on models speak of the Wasify AI harness.** A harness of the person's own
   has the models its program offers, asked from the program.

Nothing else of the decision changes.

## Built (2026-11-18): the local model follows the Model hub (`docs/coding-local-model-plan.md`, LM0 to LM3)

Decision 7 says other models "follow the picker that exists". Built: the one local entry, `this-computer`, is
the language model chosen in the Model hub, run through `LanguageService.session(coding=True)` on the app's own
`llama-server` (or a found Ollama or LM Studio model); the test-only `qwen-27b-ollama` entry is gone. The model
button shows it by name, says why it cannot run, and marks small models "May not manage coding well". Qwen3.8
27B (`Q4_0`) is on the Model hub's shelf; on it the 36 tasks passed 33 of 36 and the seven walks of the v1 gate
passed (`docs/spikes/coding-local-lm0.md`). Nothing of the decision changes.
