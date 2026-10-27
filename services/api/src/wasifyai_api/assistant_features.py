"""What the chat assistant is told the app can do (ADR-0071): the screens, and the help corpus.

Both lists are made from the action catalogue, the side menu and `docs/help/`, so a screen that is
added or renamed changes them and nothing is typed by hand: the catalogue says what each action is
called and which screen does it, `packages/ui/src/shell/menu.ts` says where that screen is, and
each action's help file says how it is done. The results are kept in the assistant's package
(`features.json`, `help.json`); the assistant offers only the rows whose actions this engine
serves. A test fails when a file is out of date.

    uv run python -m wasifyai_api.assistant_features --write
    uv run python -m wasifyai_api.assistant_features --check
"""

import argparse
import json
import re
import sys

from wasifyai_platform_sdk.actions import HelpError, load_help

from wasifyai_api.actions_engine import ROOT, default_catalogue

MENU_TS = ROOT / "packages" / "ui" / "src" / "shell" / "menu.ts"
FEATURES = ROOT / "products" / "wasifyai-assistant" / "wasifyai_assistant" / "features.json"
HELP = FEATURES.with_name("help.json")
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
    for iid, ilabel in re.findall(r'\{ id: "(motion|model3d|train)", label: "([^"]+)"', text):
        paths[iid] = ilabel
    return paths


def build() -> list[dict[str, list[str] | str]]:
    """One row per screen that has actions: where it is, and what its actions are for."""
    paths = menu_paths()
    rows: dict[str, dict[str, list[str] | str]] = {}
    for a in default_catalogue().for_surface("assistant"):
        if a.ui is None or a.ui in LEFT_OUT or a.ui not in paths:
            continue
        row = rows.setdefault(
            a.ui, {"screen": a.ui, "where": paths[a.ui], "actions": [], "does": []}
        )
        row["actions"].append(a.id)  # type: ignore[union-attr]
        row["does"].append(a.title)  # type: ignore[union-attr]
    order = {item: n for n, item in enumerate(paths)}  # the menu's own order
    return [rows[item] for item in sorted(rows, key=order.__getitem__)]


def render() -> str:
    return json.dumps(build(), indent=2, ensure_ascii=False) + "\n"


def build_help() -> list[dict[str, object]]:
    """One entry per action the assistant may be asked about: its guide, as `help.py` reads it.
    An action without a help file is left out here and caught by the catalogue test."""
    out: list[dict[str, object]] = []
    for a in default_catalogue().for_surface("assistant"):
        try:
            h = load_help(ROOT, a.id)
        except HelpError:
            continue
        title = next((ln[2:].strip() for ln in h.body.splitlines() if ln.startswith("# ")), a.title)
        out.append(
            {
                "action": a.id, "title": title, "screen": h.screen,
                "synonyms": list(h.synonyms), "body": h.body,
            }
        )  # fmt: skip
    return out


def render_help() -> str:
    return json.dumps(build_help(), indent=1, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Write or check the assistant's feature list")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    wanted = {FEATURES: render(), HELP: render_help()}
    if args.write:
        for path, text in wanted.items():
            path.write_text(text, encoding="utf-8")
            print(f"wrote {path.relative_to(ROOT)}")
        return 0
    stale = [p for p, text in wanted.items() if not p.is_file() or p.read_text() != text]
    for path in stale:
        print(f"{path.relative_to(ROOT)} is out of date: run --write", file=sys.stderr)
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
