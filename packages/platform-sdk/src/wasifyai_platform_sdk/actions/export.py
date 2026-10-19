"""The catalogue as one JSON file (ADR-0068 decision 6): `docs/contracts/actions.json`.

Tests and docs read it, and a reviewer reads it to see everything an agent can do. A test fails
when the file is not what the registry produces, so it is regenerated (never hand-edited) with

    uv run python -m wasifyai_api.actions_catalogue --write
"""

import json
from typing import Any

from wasifyai_platform_sdk.actions.help import HELP_DIR
from wasifyai_platform_sdk.actions.model import Action
from wasifyai_platform_sdk.actions.registry import ActionRegistry

EXPORT_VERSION = 1
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


def describe(action: Action) -> dict[str, Any]:
    return {
        "id": action.id,
        "title": action.title,
        "summary": action.summary,
        "description": action.description,
        "input": action.input.model_json_schema(),
        "output": action.output.model_json_schema(),
        "examples": list(action.examples),
        "effect": action.effect,
        "flags": list(action.flags),
        "requires": [n.model_dump() for n in action.requires],
        "long": action.long,
        "product": action.product,
        "ui": action.ui,
        "ui_exempt": action.ui_exempt,
        "surfaces": list(action.surfaces),
        "consent": action.consent,
        "help": f"{HELP_DIR}/{action.id}.md",
    }


def export_catalogue(registry: ActionRegistry) -> dict[str, Any]:
    return {
        "version": EXPORT_VERSION,
        "schema": SCHEMA_DIALECT,
        "actions": [describe(a) for a in registry.all()],
    }


def render(registry: ActionRegistry) -> str:
    return json.dumps(export_catalogue(registry), indent=2, ensure_ascii=False) + "\n"
