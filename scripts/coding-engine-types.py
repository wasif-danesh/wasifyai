"""The shapes the coding product reads from the Agent Server, generated from the Agent Server's own
API description at the pinned version (ADR-0101, decision 9).

    uv run python scripts/coding-engine-types.py --openapi <openapi.json>   # write both files
    uv run python scripts/coding-engine-types.py --check                    # are they in step?

`<openapi.json>` is what the real, pinned server answers at `GET /openapi.json`
(`make test-coding` fetches it and compares; so does `--data <app data>` here, which starts the
server the way the app does). Two files are written, and both are committed:

    services/coding-engine/api-excerpt.json          the part of the description we rely on: the
                                                     events we read, field by field, and the calls
                                                     we make. Small enough to read in a review
    products/wasifyai-code/wasifyai_code/agent_types.py   Python types made from the excerpt

`--check` makes the types again from the excerpt and fails when the committed file differs or the
excerpt is for another version than `services/coding-engine/VERSION`. A unit test runs it, so the
two files cannot drift apart. The contract test compares the excerpt with the live description, so
an upgrade that changes a shape we read fails before a screen does.

Nothing is fetched from the internet and none of OpenHands' code is copied: the excerpt holds
names and types only.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PINS = ROOT / "services" / "coding-engine"
EXCERPT = PINS / "api-excerpt.json"
TYPES = ROOT / "products" / "wasifyai-code" / "wasifyai_code" / "agent_types.py"

# The events `wasifyai_code/events.py` reads. A new one is added here and generated again.
EVENTS = (
    "ActionEvent",
    "AgentErrorEvent",
    "ConversationErrorEvent",
    "ConversationStateUpdateEvent",
    "MessageEvent",
    "ObservationEvent",
    "StreamingDeltaEvent",
    "UserRejectObservation",
)
# The bodies `wasifyai_code/client.py` sends.
REQUESTS = ("StartConversationRequest", "SendMessageRequest", "ConfirmationResponseRequest")
# The calls `wasifyai_code/client.py` makes: each must exist with this method.
CALLS = (
    ("post", "/api/conversations"),
    ("get", "/api/conversations/{conversation_id}"),
    ("delete", "/api/conversations/{conversation_id}"),
    ("post", "/api/conversations/{conversation_id}/events"),
    ("post", "/api/conversations/{conversation_id}/run"),
    ("post", "/api/conversations/{conversation_id}/interrupt"),
    ("post", "/api/conversations/{conversation_id}/events/respond_to_confirmation"),
    ("get", "/api/conversations/{conversation_id}/events/search"),
    ("get", "/api/conversations/{conversation_id}/events/{event_id}"),
    ("get", "/server_info"),
)


def _find(schemas: dict[str, Any], name: str) -> dict[str, Any]:
    """A schema by its name. The description gives some names a suffix when a model is used
    both in requests and in answers (`ActionEvent-Output`); the answer's form is the one read."""
    for candidate in (name, f"{name}-Output", f"{name}-Input"):
        if candidate in schemas:
            return schemas[candidate]
    raise SystemExit(f"the API description has no {name}: the pinned version changed it")


def _kind(prop: dict[str, Any]) -> str:
    """A property's type as one short word of ours: str, int, float, bool, list, dict, any; with
    `?` when it may be null."""
    if "anyOf" in prop or "oneOf" in prop:
        options = prop.get("anyOf") or prop.get("oneOf") or []
        kinds = {_kind(o) for o in options}
        maybe = "null" in kinds
        kinds.discard("null")
        kinds = {k.rstrip("?") for k in kinds}
        one = kinds.pop() if len(kinds) == 1 else "any"
        return one + ("?" if maybe and one != "any" else "")
    if "$ref" in prop or "allOf" in prop:
        return "dict"
    kind = prop.get("type")
    if kind == "null":
        return "null"
    if "const" in prop or "enum" in prop:
        values = [prop["const"]] if "const" in prop else prop["enum"]
        return "str" if all(isinstance(v, str) for v in values) else "any"
    return {
        "string": "str", "integer": "int", "number": "float", "boolean": "bool",
        "array": "list", "object": "dict",
    }.get(str(kind), "any")  # fmt: skip


def excerpt_of(openapi: dict[str, Any]) -> dict[str, Any]:
    """The part of an API description that we rely on."""
    schemas = openapi.get("components", {}).get("schemas", {})
    paths = openapi.get("paths", {})
    out: dict[str, Any] = {
        "version": str(openapi.get("info", {}).get("version", "")),
        "events": {},
        "requests": {},
        "calls": [],
    }
    for group, names in (("events", EVENTS), ("requests", REQUESTS)):
        for name in names:
            schema = _find(schemas, name)
            props = schema.get("properties", {})
            out[group][name] = {
                "fields": {field: _kind(props[field]) for field in sorted(props)},
                "required": sorted(schema.get("required", [])),
            }
    for method, path in CALLS:
        if method not in paths.get(path, {}):
            raise SystemExit(f"the API description has no {method.upper()} {path}")
        out["calls"].append(f"{method.upper()} {path}")
    return out


PY = {
    "str": "str", "int": "int", "float": "float", "bool": "bool",
    "list": "list[Any]", "dict": "dict[str, Any]", "any": "Any",
}  # fmt: skip


def types_of(excerpt: dict[str, Any]) -> str:
    """The Python module made from an excerpt."""
    lines = [
        '"""The shapes read from, and sent to, the Agent Server (ADR-0101, decision 9).',
        "",
        "GENERATED by scripts/coding-engine-types.py from services/coding-engine/api-excerpt.json,",
        "which is cut from the Agent Server's own API description. Do not edit by hand: change the",
        "list of names in the script and run it again.",
        '"""',
        "",
        "from typing import Any, TypedDict",
        "",
        f'AGENT_SERVER_VERSION = "{excerpt["version"]}"',
        "EVENT_KINDS = (",
        *(f'    "{name}",' for name in excerpt["events"]),
        ")",
        "",
        "# the calls the client makes; the contract test checks each one still exists",
        "CALLS = (",
        *(f'    "{call}",' for call in excerpt["calls"]),
        ")",
    ]
    for group in ("events", "requests"):
        for name, schema in excerpt[group].items():
            lines += ["", "", f"class {name}(TypedDict, total=False):"]
            for field_name, kind in schema["fields"].items():
                maybe = kind.endswith("?")
                py = PY[kind.rstrip("?")] + (" | None" if maybe else "")
                lines.append(f"    {field_name}: {py}")
            if not schema["fields"]:
                lines.append("    pass")
    return "\n".join(lines) + "\n"


def check() -> list[str]:
    """What is out of step, in words; empty when nothing is."""
    problems = []
    if not EXCERPT.is_file() or not TYPES.is_file():
        return ["the excerpt or the types file is missing: run the script with --openapi"]
    excerpt = json.loads(EXCERPT.read_text())
    pinned = (PINS / "VERSION").read_text().strip()
    if excerpt.get("version") != pinned:
        problems.append(
            f"the excerpt is for {excerpt.get('version')}, the pin is {pinned}: generate it again"
        )
    if TYPES.read_text() != types_of(excerpt):
        problems.append(f"{TYPES.relative_to(ROOT)} is not what the excerpt gives: run the script")
    return problems


async def fetch(data: Path) -> dict[str, Any]:
    """The live description, from the pinned server started the way the app starts it."""
    from wasifyai_api.coding_server import CodingServer

    server = CodingServer(data, PINS)
    try:
        await server.ensure_running()
        answer = await server.request("GET", "/openapi.json", timeout=30)
        answer.raise_for_status()
        return answer.json()
    finally:
        await server.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--openapi", type=Path, help="the server's /openapi.json, saved")
    parser.add_argument("--data", type=Path, help="an app data folder with the engine set up")
    parser.add_argument("--check", action="store_true", help="are the two files in step?")
    args = parser.parse_args()
    if args.check:
        problems = check()
        for p in problems:
            print(p, file=sys.stderr)
        return 1 if problems else 0
    if args.openapi:
        openapi = json.loads(args.openapi.read_text())
    elif args.data:
        openapi = asyncio.run(fetch(args.data))
    else:
        parser.error("give --openapi, --data or --check")
    excerpt = excerpt_of(openapi)
    EXCERPT.write_text(json.dumps(excerpt, indent=2) + "\n")
    TYPES.write_text(types_of(excerpt))
    print(
        f"wrote {EXCERPT.relative_to(ROOT)} and {TYPES.relative_to(ROOT)} for {excerpt['version']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
