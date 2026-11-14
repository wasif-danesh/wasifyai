# wasifyai-code

The coding agent's product (ADR-0101 to ADR-0105; plan in `docs/v2-coding-agent-start-plan.md`).

**Wired in: a coding session that only reads (stage C1b), with no screen.** The engine finds the product by
its entry point, opens its store, and serves its three actions and its routes. What is built and how it is
held is in `docs/desktop/coding.md`; the gate and what was not measured in `docs/spikes/coding-c1b.md`.

| File | What it is |
|---|---|
| `wasifyai_code/place.py` | The interface between the product and an engine (start, send, run, stop, follow, answer), and a pretended place for tests |
| `wasifyai_code/client.py` | The one real place: this computer, OpenHands' Agent Server inside its sandbox. **The only file that knows the Agent Server's API** |
| `wasifyai_code/events.py` | The Agent Server's events in the place's own words, and how a turn ended |
| `wasifyai_code/agent_types.py` | The shapes read from the Agent Server. Generated: `scripts/coding-engine-types.py` |
| `wasifyai_code/runtime.py` | The sessions in flight: start, a turn, Stop, the relay inside the engine, which folders may be a workspace |
| `wasifyai_code/actions.py`, `routes.py`, `index.py` | `code.session.start`, `send` and `stop`; `/products/wasifyai-code/code/...`; sessions in search |
| `wasifyai_code/store.py` | The rows: workspaces with their check command, sessions with their mode and cost, turns with their answer, checks, checkpoints, schedules and schedule runs. One class on SQLite or Postgres; every row carries `tenant_id` and `product_id` |
| `wasifyai_code/checks.py`, `loop.py`, `checkpoints.py`, `schedules.py` | Library code for the stages that edit, run and schedule (C2, C3, C6). Not used by a session that only reads; `docs/spikes/coding-cores.md` |
| `evals/` | The 36 evaluation tasks with hidden checks and their runner, on the pretended place in tests and on the real one with `--data` |

```
uv run pytest products/wasifyai-code                          # SQLite; the Postgres half skips when none answers
DATABASE_URL=postgresql://... uv run pytest products/wasifyai-code   # both
uv run pytest services/api/tests/test_coding_sessions.py services/api/tests/test_coding_gateway.py   # with the engine's parts, on the fake Agent Server
uv run python products/wasifyai-code/evals/run_eval.py --start       # every hidden check must fail on the starting files
CODING_OLLAMA_URL=http://127.0.0.1:11434 uv run python products/wasifyai-code/evals/run_eval.py \
    --data "<app data with the coding engine set up>" --model qwen-27b-ollama      # the real engine, a local model
uv run python scripts/coding-engine-types.py --check          # the generated types are in step with the excerpt
```

The tests use a real git, real SQLite (and Postgres), real child processes and, in `services/api/tests`, the
engine's real supervisor and gateway against the fake Agent Server. Nothing in them needs a model, a network
or the coding engine. The same calls against the real, pinned server are `make test-coding`.

The product imports nothing from the Wasify API and nothing from OpenHands: the coding server and the model
gateway are read from the engine's services (`state.coding_server`, `state.coding_gateway`).
