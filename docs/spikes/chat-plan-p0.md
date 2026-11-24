# Chat on the person's own plan: P0 (2026-11-24)

ADR-0110's spike. The programs are the ones Code installs (the "harness" part, `0.99.1+2.2.2`): Claude Code 2.1.312
and Codex 0.160.1. Each was started by its own command, with the person's real home (where its sign-in is), a
clean environment, and one tool server of ours listing one tool (`make_picture`).

## Claude Code, on the owner's Max plan

```
claude -p --output-format stream-json --verbose --include-partial-messages --tools "" \
  --strict-mcp-config --mcp-config <ours> --allowedTools mcp__wasify --system-prompt <ours> \
  --setting-sources "" --disable-slash-commands --no-session-persistence --model haiku
```

| What | Measured |
|---|---|
| Its tools, as its `init` event lists them | `mcp__wasify__make_picture` only |
| Start to `init` | 0.9 s |
| First word | 1.7 s (by hand), 2.3 s through `plan_chat.py` in the sandbox |
| A tool call in its events (`assistant` with `tool_use`) | 2.0 s |
| A round with a tool call, start to stop | 2.4 s |
| Bengali ("আমাকে দুই লাইনের একটি ছোট কবিতা লিখে দাও") | answered in Bengali, 2.8 s |

Left alone after a tool call, it reads our server's answer and goes on (it called the tool a second time, then said
the picture had not come). So `plan_chat.py` stops it once our server has answered the round's calls, before it
calls its model again; the graph runs the calls and starts the next round with the results in the text.

Its usage comes in its `result` event (tokens, and a cost in dollars it works out itself); a round stopped at a tool
call has none. Nothing is recorded yet (ADR-0110, question 3).

## Codex, on the owner's ChatGPT account

```
codex exec --json --ephemeral --skip-git-repo-check --ignore-user-config --ignore-rules -s read-only -C <empty> \
  --disable shell_tool --disable unified_exec ... -c web_search="disabled" \
  -c mcp_servers.wasify.command=... -c mcp_servers.wasify.args=[...] -c developer_instructions=...
```

Started in 1.3 s (`thread.started`), then answered: "You've hit your usage limit. Upgrade to Plus to continue using
Codex ..., or try again at Dec 15th, 2026". So no Codex round was run. Its tool calls are read from
`item.started` of an `mcp_tool_call` item, its text from `item.completed` of an `agent_message`, a refusal from
`turn.failed` (that message is shown in its words). This is from Codex's documented events and is tested only on a
pretended program; run it again once the account can.

## The sandbox

Probed through `plan_chat.py`'s profile: reading `~/.zshrc`, listing `~/Documents`, listing the app's data and
writing in the home folder are refused; reading `~/.claude`, the keychain folder and writing the round's folder are
allowed; Claude Code answered from inside it. The network is open (no proxy; see ADR-0110 decision 5).

## Not measured

- Ten turns each from `products/wasifyai-assistant/evals/` (P3).
- Codex at all, beyond its start.
- A plan limit on Claude Code (its words come through `result` and are shown as said).
