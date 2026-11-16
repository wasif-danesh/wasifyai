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

## Amendment (2026-11-15): what stage X2 built, and where it differs

Stage X2 of `docs/v2-coding-agent-start-plan.md`. The owner's standing yes of 2026-11-15 covers its routes, its
stream event and its actions.

1. **The engine is told the skills; it loads none itself.** A conversation is started with the skills that are
   on for its project, each with its whole text, in the conversation's own context. The engine's own loaders
   (the public catalogue, the home folder, the project's folder) all stay off. So "our short list as the only
   marketplace loaded" (stage X1) is done this way: nothing but what we name reaches a session, whatever else
   is in the catalogue on disk.
2. **Wasify AI's own skills live in the product's package**, `products/wasifyai-code/wasifyai_code/own/`, not
   in a top-level `extensions/` folder as decision 3 said, so that they are shipped with the product. The
   format is the same. The short list is `own/marketplace.json`.
3. **The short list today:** three of ours (Explain in plain words, Pictures with Wasify AI, Write the tests
   first) and four of the pinned catalogue (Code review, Front-end design, Security, Technical writing). The
   first two of ours are on for a new project; every other is off until switched on. The names are stand-ins
   and the list is the owner's to change: it is one file.
4. **On or off is kept for one project and one person.** A switch holds from a session's next message: a
   conversation's skills are fixed when it starts, so a project's sessions that are at rest begin a new
   conversation, and are given the last answer to go on from. A turn that is running keeps its skills.
5. **A skill's own files are put where the sandbox can read and not write them**
   (`<app data>/coding-fixed/skills/`), only for the skills that are on, so the agent can read a skill's
   further files when the skill names them. A folder is removed there when its skill is switched off.
6. **Adding from a folder copies the folder** into `<app data>/code/extensions/`, without following links.
   The person's folder is not changed and is not read again. At most 5 MB and 200 files. Two skills cannot
   have the same name.
7. **A plugin is recognised and refused** (a folder with `.plugin/plugin.json`). Plugins, with the approval
   card for what they bring, are stage X3.
8. **Which skills a message switched on is said on the stream** (`code_skills`), from the engine's own record
   of it, and shown in the chat as a quiet line.
9. **Actions:** `code.extension.list`, `code.extension.switch`, `code.extension.add`. Removing is on the
   screen and in the Library, as for other things a person keeps.
10. **Search (decision 10).** A skill the person added is a kind of its own in the Library, "Coding skill"
    (`code_extension`), found by its name and by what it says it is for. The short list is the app's own and
    is not in the Library; the Extensions screen has its own search over everything offered.
11. **Not built:** plugins; adding from the internet; the integrations list; changing a skill's text in the
    app; a skill switched on for every project at once.

Measured in `docs/spikes/coding-x2.md`.

## Amendment (2026-11-15): plugins and templates, as built in stage X3

The decisions above stand. What was settled while building, under the owner's standing yes of 2026-11-15
("Yes, add and document"):

1. **A plugin is added from a folder, like a skill** (a folder with `.plugin/plugin.json`). Nothing of the
   catalogue's 13 plugins is on the short list: several need accounts or connections outside this computer,
   and the short list stays the owner's to choose.
2. **What a plugin brings is read by our own reader and listed before anything is copied:** its skills
   (`skills/<name>/SKILL.md`), its hooks (`hooks/hooks.json`) and its tool connections (`.mcp.json`, by name
   and where each goes; what a connection is given, such as a key, is never read back out).
3. **A plugin that brings a hook or a tool connection stays off until the person approves it** (decision 6).
   Approval is once per plugin, at the window only: there is a route and no action, so the assistant cannot
   approve. Switching it on for a project is a separate step. A switch written without the approval is not
   honoured: a session is given neither the plugin's skills nor its hooks. A plugin that brings text only
   needs no approval.
4. **A hook is a plain command and nothing else.** A hook that asks a model (the format's `prompt` and
   `agent` kinds), one that runs on in the background, and one for a moment we do not know make the whole
   plugin unreadable: we never run a part of what would be approved as a whole.
5. **Hooks are given to the coding engine with the conversation** (`hook_config`), each with one second to
   run whatever the plugin asks for (ADR-0102), and with `PLUGIN_ROOT` set to our read-only copy of the
   plugin. The engine runs them inside its sandbox, so a hook can do no more than the agent's own commands.
   A session that only reads (Plan) is given no hook.
6. **Tool connections are listed and not connected.** The sandbox reaches nothing outside this computer,
   and a tool server started inside it would need its own review. The approval card says so.
7. **Templates (decision 9)** are our own short list, `wasifyai_code/own/templates.json`: five starting
   points, each prompt text and a plain rule. None of the catalogue's 27 automation templates is used as it
   is: every one of them needs an integration (GitHub, Slack, Jira and others) or an incoming webhook, which
   a run in the sandbox cannot reach. A template only fills the form; the person can change everything.
8. **Search.** An added plugin is in the Library with the added skills (`code_extension`), found by its name
   and what it says it is for.
9. **Not built:** a plugin's commands and agents (they are copied and unused); connecting a plugin's tool
   connections; plugins from the catalogue or the internet; taking an approval back (removing the plugin
   does that).

Measured in `docs/spikes/coding-c6.md`.

## Amendment (2026-11-15, owner; accepted with ADR-0107): which sessions Extensions serve

The owner: "Our Extensions can be used for local models only."
This amendment holds from 2026-11-15, the day ADR-0107 was accepted.

1. **Extensions serve sessions on the Wasify AI harness.** A session on the person's own agent program
   (ADR-0107) is given no skill, plugin, hook or tool connection of ours. Each program has extensions of its own,
   managed in the program.
2. **The Extensions screen says so** where a project's sessions run on another harness.
3. **Read with care:** the owner's words name "local models". Today Extensions also work in a session on a key
   (Claude, by the gateway), since that is the same harness. This amendment keeps that, and takes the owner's
   words to mean "not on a harness of the person's own". If the owner means that sessions on a key should lose
   Extensions too, that is one more line here and a change in the product.

Nothing else of the decision changes.
