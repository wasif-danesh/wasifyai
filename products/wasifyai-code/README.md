# wasifyai-code

The coding agent's product (ADR-0101 to ADR-0105; plan in `docs/v2-coding-agent-start-plan.md`).

**Not wired into the app yet.** What is here is the part that needs no screen and no running engine,
as tested library code. The package has no `wasifyai.products` entry point, no `product.yaml`, no
action and no route, so the engine does not find it and nothing the running app does has changed.
`docs/spikes/coding-cores.md` says what is built, what is left and which open points were settled.

| File | What it is |
|---|---|
| `wasifyai_code/place.py` | The interface between the product and an engine (start, send, run, stop, follow, answer), and a pretended place for tests. The real place (this computer: the Agent Server in the sandbox) is not written |
| `wasifyai_code/store.py` | The rows: workspaces with their check command, sessions, turns, checks, checkpoints, schedules and schedule runs. One class on SQLite or Postgres; every row carries `tenant_id` and `product_id` |
| `wasifyai_code/checks.py` | The check as a child program of ours: its own process group, a time limit, the whole group stopped at the limit and on Stop, an optional wrapper for the sandbox |
| `wasifyai_code/loop.py` | The implement, check, fix loop: the turn's states, three rounds, the four result words. One function for a chat turn and a scheduled run |
| `wasifyai_code/checkpoints.py` | A git store outside the workspace: checkpoint, undo, "did files change" |
| `wasifyai_code/schedules.py` | The plain rules, the one next-due function, the one timer |
| `evals/` | The 36 evaluation tasks with hidden checks and a runner written against the place interface |

```
uv run pytest products/wasifyai-code                          # SQLite; the Postgres half skips when none answers
DATABASE_URL=postgresql://... uv run pytest products/wasifyai-code   # both
uv run python products/wasifyai-code/evals/run_eval.py --start       # every hidden check must fail on the starting files
```

The tests use a real git, real SQLite (and Postgres) and real child processes. Nothing in them needs
a model, a network or the coding engine.
