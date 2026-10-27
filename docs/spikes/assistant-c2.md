# Stage C2: the assistant with outside tools, evaluated 2026-10-27

ADR-0070 decision 8 and its consequence ("if a local model cannot choose among remote tools reliably, remote tools
are offered only with a hosted or larger model"); `docs/phase4-agent-plan.md` stage C2. The runner is
`products/wasifyai-assistant/evals/run_tool_eval.py` (kind `remote`), the cases `evals/cases.yaml`; what is measured
is the assistant as built in C1 and C2: the pair `external_tools` and `call_external` behind one catalogue action, the
connected servers named in the prompt, and `external_tools` answered by the same ranking the app uses
(`rank_tools`) over a catalogue of 5 or 40 outside tools across ten servers.

**Model:** Qwen3 8B Q4_K_M (`unsloth/Qwen3-8B-GGUF`), the language model on this Mac, through the app's own
`llama-server`, context 8,192, thinking off, temperature 0.2. Qwen3 4B and a hosted tier were **not run** (not on
this machine; no key). MacBook Pro M5 Pro, 64 GB; 25 to 34 tokens per second; the server held 7.5 GB.

## The cases

Ten `remote` cases: five asks, each with a catalogue of 5 and of 40 outside tools (an issue search on GitHub, a
file on a files server, a Slack message, the weather, Jira tickets). The model must call `external_tools`, then
`call_external` with the right server and tool and arguments that fit the tool's schema and hold the words of the
ask. Three more cases check that the app's own things still win with 40 outside tools connected (a picture, speech,
a how-to), and one safety case feeds a result from an outside server that orders a delete.

## Results

| Set | Passed | Median per case | The misses |
|---|---|---|---|
| remote, catalogue of 5 | **4 of 5** | 2.7 s | `remote-issues-5`: after the search returned four GitHub tools it asked "Which one would you like to use?" instead of calling `search_issues` |
| remote, catalogue of 40 | **4 of 5** | 2.8 s | `remote-issues-40`: the same |
| the app's own things with 40 connected (3) | **3 of 3** | 1.4 s | none: a picture and speech go to `propose_action`, a how-to to `how_to` |
| safety, including the outside result that orders a delete (5) | **5 of 5** | 2.5 s | none |
| guide (18), rerun with the new prompt | **18 of 18** | 4.1 s | none (`guide-quiz` missed in the first full run, then passed) |

Every `call_external` the model made named the right server and tool with arguments that fit the schema; the two
misses are the model asking the person to choose among four plausible GitHub tools, which is not a wrong call. The
catalogue size, 5 or 40, made no difference: the model's tool list is the same ten tools either way (decision 8),
and the ranking puts the right tool first in both.

The first full run (70 cases, before the two changes below) scored tool 31 of 34, guide 17 of 18, status 2 of 3,
safety 5 of 5 and **remote 2 of 10**. The tool and status sets were not rerun after the prompt change; their misses
(`draw-wide`, `speak-saved-voice`, `voice-design`, `status-video-missing`) are the ones A3 recorded.

## What changed because of the run

- **The prompt names the connected servers.** With "the person connected outside tools" alone the model answered "I
  cannot directly interact with Slack" or reached for `search_notebooks` and the web; with "The person connected
  these outside servers: files, github, jira, slack, weather" it searches them. The app lists the names of the
  person's servers that are not blocked or unhealthy (`external_servers` on the host); with none connected the
  prompt says so, so the model does not look.
- **`external_tools` gives the model each tool's signature** (`search_issues(query: string, repo?: string)`): the
  schema is in the tool's output, which the model never sees, so before this it could not form the arguments.
- Two runner bugs found by the run: the web tools were offered to remote cases although the app offers them only
  with Search on, and the catalogue of 5 did not hold the weather and Jira tools the cases asked for (the model was
  right to say it had none). Both fixed; the numbers above are from the corrected run.

## The per-tier decision (ADR-0070's consequence)

Qwen3 8B, a local model, reaches the right outside tool in 8 of 10 asks with no wrong tool and no unfitting
arguments, keeps the app's own actions and guides, and does not obey an outside result. **Outside tools are offered
to local models**; Settings does not warn. Qwen3 4B, the shelf's recommended model, was not run: if it is checked
later and falls short, the consequence stands (offer them only with a larger or hosted model, and say so).

## Not verified

Qwen3 4B and a hosted model; a real third-party server end to end through the chat (the runner stops at the card);
more than one outside call in a turn; `trusted_read_only` with a real model (its path is unit-tested); languages
other than English.
