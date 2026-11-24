# ADR-0110: Chat on the person's own plan: the chat can answer through Claude Code or Codex, signed in with the person's own Claude or ChatGPT subscription

- **Status:** Accepted (2026-11-24, the owner: "Implement it first"); P0 to P2 built the same day (see "Built"). Earlier: The owner asked "Why there is no option for subscribed users to
  Claude/ChatGPT/Gemini?" about the chat's model picker, and said "Yes, draft it" to this record. On the draft:
  "It should support Claude, ChatGPT, and Gemini." After reading what Google's plans allow
  (`docs/spikes/google-ai-plans-2026-11.md`), the owner, 2026-11-24: "no gemini or antigravity is needed. Only
  claude and chatgpt subscription in the chat for now."
- **Date:** 2026-11-24
- **Keeps:** ADR-0107 (the person's own agent program, unmodified, signing in by itself; Wasify AI never reads, stores
  or sends a plan's login or token), ADR-0069 (the MCP server and its approval cards), ADR-0071 (what a card says and
  the floor that always asks), ADR-0070 decision 4 (the taint rule), ADR-0086 (one model button), ADR-0092 (the
  secret store), ADR-0082 (the chat on assistant-ui).
- **Changes:** ADR-0107 decision 1 says a harness is for a coding session. This record adds a second use, the chat,
  on the same programs, sign-in and optional part. ADR-0107 gets an appended amendment that points here if this is
  accepted; its question 3 (Gemini CLI) is answered for the chat by the owner's words above: no Google program.

## Context

The chat answers on a model on this computer or on a cloud model through a saved API key (ADR-0100). Many people
already pay for a plan (Claude Pro or Max, ChatGPT Plus or Pro) and have no API key. ADR-0107 let them use
the plan in **Code**, where the app starts the provider's own program (Claude Code, Codex) and the program signs in
by itself. The chat's model picker has no such choice: its tabs are Recommended, On this computer, Cloud and More.
The Your agent tab is given only to Code (`apps/desktop/src/choices/code-choices.ts`).

The chat is not a coding session. What it needs from a model is different:

- **Its tools are Wasify AI's own actions** (make a picture, a song, a clip; read the Library; ask a notebook), each
  one a catalogue action with its card (ADR-0068, ADR-0071). In Code the program's tools are its own (files, shell).
- **Every turn is short and many are plain talk.** A program that starts for each turn adds its start time to every
  answer.
- **The chat branches.** A person edits an earlier message or asks again (CU2), and the conversation forks. A
  program keeps one straight session.
- **It is used in many languages,** Bengali and five Indian languages included.

**What the providers allow** was read for ADR-0107 on 2026-11-15 and is not read again here. In short: Anthropic
allows a product to start the unmodified Claude Code with the person signing in through Anthropic's own flow, and
forbids an app sending requests through a plan's credentials on a person's behalf or handling a Claude.ai login or
token. OpenAI's Codex signs in with ChatGPT; OpenAI has "Sign in with ChatGPT" terms for apps but no plain statement
about an app that starts Codex. ADR-0107's question 1 (whether starting Claude Code through the Agent SDK adapter counts
as "the unmodified Claude Code binary") is still open. These rules changed several times in 2026; they are read
again before anything here is built, and the chat is a step further from coding than Code is.

**Google is left out.** Google's pages, read 2026-11-24 (`docs/spikes/google-ai-plans-2026-11.md`): Gemini CLI no
longer serves Google AI Pro or Ultra (since 2026-06-18), and Antigravity's terms forbid another app starting `agy`
on a consumer plan. A Pro or Ultra plan's monthly developer credits can pay for a Gemini API key, which Wasify AI
already takes (ADR-0100); that is a key, not this record's subject.

## Options

| | How | For | Against |
|---|---|---|---|
| **A. The program's own command, one call per turn** | Each turn starts the program's own non-interactive command (for example `claude -p` with JSON lines, `codex exec --json`), resuming the program's session for the conversation; Wasify AI's MCP server is the program's only tool server | The unmodified program by its own command, the closest reading of Anthropic's page; no Agent Server, so it works without the coding part; small | A program start on every turn (to be measured); one integration per program, kept in step with each vendor |
| **B. OpenHands' ACP agent, as in Code** | A chat conversation is an ACP conversation on the harness's Agent Server | Code's path, already built and walked | Needs the coding part (about 680 MB for the adapters, plus the Agent Server) to chat; the ACP agent says yes to every permission the program asks; ADR-0107's question 1 applies in full |
| **C. Call the provider with the plan's credentials** | Read the program's login and call the provider's API directly | Fast, our own streaming | Forbidden by Anthropic's page; against ADR-0107 decision 3. Not taken |
| **D. "Sign in with ChatGPT" for apps** | OpenAI's own sign-in for apps, the app as a registered party | OpenAI's sanctioned way for an app | ChatGPT only; registration with OpenAI; a different model of trust. Kept for later |

## Decision (proposed)

1. **The chat's model button gets a "Your plan" tab** (desktop only), listing the programs set up and signed in:
   **Claude Code (a Claude plan) and Codex (a ChatGPT plan)**, the two programs Code already sets up (the owner,
   2026-11-24: "Only claude and chatgpt subscription in the chat for now"). Choosing one makes the chat answer
   through it, with the plan's models the program offers (for example Sonnet, Opus and Haiku on a Claude plan). No
   Google program (Gemini CLI, Antigravity) is added. The web does not get it: the programs run on the person's own
   computer.
2. **Option A: the program's own command, one call per round of a turn.** The program is the person's own, unmodified, set
   up and signed in exactly as for Code (ADR-0107 decisions 3 and 4: the same optional part, the same sign-in,
   status and "Sign in" from the app). **Wasify AI never reads, stores, copies or sends a plan's login or token.**
   Option B is the fallback if the spike shows A cannot hold a conversation well.
3. **The program's only tools are the chat's own tools,** the ones the assistant graph offers that round, listed
   to it by a small MCP server of ours that runs nothing (`plan_tools_server.py`). When the program asks for a tool,
   the call is read from the program's own events, the program is stopped, and the call goes back to the graph as
   the model's tool call; the graph runs it as it runs any model's call, and the next round starts the program again
   with the result. Its built-in tools (shell, files, editing, its own web fetch and search) are switched off by the
   program's own options for the call. So a picture, a song or a notebook answer is the same action, with the same
   card, as in any chat. (Changed when built: not a connection to the MCP server of ADR-0069, so no second path for
   cards is needed.)
4. **Cards and the floor are unchanged.** An action that asks shows its card in the conversation, and the person
   answers there (ADR-0071). `destroy` and `needs_consent` always ask (ADR-0068). The taint rule holds: after outside
   text, everything that is not a read asks (ADR-0070 decision 4). Search is Wasify AI's own `web_search`, with its
   opt-in, not the program's.
5. **The program runs in a sandbox** (macOS `sandbox-exec`, the harness kind of ADR-0102's amendment for ADR-0107):
   its sign-in folders open to write and the keychain to read; no project folder, only the round's own folder; the
   rest of the home folder, other disks, temp folders and the app's data closed. The network is not narrowed to the
   provider's hosts (changed when built): the proxy that does that belongs to the coding part, which the chat does
   not need, and the program's own tools, which could fetch anything, are off.
6. **The conversation stays Wasify AI's.** Messages, attachments, the tree of edits and the search index are kept
   as today. No program session is kept (changed when built): every round gives the program the conversation's text
   up to that point, so editing an earlier message or asking again needs nothing more, and the program keeps no
   session file (`--no-session-persistence`, `--ephemeral`). A picture the person attaches is said in the text, not
   sent.
7. **Cost is said as the program reports it** (ADR-0107 decision 8): "On your plan" and the tokens it reported, or
   a cost where it gives one. A reached plan limit is shown in the program's words with a way back to another model.
8. **Usage is recorded** as tokens on a plan, with no price, if the owner agrees (rule 9 of CLAUDE.md asks that every
   billable action writes a usage event; a plan is billed by its provider, not by us).
9. **The names are plain** (ADR-0107 decision 10): "Claude Code", "Codex", "your Claude plan",
   "your ChatGPT plan". No provider's logo
   or name is part of a name of ours.

## What must be answered before it is built

| | Question | Who |
|---|---|---|
| 1 | **The providers' terms, read again**, for a chat (not coding) through Claude Code and Codex. Anthropic: is a chat that starts the unmodified Claude Code by its own command, signed in by the person, inside the page? OpenAI: does Codex's sign-in with ChatGPT allow an app to start `codex exec` for a chat? | The owner; the reading written into this record |
| 2 | **Google**: answered 2026-11-24, the owner: "no gemini or antigravity is needed. Only claude and chatgpt subscription in the chat for now." | Answered |
| 3 | **A usage event for a plan's tokens** (decision 8): a change to usage-event handling | The owner |
| 4 | **Desktop only** (decision 1) | The owner |
| 5 | **Editing an earlier message** starts a new program session and sends the conversation's text again (decision 6), which spends more of the plan | The owner |

## Stages

| Stage | What | Gate |
|---|---|---|
| **P0, a spike** | Claude Code and Codex by their own commands, signed in with the owner's plans, given only Wasify AI's MCP server: ten turns each from `products/wasifyai-assistant/evals/`, English and Bengali | Measured and written in `docs/spikes/chat-plan-p0.md`: time to the first word per turn; whether the built-in tools stay off; whether every action is called through our server and its card is answered in the window; what usage is reported; how a resumed session holds; how a plan limit looks |
| **P1** | The engine: a text provider for a plan program behind the chat's capability (ADR-0095's seam), the MCP connection of its own kind, the sandbox, session ids per branch | A chat on each program answers, makes a picture through a card and is undone by the person's No; the sandbox's hostile tests pass |
| **P2** | The screens: the Your plan tab with setup and sign-in (Code's parts reused), the plan pill, the limit card | Walked in the real window on each program |
| **P3** | The chat's tool evaluation on each program, against the local and cloud models' scores | Written per program; a program below the cloud models' score says so in its row |

## Built (2026-11-24)

- **P0** (`docs/spikes/chat-plan-p0.md`): Claude Code 2.1.312 on the owner's Max plan, with only our tool server:
  the first word in about 2.3 s, a tool call in about 2 s, English and Bengali. Codex 0.160.1 started in 1.3 s but the
  owner's ChatGPT account was at its usage limit, so no Codex round was run; Codex is built from its documented
  events and tested on a pretended program.
- **P1**: `services/api/src/wasifyai_api/plan_chat.py` (`PlanChat`, `PlanTextProvider` in front of the desktop's text
  provider; only the product `wasifyai-assistant` follows the plan), `plan_tools_server.py`, the routes
  `GET/PUT /desktop/chat-plan` in `plan_chat_routes.py`; tests in `services/api/tests/test_plan_chat.py` (the
  sandbox one on a Mac).
- **P2**: the chat's model button on the main chat (`useChoicesFor("chat", "assistant")`) has a Your plan tab: Code's
  setup and sign-in (`AgentTab`, with the chat's own words) and, for each signed-in program, Its own choice and, on a
  Claude plan, Opus, Sonnet and Haiku (`apps/desktop/src/choices/chat-choices.ts`). Choosing any other model takes the
  chat off the plan.
- **Walked in the real window** (`ui-audit.sh light chat-plan` on a throwaway data folder, 2026-11-24; pictures
  `docs/ui-audit/desktop/chat-plan-*.png`): Your plan lists Claude Code's models; on Haiku a line in English and
  Bengali came in 2.8 s; "Make a picture of a red cat on a sofa" gave the Make a picture card with a line before it;
  Not now was answered politely and nothing was made. Found and fixed: the home's "Get a chat model" card stayed
  while the chat was on a plan.
- **Not built:** a usage event for a plan's tokens (question 3, waits for the owner); P3, the tool evaluation on each
  program; the walk in the real window on Codex.

## Consequences

- People with a plan and no API key can use the chat. This is the reason.
- The chat depends on programs we do not control. A vendor can end plan use in other tools on any day, as happened
  in April 2026; the chat then falls back to the person's other models, and the tab says why.
- Every answer is slower by a program's start (P0 measures how much).
- One more kind of MCP connection, and the chat's cards must work for a program's calls as they do for a model's.
- Nothing changes for chats on a local model or a key.

## Alternatives considered

Options B, C and D above. Doing nothing (the plan only in Code) was the state before this record; the owner asked
for the plan in the chat.

## References

- ADR-0107 and its spikes `docs/spikes/coding-harness-h0.md` to `coding-harness-h3.md` (what the programs report,
  how they sign in, what the sandbox must open).
- ADR-0069 and `docs/mcp-security-review.md` (the server the program would call).
- The providers' pages listed in ADR-0107's references, to be read again for question 1.
- `docs/spikes/google-ai-plans-2026-11.md` (what a Google AI plan gives, and why Google is left out).
