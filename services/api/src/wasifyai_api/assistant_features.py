"""What the chat assistant is told the app can do (ADR-0071, before its meta-tools exist).

The list is made from the action catalogue and the side menu, so a screen that is added or renamed
changes it and nothing is typed by hand: the catalogue says what each action is called and which
screen does it, `packages/ui/src/shell/menu.ts` says where that screen is. The result is kept in
the assistant's package (`features.json`); the assistant offers only the rows whose actions this
engine serves. A test fails when the file is out of date.

    uv run python -m wasifyai_api.assistant_features --write
    uv run python -m wasifyai_api.assistant_features --check
"""

import argparse
import json
import re
import sys

from wasifyai_api.actions_engine import ROOT, default_catalogue

MENU_TS = ROOT / "packages" / "ui" / "src" / "shell" / "menu.ts"
FEATURES = ROOT / "products" / "wasifyai-assistant" / "wasifyai_assistant" / "features.json"
# screens that are not a thing to make: this chat, and the two the assistant has tools for
LEFT_OUT = {"chat", "library", "models"}


def menu_paths() -> dict[str, str]:
    """Menu item id -> where it is in the side menu ("Voice › Text to speech", or "Train")."""
    text = MENU_TS.read_text(encoding="utf-8")
    paths: dict[str, str] = {}
    for _gid, glabel, body in re.findall(
        r'id: "(\w+)",\s*label: "([^"]+)",\s*icon: \w+,\s*items: \[(.*?)\],\s*\}', text, re.S
    ):
        for iid, ilabel in re.findall(r'id: "([\w.]+)", label: "([^"]+)"', body):
            paths[iid] = f"{glabel} › {ilabel}"
    for iid, ilabel in re.findall(r'\{ id: "(train)", label: "([^"]+)"', text):
        paths[iid] = ilabel
    return paths


def build() -> list[dict[str, list[str] | str]]:
    """One row per screen that has actions: where it is, and what its actions are for."""
    paths = menu_paths()
    rows: dict[str, dict[str, list[str] | str]] = {}
    for a in default_catalogue().for_surface("assistant"):
        if a.ui is None or a.ui in LEFT_OUT or a.ui not in paths:
            continue
        row = rows.setdefault(a.ui, {"where": paths[a.ui], "actions": [], "does": []})
        row["actions"].append(a.id)  # type: ignore[union-attr]
        row["does"].append(a.title)  # type: ignore[union-attr]
    order = {item: n for n, item in enumerate(paths)}  # the menu's own order
    return [rows[item] for item in sorted(rows, key=order.__getitem__)]


def render() -> str:
    return json.dumps(build(), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Write or check the assistant's feature list")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    text = render()
    if args.write:
        FEATURES.write_text(text, encoding="utf-8")
        print(f"wrote {FEATURES.relative_to(ROOT)}")
        return 0
    if not FEATURES.is_file() or FEATURES.read_text(encoding="utf-8") != text:
        print(f"{FEATURES.relative_to(ROOT)} is out of date: run --write", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
