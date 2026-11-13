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
