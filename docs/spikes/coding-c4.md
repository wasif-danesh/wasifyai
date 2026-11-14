# Coding agent, stage C4: a preview, Node, a first starter and Wasify AI's own products

Written 2026-11-15 on the owner's Mac (M5 Pro, macOS 27.0). The stage is piece 8 of
`docs/v2-coding-agent-start-plan.md`, section 9, taken before piece 7 (the Extensions screen) by the owner's
choice ("C4 first"). What is built is described in `docs/desktop/coding.md`; the decisions are the amendments
of 2026-11-15 to ADR-0101 and ADR-0102.

## The owner's answers behind it (2026-11-15)

| Asked | Answer |
|---|---|
| May Node be an optional part, downloaded from nodejs.org (about 50 MB, checksum checked)? | "Yes, download it" |
| The Browser tab needs a second webview in the real window, which cannot be seen from here | "Preview now, Browser after": the Browser tab is a piece of its own |
| Wasify AI's own products as tools of the agent | "A short set now" |
| Routes and actions for the preview and a new project, and the page shown from this computer's address | "Yes, add them" |

## The gate

The guideline's gate for C4: "Build a to-do web app with a logo" ends in a running app with a picture made by
Wasify, on a clean computer.

It was measured with `ui-audit.sh light code-build`: the real window's page with the real engine behind it, on
the throwaway data folder `~/Library/Application Support/ai.wasifyai.coding-c1b`, the local Qwen 27B (Ollama)
as the agent's model, and an empty throwaway folder for the project. "Clean" here means: no Node the sandbox
could read but the optional part's, and nothing installed for the project. The picture was made by the
picture engine and model the owner's own app has (the throwaway data folder was given a link to that engine
and the models' drive; nothing of the owner's was written).

| Gate | Result | How it was measured |
|---|---|---|
| A new project from the starter | **Passed.** "Start in a new, empty folder" wrote the starter's nine files into a new folder and opened a session in "Ask me" with its check (`npm test`) and preview (`npm run dev`) set | The walk, step 0; `test_a_new_project_is_made_from_the_starter_...` |
| The starter runs with nothing installed | **Passed.** Its page was in the Preview tab 1.4 s after "Start the preview", on a port of this computer only; its own check passed inside the sandbox in 0.1 s | The walk, steps 1 and 2 |
| "A to-do web app with a logo" is built | **Passed.** One turn of 8 min 46 s (20 steps, 6 files changed): the agent wrote the page, the logic and its tests, asked for the logo, and ran the tests itself. The project's check passed in round 1 and the bar says "Passed" | The walk, step 3 |
| The picture is made by Wasify AI, after a question | **Passed.** The card came 104 s after the request with the agent's own words for the logo. Nothing was made before the yes. After it, `image.generate` ran for the person and `assets/logo.png` was in the project 347 s later (most of it the picture engine starting and loading its model): a PNG of 1024 by 1024, 387 KB, also in the library | The walk, step 3; the file read from disk |
| It ends in a running app | **Passed.** In the Preview tab: "Buy bread" typed and added appeared in the list; the logo was shown (the picture had loaded); after "Load again" the to-do was still there | The walk, step 4, driving the page inside the frame |
| Node from the optional part | **Passed.** Set up for real through the part: 53.1 MB fetched and checked, 199 MB on disk, 5 s. Inside the sandbox `node`, `npm` and `npx` are the part's; a file was written in the project and a port opened on this computer | By hand, through `NodeComponent`; `test_the_agent_finds_node_...` |
| The preview is held by the sandbox | **Passed.** A program started as the preview could not write beside the project and could not list the person's home; it served the project's page; Stop left no process | `test_a_preview_runs_inside_the_projects_sandbox_...` |
| `wasify-make` inside the sandbox | **Passed** with a pretended picture on the real engine: asked first even in "Work on its own", made by the app outside the sandbox, the command inside read how it went | `test_wasify_make_is_asked_first_...` |
| `make test-coding` | **Passed: 51** (30 hostile tests, 21 of the sessions; 3 are new) | The real server in its sandbox, a scripted model |
| `make test`, `make lint` | **Passed** on the final tree: ruff, the format check, pyright (0 errors), the design check, Biome and the TypeScript check; 3,745 Python tests passed and 494 skipped; 1,294 TypeScript tests (178 client, 220 web, 108 desktop, 788 screens) | The full chains, run while no coding engine was running |

**No paid run was made in this stage.** The gate was measured with the local model only. Claude Sonnet 5.5 was
not run on it; of the 25 dollars the owner allowed, about 3.75 were used, all in stage C3.

## What is built

| Part | Where |
|---|---|
| "Node for coding projects" as an optional part, pinned for the Mac | `services/api/src/wasifyai_api/components/node.py`, `components/manifests/darwin-arm64.yaml`, `assemble.py` |
| Node on the sandbox's path and readable; our own commands first on it | `coding_server.py` (`_environment`, `_node_root`, `_tools`) |
| The preview: the project's command in its sandbox, found by its port | `products/wasifyai-code/wasifyai_code/preview.py`, `runtime.py` (`preview`, `start_preview`, `stop_preview`) |
| The Preview tab | `packages/ui/src/code/Preview.tsx` |
| The first starter and "Start in a new, empty folder" | `starters.py`, `starters/web/`, `runtime.py` (`start_new`), `packages/ui/src/code/NewProject.tsx` |
| A picture or speech from Wasify AI's own products | `assets.py`, `services/coding-engine/wasify-make`, `rules.py` (the kind `make`), `runtime.py` (`_make`) |
| Routes and actions | `routes.py`; `actions.py` (`code.session.preview`, `code.project.new`), `docs/help/` |
| The walk of this stage | `apps/desktop/scripts/ui-audit-pictures.mjs`, scenario `code-build` |

## Found on the way

Each was found by a run in the real sandbox or the real window, not by reading.

1. **The sandbox cannot see a Node kept in the person's home folder.** On this Mac Node is under `~/.nvm`. So
   inside the sandbox there was no `node` and no `npm` at all, for the agent, the check, the preview and the
   person's terminal alike. This is why Node had to be a part of ours and not "what the computer has".
2. **The sandbox cannot keep a program from listening to other computers.** A server bound to `0.0.0.0`
   inside it answered on this computer's network address, with and without an inbound rule in the profile.
   The preview therefore looks at what the program really listens on, and the tab says when it is more than
   this computer. Our own starter listens on `127.0.0.1` only.
3. **`localhost` is not `127.0.0.1` for a server.** Node binds `localhost` to the IPv6 address alone. The
   preview's address is therefore `http://localhost:<port>`, which reaches either, and the window's content
   rule now allows frames from `localhost` too.
4. **A real model does not run the command alone.** Told to run `wasify-make` "alone, as the whole command",
   the local model wrote `cd <the project> && wasify-make ...`, and once `... && mkdir -p assets && ...`. The
   first reader refused both, the agent was told "run it alone", and no picture was made. Going into a folder
   of the project and making a folder in front of the command are now read; anything else in front or behind
   is still refused.
5. **The agent asks again before it is done.** In one run, after the picture, it wanted to stop a server it
   had started itself and remove its log, with `kill` and `rm` in one command; in "Ask me" that is a card
   ("The agent wants to delete files"), and the turn waited for it. That is the product as designed. The walk
   now answers every card as a person would.
6. **Two buttons are called Stop** once a preview runs beside a working agent: the chat's and the preview's.
   Each is in its own named region, and the walk now names the region.
7. **A picture takes minutes the first time.** 347 s from the yes to the file, of which the model's own work is
   a small part: the picture engine was started and loaded its model. The step's line in the
   chat now says "Wasify AI is making a picture. This can take a few minutes" for that time; that line was
   added after the walk and is checked by a test, not by a walk.

## Decided while building, for the owner to see

1. **Wasify AI's own products reach the agent through one command, `wasify-make`, and not through the MCP
   server.** The MCP server and its launcher are not touched. Nothing of the app is reachable from inside the
   sandbox; the app makes the file itself after the question. This replaces what `docs/spikes/coding-c1b.md`
   had decided for this stage (a connection of the coding product's own).
2. **The short set is two: a picture and speech.** "List what it made" is not a tool: what is made is a file
   in the project, which the agent can see, and an item in the library, which the person can.
3. **A picture is asked about in every mode**, also in "Work on its own", until allowed for the project.
4. **The preview is a frame in the window, not a second webview.** It needed no change to the Tauri shell but
   one line of its content rule.
5. **The preview and the person's terminal may fetch from a package index at any time; the agent's commands
   only after an install was let through.** A preview is the person's own, like their terminal.
6. **A starter's check and preview are set when it is made**, though for a folder of the person's a check is
   only ever suggested: the starter is ours, and its commands are part of it.
7. **The picture engine of the owner's own app was used for the gate**, by a link from the throwaway data
   folder to `engine/comfyui` and with the models' drive named in `DESKTOP_MODELS_DIR`. Nothing was written
   there. The link is still in the throwaway folder.

## Not measured, not built

- **The Browser tab**, by the owner's choice: its own piece.
- **The real Tauri window was not opened.** The walk drives the real window's page in a browser. The frame
  under the window's own content rule (changed in this stage) was therefore not seen.
- **Claude Sonnet 5.5 on the gate.** The local model alone was run.
- **Speech through `wasify-make`.** It is written the same way as a picture and tested with a pretended
  product; no real speech was made.
- **The Agent Server sees a newly set-up Node only from its next start.** The check, the preview and the
  terminal see it at once. Nothing restarts the server when the part is set up.
- **Node on other computers.** Only the Mac with Apple silicon has a pin; elsewhere the part says it is not
  available, like the coding engine.
- **A preview that needs packages** (`npm install` first). The starter needs none; a project that does must
  be installed in the terminal or by the agent first.
- **3D models, music or video** through the same command.
- **A picture the agent can look at**, and the agent looking at the preview's page.
- **Other managed tools** (a Python with `pytest`, Rust, Go), and more starters.
- **"Show what is running"**, still: a preview is one more thing it would list.

## For the next stage

- The Extensions screen (X2) is next by the plan; the Browser tab is a small piece of its own that needs the
  owner's eyes on the real window.
- `CLAUDE.md` (in the main checkout only) was brought up to date with this stage.
