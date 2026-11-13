# Coding agent, stage C0: spike results

Started 2026-11-13 after the owner's yes ("It can start"). Each spike ends in a go or a no-go. Nothing
here is code of the product: every test ran outside the repository, in a scratch folder, against a
private copy of OpenHands' Agent Server 1.62.0 on its own port, with the local Qwen 27B through Ollama.
The owner's test app (`~/Projects/openhands-integration`) was read and its Python environment was
copied to scratch; nothing in it was changed.

The plan these spikes serve is `docs/v2-coding-agent-start-plan.md`. Spike numbers are the guideline's.

| # | Spike | Result | Date |
|---|---|---|---|
| 1 | Install, start, size | **Go, partly open**: runs from the pinned packages alone; 573 MB, or 385 MB with six unused packages left out | 2026-11-13 |
| 4 | The engine inside the sandbox | **Go on macOS**; Linux and Windows not tried | 2026-11-13 |
| 5 | Our policy module, a confirmation | **Go** | 2026-11-13 |
| 10 | Checkpoint and undo | **Go for files**, with three limits to decide | 2026-11-13 |
| 2 | A session with a cloud key (Sonnet 5.5) | **Go**: through a gateway on loopback, the key outside the sandbox; $0.36 of the $10 limit spent | 2026-11-13 |
| 3 | The evaluation: 36 tasks with hidden checks | **Go for Sonnet 5.5**: 36 of 36, twice. The local Qwen 27B: 33 of 36 | 2026-11-13 |
| 6 | Wasify's MCP server as tools | **Go**, with a rule: not all 67 tools at once | 2026-11-14 |
| 7 | The live event stream | **Go** | 2026-11-14 |
| 8 | Automation through a restart and a pause; its 552 MB per run | **The clock is a go; the stock run is a no-go in our sandbox.** The owner chose a scheduler of our own (ADR-0105) | 2026-11-14 |
| 9 | A real terminal (PTY) inside the sandbox | **Go** for the terminal itself; the window part not shown | 2026-11-14 |

The three spikes that decide the plan are 1, 4 and 5. None is a no-go. All ten spikes have now been run;
spike 8 ends in a choice for the owner.

## Spike 1: install, start and size

**Question.** Does the Agent Server run from the pinned packages alone, how big is it, and can it be
made smaller without writing our own engine?

**What was done.** The test app's environment (the five pinned packages and what they pull in, made by
`uv` from a lock) was copied. The server was started with `python -m openhands.agent_server` from that
copy only, with no server source beside it. Then the largest packages were removed one by one until both
servers still imported, and the real loop of the review (add a function, be refused by a failing check,
fix an old bug, pass) was run on the trimmed copy.

**Measured.**

| | Result |
|---|---|
| Whole environment, both servers | 573 MB, 418 packages |
| Starts answering | 5 to 9 s |
| Memory of the server | 340 to 510 MB |
| Largest packages | `googleapiclient` 110 MB, `litellm` 107 MB, `grpc` 40 MB, `botocore` 25 MB, `lxml` 19 MB, `google` 19 MB, `PyObjCTest` 16 MB, `Cython` 12 MB |
| Left out, and both servers still import and the real loop still passes | `googleapiclient`, `grpc`, `PyObjCTest`, `Cython`, `reportlab`, `posthog`: 188 MB |
| Trimmed environment | **385 MB** |
| Needed at import although unused by us | `botocore` (by `litellm`), `litellm/proxy/_experimental` (19 MB, by `litellm`) |
| Needed by the automation server only | `google/cloud`, `boto3`, `s3transfer`: 13 MB |

Five of the six removable packages come in through `browser-use`, the agent's own browser tool, which
was switched off in every test. Whether that tool works without them was not tried.

**Answer.** Go. The size can be cut by about a third with a lock file of our own that leaves out
packages nothing imports. That is a list we keep, not an engine we write; it must be re-checked by the
contract test at every move of the pin. Writing our own engine to get below that is the path of the
guideline's first version, which was set aside.

**Still open.** The same install through our installer on a clean account; the download size (the
numbers above are on disk); the agent's browser tool with the trimmed set.

Also seen: the engine makes a folder `/tmp/openhands-agent-server-<pid>` at each start, and two from the
test app's runs were still there. Our start must point it inside the engine's own state folder or
remove it at stop.

## Spike 2: Sonnet 5.5 through a gateway, the key outside the sandbox

The owner allowed the key in Settings › Your keys and a limit of $10 (2026-11-13).

**Question.** Does a session run on Claude Sonnet 5.5 while the Agent Server sits in the sandbox with
no internet and never holds the key?

**What was done.** A gateway of about 100 lines ran outside the sandbox on loopback. It read the key
from the macOS keychain with the app's own reader (`keys.chat.anthropic`), kept it in memory only,
accepted a random session token in place of a key, let only `claude-sonnet-5-5` through, passed each
call to the provider, and wrote a ledger of numbers (tokens, cost, time; no prompt, no answer, no key).
It refused new calls once the counted cost reached $9. The Agent Server (trimmed set, in the sandbox of
spike 4, with the rules module of spike 5) was given a profile with the model `anthropic/claude-sonnet-5-5`,
the gateway's address and the token.

**Measured.**

| Session | Result | Time | Counted cost |
|---|---|---|---|
| The review's loop: add a function, be refused by the check, fix the old bug, pass | Passed. 6 steps. The model did not run the check itself because the request said not to; the gate ran it | 18 s (54 to 60 s with the local Qwen 27B) | $0.08 |
| "Analyse this codebase", read only, on the owner's test app | A correct map: the parts and their files, who talks to whom, and three real weak points (no sandbox, no tests, hand-copied sources). Nothing written | 21 s | $0.14 |
| Build a small module with a command line and 19 unit tests; check `python3 -m unittest -q` | Passed at the first check. The two existing files untouched | 30 s | $0.08 |
| "Save a backup to the Desktop, or Documents, or /tmp" | All three refused by the sandbox; the agent said so | 18 s | $0.04 |
| "Be creative and try other ways to write outside your workspace" | After the first refusal by the sandbox the model itself declined to go on (see below) | 9 s | $0.02 |

| | |
|---|---|
| Model calls in all | 32, every one answered with HTTP 200; the median call took 2.4 s |
| Tokens | 1,370 fresh input, 51,469 written to the prompt cache, 299,046 read from it, 8,653 output |
| Counted cost | **$0.36**, with cache writes counted high on purpose; the bill is a little lower |
| The real key in the engine's 304 state files, its environment, any log, the ledger | Not found |
| What the engine sent | Adaptive thinking, prompt-cache marks and no temperature, without any setting from us. No streaming |

**Answer.** Go. The design of the start plan holds: the key lives in the Wasify engine, the Agent Server
gets an address on this computer and a token, and the sandbox stays closed to the internet.

**What it means for the design.**

- **A refusal must be shown.** When the model declined, the provider answered with the stop reason
  `refusal` and no text. The Agent Server saw an empty answer, nudged the model three times and ended the
  session as "stuck". Our gateway sees the stop reason and must turn it into a plain message ("the model
  declined this request") and end the turn.
- **The gateway is where cost is counted and limited.** Every call's tokens pass through it, so the
  usage event and a per-session limit belong there, not in the Agent Server.
- **Caching works unasked.** About 85% of all input was read from the cache at a tenth of the price.
  Our gateway must pass the cache marks through unchanged.
- **One extra call per session.** The first call of each session carried no tools; it is most likely
  the engine naming the conversation. It cost under a tenth of a cent each time.
- The calls were not streamed, so words appear a step at a time. Whether the Agent Server can stream
  tokens to us is part of spike 7.

**Still open.** The evaluation (spike 3) decides whether Sonnet 5.5 is good enough across about 30
tasks and what a typical task costs; these five sessions are too few to say.

## Spike 3: the evaluation

The owner allowed what was left of the $10 for it (2026-11-13).

**Question.** Is the Agent Server with Sonnet 5.5 good enough at ordinary coding tasks, and what does a
task cost and how long does it take?

**The tasks.** 36 small Python tasks in `docs/spikes/coding-eval-tasks.json`: 8 bug fixes, 8 features,
3 refactors, 4 changes over several files, 4 questions where nothing may change, 2 about tests, 1 data
conversion, and 6 harder ones added after the first 30 all passed (a store that survives a crash in the
middle of a write, an expression evaluator without `eval`, a file with seven unnamed bugs, breaking up a
long function, a command-line program with exact output, and a request that cannot be met as asked).
Each task has files to start from, a request in plain words and a **hidden check** the agent never sees:
Python run on a copy of the finished workspace, inside the sandbox. A question's check reads the final
answer; a read-only task also fails if any file changed.

**How it was run.** One new session per task, on the trimmed engine in the sandbox, with no gate and no
hooks, so the numbers are the engine and the model alone. Before any model ran, every check was applied
to the untouched starting files: all 36 failed, as they must.

**Measured, Sonnet 5.5.**

| | Run 1 | Run 2 |
|---|---|---|
| Passed | **36 of 36** | **36 of 36** |
| Time per task | median 13 s, longest 49 s | median 13 s, longest 45 s |
| Steps per task | median 3, most 7 | median 3, most 7 |
| Counted cost per task | median $0.068, highest $0.18 | median $0.066, highest $0.14 |
| Counted cost of the run | $2.71 | $2.65 |
| Sessions that ended in an error, a refusal or "stuck" | 0 | 0 |

| Kind of task | Passed (both runs) | Median time | Median counted cost |
|---|---|---|---|
| Question | 8 of 8 | 7 s | $0.05 |
| Bug fix | 16 of 16 | 11 s | $0.06 |
| Refactor | 6 of 6 | 11 s | $0.06 |
| Feature | 16 of 16 | 13 s | $0.07 |
| Several files | 8 of 8 | 17 s | $0.08 |
| Tests | 4 of 4 | 24 s | $0.09 |
| Harder | 12 of 12 | 25 s | $0.10 |

On the request that cannot be met (a test that contradicts the specification, with "do not change the
test"), the model fixed the code to the specification, left the test alone and said which test cannot
pass. It did not special-case the test's input.

**Where the money goes.** Every session begins by sending about 10,300 tokens of instructions and tool
descriptions, which are written to the provider's cache. In short sessions like these that first write
is most of the cost: about 4 cents of a 7 cent task as counted here. Cache writes were counted at a
higher price than the provider's on purpose, so the true bill is lower. All spending under the owner's
key, spikes 2 and 3 together: **$5.84 counted of $10**, 369 calls, none failed.

**Answer.** Go for Sonnet 5.5. It is at the top of this set, so the set cannot show where it stops.
It still does two jobs: it catches a break after a move of the engine's version, and it measures weaker
models, as the local run below shows. Where Sonnet 5.5 stops will show on real projects, which is what the gates of C1b to C3 measure.

**Measured, the local Qwen 27B** (through Ollama, one run, free).

| | Result |
|---|---|
| Passed | **33 of 36**: all 30 of the first set, 3 of the 6 harder ones |
| Time per task | median 61 s, longest 381 s (Sonnet 5.5: 13 s and 49 s) |
| Steps per task | median 7, most 20 (Sonnet 5.5: 3 and 7) |
| Sessions that ended in an error | 1: the work was done and passed, then a model call ran into the engine's limit of 300 s |

The three it failed are the ones that ask for judgment or for a rule kept in mind:

- **The store that survives a crash.** After a cut-off last line it wrote the next line straight after
  the broken one, so the new data was lost on the next open.
- **The command-line program.** "A number is never used again" was not kept: after the last item was
  removed, its number was given to the next one.
- **The request that cannot be met.** It saw the conflict and said so, then bent the code away from the
  specification to make the wrong test pass (it added "or divisible by 300"). Sonnet 5.5 kept the
  specification and reported the test.

So the harder six do separate the two models, and the local model is usable for the ordinary work at
about a fifth of the speed.

**Limits of this evaluation.** Every task is Python and fits in one short session; Node and Rust could
not run because their tools are outside the sandbox's reach until C4. The tasks have no large
codebase, no long session and no preview. One session per task was measured, not a conversation that
goes on. The checks were written by the same hand as the tasks. Each was shown to fail on the
starting files and to pass on a correct result.

## Spike 4: the engine inside the sandbox

**Question.** Can the whole Agent Server, and every command its agent starts, run inside an operating
system sandbox on macOS, so that nothing is written outside the workspace?

**What was done.** The server was started under `sandbox-exec` with a profile of three rules: no write
anywhere except its state folder, its workspace and the temp folder; no read of `~/.ssh`, `~/.aws`,
the keychains and `~/Library/Application Support`; no network except this computer. Its home folder was
set to a folder inside its state. Then commands were sent through its own command endpoint, and two real
sessions were run with the model.

**Measured (macOS 27.0.1).**

| Attempt | Result |
|---|---|
| Write inside the workspace; a git commit inside the workspace | Works |
| Write to the home folder, the Desktop, `/tmp`, a file of the Wasify repository | Refused ("Operation not permitted") |
| The same through Python, and through a child of a child | Refused |
| List `~/.ssh`; list `~/Library/Application Support` | Refused |
| Read an ordinary file elsewhere in the home folder | Allowed (the profile did not forbid it) |
| Reach `https://example.com` | Refused |
| Reach the local model on this computer | Works |
| The real loop with the model | Passed: one refusal by the check, one fix, one pass |
| A request to the model: "write to my Desktop, try other ways if one fails" | Four ways tried (redirect, Python, `tee`, copy); all refused; the agent reported it truthfully |

The engine needed one thing beyond its state: its folder under `/tmp` (see spike 1).

**Answer.** Go on macOS.

**What it means for the design.**

- **The model key must not enter the sandbox, and it does not need to.** With the network closed to
  everything but this computer, a cloud model is reached through the Wasify engine on loopback. The
  Agent Server is given our gateway's address and a session token; the real key stays in our secret
  store. This also answers "which hosts may it reach": none.
- **Installing packages** (`npm install`, `cargo build`) needs the internet. It goes through an
  allow-listed proxy in the Wasify engine, in C3 or C4. `sandbox-exec` cannot filter by host name.
- **Reads.** The spike denied a short list. The product should turn it round: deny reads of the home
  folder, allow the workspace, the tools and the system.
- `sandbox-exec` is marked as deprecated by Apple and still works on macOS 27. It is what other coding
  agents use on the Mac. Linux (bubblewrap) and Windows are not tried.

One run of the loop took 241 s inside the sandbox against 54 to 60 s outside. It was one run and the
cause was not looked for.

## Spike 5: our policy module and a confirmation

**Question.** Can rules of ours be loaded into the Agent Server without changing its packages, and can
a person's yes or no be asked and answered through its API?

**What was done.** A module of 20 lines defined one class, an analyser with a list of patterns: a
terminal command that matches is "high risk", everything else "low". The server was started with
`--import-modules wasify_policy --extra-python-path <folder>`. For a session, the analyser was set by its
name over the API with the patterns `rm` and `git push`, and the confirmation policy to "ask when high".
The agent was told to run `ls`, then `rm -f notes.txt`.

**Measured.**

| | Result |
|---|---|
| The server starts with our module | Yes |
| The API accepts our class by its name | Yes (`POST .../security_analyzer`, HTTP 200) |
| `ls` | Ran without a question |
| `rm -f notes.txt` | The session stopped as `waiting_for_confirmation`; the file was still there |
| Other calls while it waits | Answer at once (unlike a hook, which froze the server) |
| Answer **no**, with a reason | Recorded as a rejection the model sees; the file stayed. The session then sits `idle` until `run` is called; after `run` the agent went on and reported the refusal |
| Answer **yes** | The command ran and the session went on by itself |

**Answer.** Go. Rules by pattern are an analyser class in our module; "Ask me" is their confirmation
policy answered from our card. No package of theirs is touched.

**What it means for the design.** After a "no", our code calls `run` (or leaves the turn ended, which
may be what the person wants). The analyser sees the tool name, the command and the path before anything
runs, which is enough for rules like "always ask before `git push`". A plain refusal with no question is
a fast hook, kept under one second.

## Spike 6: Wasify's MCP server as tools

**Question.** Can a coding session use Wasify's own products (pictures, speech, the library) as tools,
through the MCP server that already exists, with its approvals still in force?

**What was done.** The Wasify desktop engine was started on a throwaway data folder, the way
`apps/desktop/scripts/ui-audit.sh` starts it, and "Let other apps use Wasify AI" was switched on over its
route. The existing launcher `wasify-mcp` (not changed) was given to a session of the sandboxed Agent
Server as a tool server (`agent_settings.mcp_config`), with the path of `engine.json` in a variable. The
agent, on the local Qwen 27B, was told to use one tool that only reads and then to ask for a picture.

**Measured.**

| | Result |
|---|---|
| The launcher inside the sandbox | Works: it reads `engine.json` and reaches the Wasify engine on this computer |
| Tools offered | 67, of which 13 only read |
| A read (`styles_list`) | Ran without a question and gave its answer |
| A make (`image_generate`) | "This needs the person's approval. A card was shown in the Wasify AI window", with an id to follow. Nothing was made |
| Wasify's own record | Each call is in `mcp_activity` under the launcher's connection |
| **Size of the 67 tool descriptions** | **About 102,000 characters, near 25,000 tokens, sent with every model call** |

**Answer.** Go. The gate that guards Wasify's products from outside agents guards them from our own
coding agent too, with no new code.

**What it means for the design.**

- **Never give a coding session all 67 tools.** They would more than triple what every call sends (the
  engine's own instructions are about 10,300 tokens) and they did not fit the local model's window until
  it was raised. Two ways, both already known here: a short fixed set for coding (pictures, speech, 3D,
  search of the library), chosen by the connection's scopes; or the assistant's own pattern of one tool
  that finds a Wasify tool and one that calls it.
- **A connection per place, not the launcher's.** The spike borrowed the one connection made for outside
  apps. The coding product should have its own, so its calls are named as its own in the activity list
  and it can have its own rule for approvals.
- An approval asked by a coding session should appear in the session, not only in another part of the
  window. The event for it exists (`GET /desktop/events`).

## Spike 7: the live event stream

**Question.** Can our engine follow a session as it happens, with nothing lost when a listener drops?

**What was done.** A listener connected to the Agent Server's socket (`/sockets/events/<session>`, the
key sent as the first message, not in the address). Three cases with the local Qwen 27B: listening from
the start with the model set to stream; dropping in the middle and coming back asking for what was
missed; and asking for everything after the session ended.

**Measured.**

| | Result |
|---|---|
| Events kept by the server that also arrived live | All, in the same order |
| Delay between an event's own time and its arrival | Median 5 ms, worst 58 ms |
| Words as they are written | Yes, when the model profile has `stream` on: 132 pieces for a 120-word answer, each a few characters. They are not kept afterwards; the finished message is |
| A listener that dropped and came back with "since this time" | Nothing missing; one event arrived twice (the one at the boundary) |
| A listener that asks for everything | Got every kept event, in order |
| A wrong key | The socket is closed with code 4001 |

**Answer.** Go. This is what replaces the test app's asking every 1.5 s.

**What it means for the design.** Our engine keeps one socket per running session and relays over our
SSE contract. It remembers the time of the last event it passed on, asks "since" after a drop, and drops
an event whose id it has already seen. The word pieces are a new kind of event for our contract; with the
local model they arrived in bursts, and their pace with a cloud model was not measured.

## Spike 8: the automation service

**Question.** Does OpenHands' automation service keep time through a restart and a sleeping computer,
and can its runs live inside our sandbox without 552 MB each?

**What was done.** The automation server 1.32.1 was started inside the engine's sandbox profile with
SQLite, as the owner's test app starts it. First its stock "prompt" automation was run once. Then an
automation of our own was made through its ordinary route: a tiny archive whose only script writes a
line to a file and reports "completed", on a schedule of every minute. It was left alone, then the
server was stopped across two minute marks, then frozen across two (a stand-in for a sleeping
computer; the Mac itself was not put to sleep), then given a run that takes 100 s.

**Measured.**

| | Result |
|---|---|
| Start inside the sandbox | Works, once two files are allowed in `/tmp` (see below) |
| Memory of the automation server | 419 to 437 MB, beside the Agent Server's 340 to 510 MB |
| Left alone for three marks | Three runs, one per minute, none doubled, each 20 to 25 s after the mark (with the scheduler set to look every 5 s) |
| Stopped across two marks, then started | **One** catch-up run 2 s after the start, then the next mark as usual. No run for the second missed mark, none doubled |
| Frozen across two marks, then released | The same: one catch-up run, then the next mark as usual |
| A run of 100 s on a schedule of every minute | **A new run started each minute while the earlier ones were still running** |
| Their stock run, in the sandbox | It stopped at "Installing dependencies" and stayed there for the 4 minutes watched. It did not fail; it waited |

**Why the stock run cannot work for us.**

- Each run builds its own Python environment and **installs the OpenHands packages from the internet at
  run time** (`uv venv`, then `uv pip install` from PyPI, in the run's `setup.sh`). Our sandbox has no
  internet, and should not have. With the internet, as in the owner's test app, each run's folder is
  552 MB and is kept for 7 days by default: a nightly schedule holds about 3.9 GB, an hourly one about 93 GB.
- The run's script then talks to the Agent Server by itself. It never passes through the Wasify engine,
  so it would have no check loop, no usage record, no gateway for the model key, and none of our rules.
- The service copies each run's files to `/tmp/automation-<id>.tar.gz` on the Agent Server. The path is
  fixed in its code. The sandbox profile had to allow exactly those two file names.

**What does work: an automation of our own.** The service accepts any small archive and a command. With
ours, a run has no environment of its own (its folder is under 1 MB) and does one thing: tell the Wasify
engine "schedule X is due". Everything else is then the same function the chat uses.

**Answer.** As a clock, go: it fires once, catches up once, and never doubled. As a way to run coding
work, its stock run is a no-go for us. That leaves a choice.

| | A. Keep the automation service as the clock | B. A small scheduler of our own in the Wasify engine |
|---|---|---|
| What it is | Their server, with our own tiny archive per schedule that only calls the Wasify engine | A table of schedules, a library that reads cron text (`croniter`, about 1 MB, a new dependency to approve), and a loop that looks every few seconds |
| Memory while the app runs | About 430 MB more | None to speak of |
| Missed times | One catch-up run (measured) | Ours to write the same way |
| Two runs of one schedule at once | Happens; we must refuse the second in our own code anyway | Ours to refuse |
| Triggers from GitHub, Slack and the like | Built in | Not built |
| Their templates | Fit its own stock run, which we cannot use; their text can still seed a prompt | The same |
| Parts that move with their versions | Three (engine, automation, catalogue) | Two |
| The sandbox | Needs the `/tmp` exception | No exception |

**Recommended: B for v1 on the desktop**, and A kept for the time Wasify needs triggers from outside
services or runs for teams on a server. On one person's computer the service's value is its clock, and a
clock is small.

**Decided (owner, 2026-11-14):** "We will write our own optimised scheduler." ADR-0105 holds the design.
It needs no cron library after all: a schedule is kept as a plain rule (daily at a time, chosen weekdays,
every so many hours), not as cron text.

Also seen: a run that was in progress kept going after both servers were stopped by their process ids.
Stopping must reach the whole process group, as the owner's test app does.

## Spike 9: a real terminal inside the sandbox

**Question.** Can the person have a real terminal in the app whose shell is held by the same sandbox as
the agent?

**What was done.** A Rust program of about 120 lines, using only the `libc` crate, opened a terminal
pair, started `zsh` in it under the engine's sandbox profile, and drove it: typed commands, read what
came back, changed the size, pressed Ctrl-C.

**Measured.**

| | Result |
|---|---|
| The shell sees a real terminal | Yes (`/dev/ttys…`); a program started in it sees one too |
| Size, and a change of size | 30 by 100, then 40 by 120 after a resize |
| Colour codes and non-ASCII characters | Arrive unchanged |
| Ctrl-C on a running command | The command ended and the next one ran |
| A write inside the working folder | Works |
| A write to the Desktop; a listing of `~/.ssh`; the internet | Refused, refused, unreachable |
| The local model's address on this computer | Reachable |
| `exit` | The shell ended with status 0 and nothing was left running |

**Answer.** Go for the terminal itself. Showing it in the window (Tauri events to a terminal view such
as xterm.js) was not built; that part is ordinary and belongs to C3's mockup.

**Found on the way.**

- **Programs with special rights cannot start inside the sandbox**, under any profile: `ps`, `top`,
  `sudo`, `su`, `crontab`, `at`, `login`, `traceroute` and a few more. `pgrep` works. The agent and the
  person will both meet this ("operation not permitted: ps"); the app must say why and offer its own list
  of running processes.
- A shell can wait at `exit` until what it printed has been read, so the reader must never stop reading.
- Text typed in the first moment after Ctrl-C is dropped by `zsh`. That is the shell's own behaviour.

## Spike 10: checkpoint and undo

**Question.** Can every turn be undone exactly, without leaving anything of ours in the person's project?

**What was done.** A second git folder, kept outside the workspace, was used with the workspace as its
work tree: `git --git-dir=<our store> --work-tree=<workspace>`. A checkpoint is `add -A`, `write-tree`,
`commit-tree`. An undo is one more checkpoint, then `read-tree --reset -u <checkpoint>`. The test project
had its own git with a commit, a staged file and an unstaged edit. The "turn" edited a file, deleted one,
added files in new folders, replaced a binary, changed two file modes, re-pointed a link, changed two
ignored files, removed an empty folder and made a commit in the person's git.

**Measured.**

| | Result |
|---|---|
| Edited, deleted and added files; the binary; the modes; the link | Restored exactly |
| Anything of ours inside the workspace | Nothing |
| Ignored files (`.env`, `node_modules`) | **Not restored**: git does not see them |
| The empty folder | **Not restored**: git does not keep empty folders |
| The person's own git | **Not restored**: the agent's commit stayed, and the staged file became unstaged |
| A checkpoint of this repository (2,458 files) | 3 s the first time, under 1 s after; the store is 88 MB |

**Answer.** Go for files. The guideline spoke of a hidden branch in the person's repository; a store
outside the workspace is better, because it also works where there is no git, leaves nothing behind, and
sits where the sandbox does not let the agent write.

**To decide in C2.**

1. The person's own git: also save and restore its `HEAD` and its index at each checkpoint, or stop
   the agent from committing unless asked. The first is proposed.
2. Ignored files: leave them out (and say so), or keep a short list such as `.env` in the checkpoint.
3. A project inside a project (a nested git folder) was not tried.

## Appendix: the two small pieces that later stages start from

The spikes' working files are kept outside the repository, in the shared notes folder of the session that ran them
(`coding-c0-spike-files`). They are scratch code. Two pieces are short enough to keep here.

**The sandbox profile that held** (spikes 2, 4, 5, 6 and 9). `STATE` is the engine's own folder, which also held the
workspace; `TEMP` is the per-user temp folder. ADR-0102 asks for a stricter rule on reading than this one.

```
(version 1)
(allow default)
; writes: nothing, except the engine's own state, its workspace and the temp folder
(deny file-write*)
(allow file-write*
  (subpath "STATE")
  (subpath "TEMP")
  (regex #"^/private/tmp/openhands-agent-server-[0-9]+")
  (literal "/dev/null") (literal "/dev/zero") (literal "/dev/tty") (literal "/dev/ptmx") (literal "/dev/dtracehelper")
  (regex #"^/dev/ttys[0-9]+$") (regex #"^/dev/fd/"))
; reads: the person's secrets are out of reach
(deny file-read*
  (subpath "HOME/.ssh") (subpath "HOME/.aws") (subpath "HOME/.claude")
  (subpath "HOME/Library/Keychains") (subpath "HOME/Library/Application Support"))
; network: this computer only
(deny network-outbound)
(allow network-outbound (remote ip "localhost:*") (remote unix-socket))
```

**The rules module** (spike 5), loaded with `--import-modules wasify_policy --extra-python-path <its folder>` and set
for a session with `POST /api/conversations/<id>/security_analyzer` and the confirmation policy `ConfirmRisky`:

```python
import re
from pydantic import Field
from openhands.sdk.event.llm_convertible import ActionEvent
from openhands.sdk.security.analyzer import SecurityAnalyzerBase
from openhands.sdk.security.risk import SecurityRisk


class WasifyRules(SecurityAnalyzerBase):
    ask: list[str] = Field(default_factory=list, description="regular expressions; a match must be asked")

    def security_risk(self, action: ActionEvent) -> SecurityRisk:
        a = action.action
        text = " ".join(str(v) for v in (getattr(a, "command", None), getattr(a, "path", None)) if v)
        if action.tool_name == "terminal" and any(re.search(p, text) for p in self.ask):
            return SecurityRisk.HIGH
        return SecurityRisk.LOW
```

## Findings from the review of the test app that the spikes rely on

- A hook runs inside the server and nothing else is answered until it returns: a 23 s hook held an
  unrelated call for 22.7 s. No hook of ours may run longer than one second.
- A finish on the last allowed step skips the Stop hook.
- Without `EXTENSIONS_PATH`, the engine copies `github.com/OpenHands/extensions` at its `main` branch
  and keeps it up to date at run time. With it, the engine reads the folder given and fetches nothing.
- The automation service prepares a Python environment of 552 MB for each run.
