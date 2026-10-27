"""The MCP server (ADR-0069, stage M1): Claude Code, Codex and OpenCode use the app through the
action catalogue, under a connection the person made in Settings.

    connections.py   connections (secret, scopes, approval setting, folders), their activity log,
                     and the principal a connection acts as
    tools.py         one MCP tool per catalogue action offered to `mcp`, built from its schema
    calls.py         a tool call: the executor runs the action; progress, jobs, approvals
    approvals.py     the desk: what waits for the person's answer in the window, and what the
                     answer did
    endpoint.py      the server, the `/mcp` gate (bearer, rate limit, activity) and its mount
    routes.py        Settings > Connections, the pending approvals, the window's answer
    runtime_file.py  `engine.json`, what the launcher reads
"""
