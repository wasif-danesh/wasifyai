# Stage H2: the screens for the person's own Claude Code or Codex (ADR-0107)

Built 2026-11-15 on branch `coding-harness`, after the owner approved the mockup
(`docs/spikes/coding-harness-mockup.html`, "Approve, build H2"). Stage H1 (the engine side) is
`docs/spikes/coding-harness-h1.md`.

## What was built

- **The Your agent tab** in the Code model button (`packages/ui/src/models/AgentTab.tsx`):
  - Before setup: "Use your own Claude Code or Codex", "Set up (694 MB)", then how far it is.
  - After setup, each program shows one of three states:
    - signed in, with its plan and then its models ("Its own choice" first);
    - not signed in, with "Sign in to …";
    - signing in, with "Signing in…", "Open the page again" and Cancel.
  - The button reads "Claude Code · Haiku 5.5".
  - On the window's side: `apps/desktop/src/choices/agents.ts`, and the rows in `code-choices.ts`. A program's models are asked for once per sign-in, because asking starts the program.
- **A session on a program** (`packages/ui/src/code/Code.tsx`, `Asking.tsx`, `use-code.ts`):
  - A note is shown once, before the first session on each program. Sessions start in Plan.
  - The bar shows the program and its model. Where the cost was, a "Your Claude plan" or "Your ChatGPT plan" pill opens to the tokens and cost the program reported, and says there is no limit of ours.
  - The mode menu has two modes. "Ask me" is greyed and says why. "Carry out this plan" goes to Work on its own.
  - Two cards in the program's own words:
    - when the sign-in has ended, with "Sign in to …";
    - when the plan's limit is reached, with "Try again" and "New session on another agent".
- **Elsewhere:**
  - Projects says what each session runs on.
  - Extensions says it is for Wasify AI's own agent only.
  - Settings › Code, "Your agent programs", lists each program's sign-in with "Sign in again" or "Sign in to …", and the part with Remove.
- **A fault the walk found and that is fixed:** choosing a model on the button and then clicking "Choose a folder" straight away started the session on the old model. Code read its choice again only a moment later. This hit every model, not only the programs. The button now tells Code its choice at once, and a test covers it.

## The walk in the real window (the gate)

`WASIFYAI_AUDIT_FOLDER=<empty folder> apps/desktop/scripts/ui-audit.sh light code-agent`, on a throwaway
`DESKTOP_DATA_DIR` with `engine/coding` and `engine/node` linked in. The run used the real engine, the real coding
engine in its sandbox, the programs installed by the part, and the owner's own sign-in on both plans. Pictures:
`docs/ui-audit/desktop/agent-*.png`.

| Step | Claude Code (Haiku 5.5) | Codex (GPT-5.6 Terra) |
|---|---|---|
| Set up from the Your agent tab | 6.4 s (from npm's cache), once for both | |
| The plan's models listed | Its own choice, Opus 5.5, Fable 5.1, Sonnet 5.5, Haiku 5.5 | Its own choice and the plan's models |
| The note before the first session | Shown, then the session started in Plan | Same |
| "Ask me" | Greyed, with the reason | Same |
| A real change in Work on its own | 13.9 s; `prices.py` fixed on disk | 31.5 s; `prices.py` fixed on disk |
| What the program reported | 73,702 tokens in, 981 out, $0.004 | 105,230 tokens in, 683 out, $0.057 |
| Undo this turn | The file was exactly as before, read from disk | Same |
| Projects, Extensions, Settings › Code | Each says what the mockup says | |

The costs are what the programs reported. They count against the owner's plans; nothing was paid by the app.

After the walk, the wording "ChatGPT plan · ChatGPT" was fixed: a plan name that only repeats who pays is now
left out. This is covered by tests, but the walk was not run again for it.

## Not done, or different from the mockup

- **The "+" menu screen.** The session's box has no "+" menu today, so there was nothing to add the line to.
- **A reached plan limit was not seen.** The card shows when the program's words mention a usage or rate limit, a quota or 429. Its shape is still a guess, as the mockup said.
- **The model's name differs a little between places.** The picker uses the program's own name ("5.6 Terra" for Codex). The bar and Projects build one from the model's id ("GPT-5.6 Terra").
- **Not built:** Gemini CLI (open question 3), Scheduled runs on a program and the evaluation (H3), and installs inside a program's session.
- **A turn on a program was not checked in the walk,** because the walk's project had no check set. The H1 gate checked one on each program.
