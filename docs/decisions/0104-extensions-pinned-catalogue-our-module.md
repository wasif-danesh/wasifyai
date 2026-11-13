# ADR-0104: Extensions: OpenHands' catalogue as a pinned copy, the module that manages it is ours

- **Status:** Accepted (2026-11-14, by the owner: "Accept all"). The owner's words behind it: "I don't see anything about the Extensions module in OpenHands.
  We need to copy or implement it." and "Coding, automation and extensions will be part of v1." (2026-11-13)
- **Date:** 2026-11-14
- **Plan:** `docs/v2-coding-agent-start-plan.md`, section 7 (stages X1, X2, X3).
- **Keeps:** ADR-0070 (tools from other apps and their trust levels), ADR-0041 (searchable), ADR-0068 (actions),
  ADR-0102 (no hook longer than one second; nothing fetched from the internet by the engine).
- **Goes with:** ADR-0101.

## Context

OpenHands' Extensions is a catalogue, not a program: the package `@openhands/extensions` (0.42.0, MIT, about 10 MB).
It holds:

- 73 skills: a folder with a `SKILL.md`, offered to the agent and switched on when a message matches it;
- 13 plugins: a folder with `.plugin/plugin.json` that can bring skills, hooks and tool connections, attached to a
  session by its folder;
- 27 automation templates and a list of 79 integrations (tool servers for GitHub, Slack and others);
- two "marketplaces", which are lists that say which entries are offered;
- three small apps for OpenHands' own screen.

The screens that list and manage these are part of Agent Canvas, which we do not use (ADR-0101).

Two facts from the code and the test app matter:

- **Without `EXTENSIONS_PATH`, the engine copies the catalogue from GitHub's `main` branch and keeps it up to date at
  run time.** With it, the engine reads the folder given and fetches nothing.
- In the owner's test app, a plugin from the catalogue was attached to one session and its skill fired.

Most of the 73 skills are for developers who work with GitHub, Jira, Slack or OpenHands itself. A person who is not
a developer should not meet them first.

## Decision

1. **The catalogue's content is taken as it is**, as a pinned archive in the installer's manifest, checked by size
   and SHA-256 and installed with the coding engine. `EXTENSIONS_PATH` always points at it. Nothing is fetched while
   a session runs.
2. **What is offered is our choice.** A marketplace file of our own names the entries shown in Wasify AI: a few to
   begin with. The rest of the catalogue stays on disk, unused, until it is chosen.
3. **Wasify's own skills and plugins** live in `extensions/` in this repository, in the same format, so that a
   public skill and one of ours are handled alike.
4. **The module is ours**: `wasifyai_code/extensions.py` and a screen. It lists, searches, shows details, switches
   an entry on or off for a workspace, and adds one from a folder. It reads the format with a small reader of its
   own (it does not import the OpenHands SDK) and tells the Agent Server what to load.
5. **A skill's text is outside content.** It is shown before it is switched on, and it never widens what the agent
   may do.
6. **A plugin that brings a hook or a tool connection is approved once by the person**, with what it brings listed.
   Its hooks fall under the one-second rule.
7. **The three apps are left out.** They are pieces of OpenHands' screen.
8. **The integrations list is used later**, as entries for Settings › Other apps › Tools from other apps, where the
   trust levels already exist.
9. **The automation templates are used as prompt text** for Scheduled (ADR-0105). They were written for OpenHands'
   own automation runs, which we do not use.
10. **Every extension the person adds or switches on is found by search** and is reached through actions
    (`code.extension.*`).

## Consequences

- The catalogue is a third pinned thing beside the engine's packages. It moves on its own, when we choose.
- Choosing the short list is editorial work, for the owner or with the X2 mockup.
- Adding an extension from the internet is not in this ADR. It needs its own approval step and comes later.
- Stages: X1 with the engine (the pinned copy, the short list as the only marketplace loaded); X2 after commands
  work (the screen, the first of our own skills); X3 with Scheduled (plugins with the approval card, templates).
- Gates: with the network closed, a session starts and only the short list's skills are offered; a public skill and
  one of ours each fire in a real session, and switching one off stops it; a plugin with a hook is refused until
  approved.
