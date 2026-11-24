"""The chat's tools as an MCP server for the person's plan program (ADR-0110; `plan_chat.py`).

It only lists the tools of one round, from the file it is given, and runs nothing: the engine
reads the program's tool call from the program's own events and stops the program, and the
assistant graph runs the call with its card. Standard library only, started with `python -I`
inside the program's sandbox.
"""

import json
import sys

ANSWER = "Wasify AI runs this call and will tell you the result."


def answer(message: dict, tools: list) -> dict | None:
    ident, method = message.get("id"), message.get("method")
    if ident is None:
        return None  # a notification
    if method == "initialize":
        version = (message.get("params") or {}).get("protocolVersion") or "2025-06-18"
        result: dict = {
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "wasify", "version": "1"},
        }
    elif method == "tools/list":
        result = {"tools": tools}
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": ANSWER}]}
    else:
        result = {}
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def main() -> None:
    with open(sys.argv[1], encoding="utf-8") as f:
        tools = json.load(f)
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if isinstance(message, dict) and (out := answer(message, tools)) is not None:
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
