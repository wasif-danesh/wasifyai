"""Extensions: the skills a coding session is taught (ADR-0104; stage X2 of
docs/v2-coding-agent-start-plan.md).

A skill is a folder with a `SKILL.md`: a few lines that name and describe it and say when it is
used (`triggers`), then the text the agent is given. It is data in an open format, the one of
OpenHands' catalogue and of agentskills.io, so a public skill and one of ours are handled alike.

Three places a skill can come from:

    own         Wasify AI's own, in `own/skills/` of this package
    catalogue   the pinned OpenHands catalogue, installed with the coding engine and never
                fetched while a session runs. Only the entries our short list names are shown
    added       a folder the person chose, copied into `<app data>/code/extensions/<id>/`

What is offered is our short list, `own/marketplace.json`, plus what the person added.

**What this module does and does not do.** It reads the format with a small reader of its own
(it does not import the OpenHands SDK), lists what is offered, keeps which skill is on for
which project (in the store), copies a person's folder in, and gives a session the skills that
are on, in the shape the Agent Server takes them. It never runs anything a skill brings: a
folder with scripts is copied as files and read as text.

**A plugin** (stage X3) is a folder with `.plugin/plugin.json`. It can bring skills, hooks
(`hooks/hooks.json`: a command the coding engine runs by itself, before or after a step) and
tool connections (`.mcp.json`). A plugin that brings a hook or a tool connection stays off
until the person has approved it once, with what it brings listed. Its hooks are commands
only, run inside the engine's sandbox, and each is stopped after one second (ADR-0102). Tool
connections are listed and not connected: the sandbox reaches nothing outside.

A skill's text is outside content. It can steer how the agent works; it cannot widen what the
agent may do: the sandbox, the rules and the approvals are not the agent's to change.
"""

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

OWN, CATALOGUE, ADDED = "own", "catalogue", "added"
SOURCES = (OWN, CATALOGUE, ADDED)
SKILL_FILE = "SKILL.md"
PLUGIN_MARK = Path(".plugin") / "plugin.json"
HERE = Path(__file__).with_name("own")
MARKETPLACE = HERE / "marketplace.json"
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$|^[a-z0-9]$")
MAX_SKILL_BYTES = 200_000  # of one SKILL.md
MAX_FOLDER_BYTES = 5_000_000  # of a folder a person adds
MAX_FOLDER_FILES = 200
MAX_DESCRIPTION = 1024  # the AgentSkills limit
SHOWN_FOLDER = "skills"  # under the folder the sandbox reads and cannot write
SKILL, PLUGIN = "skill", "plugin"
HOOKS_FILE = Path("hooks") / "hooks.json"
CONNECTIONS_FILE = ".mcp.json"
HOOK_LIMIT_S = 1  # no hook longer than one second (ADR-0102)
MAX_HOOKS = 20
# when the engine runs a hook: the plugin format's word, the engine's word, ours for a person
HOOK_TIMES = {
    "PreToolUse": ("pre_tool_use", "before each step"),
    "PostToolUse": ("post_tool_use", "after each step"),
    "UserPromptSubmit": ("user_prompt_submit", "when you send a message"),
    "SessionStart": ("session_start", "when a conversation starts"),
    "SessionEnd": ("session_end", "when a conversation ends"),
    "Stop": ("stop", "when the agent is about to finish"),
}


class ExtensionError(Exception):
    """An extension could not be read or added. `message` is safe to show."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass(frozen=True)
class Skill:
    id: str  # "own:explain-in-plain-words", "catalogue:code-review", "added:<id>"
    source: str
    name: str  # the skill's own name, as its file says
    title: str  # for a person
    description: str
    triggers: tuple[str, ...]
    text: str  # the whole SKILL.md, as it is shown before it is switched on
    content: str  # what the agent is given: the file without its first lines
    folder: Path
    licence: str = ""
    needs: str = ""  # "compatibility" in the file
    default_on: bool = False
    # a plugin (stage X3): the skills it brings, its hooks and its tool connections
    kind: str = SKILL
    parts: tuple["Skill", ...] = ()
    hooks: tuple[dict[str, Any], ...] = ()
    connections: tuple[dict[str, Any], ...] = ()
    approved: bool = False

    @property
    def needs_approval(self) -> bool:
        """A plugin that brings more than text is refused until the person has approved it."""
        return bool(self.hooks or self.connections) and not self.approved

    def brings(self) -> dict[str, Any]:
        """What switching it on brings, for the approval card."""
        return {
            "skills": [{"name": p.name, "description": p.description} for p in self.parts],
            "hooks": [
                {"when": h["when_words"], "on": h["matcher"], "command": h["command"]}
                for h in self.hooks
            ],
            "connections": [dict(c) for c in self.connections],
        }

    @property
    def files(self) -> int:
        return sum(1 for p in self.folder.rglob("*") if p.is_file())

    def view(self, *, with_text: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "source": self.source,
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "triggers": list(self.triggers),
            "needs": self.needs,
            "default_on": self.default_on,
        }
        if self.kind == PLUGIN:
            out |= {
                "brings": self.brings(),
                "approved": self.approved,
                "needs_approval": self.needs_approval,
            }
        if with_text:
            out |= {
                "text": self.text,
                "lines": self.text.count("\n") + 1,
                "licence": self.licence,
                "files": self.files,
            }
        return out


# ---- the small reader ----------------------------------------------------------------------------


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def read_front(text: str) -> tuple[dict[str, Any], str]:
    """The first lines of a `SKILL.md` (between two `---` lines) and what follows them. Only what
    a skill uses is read: `key: value`, a list as `- item` lines or as `a, b, c` or `[a, b]`, and
    a value that goes on over indented lines. Anything else is passed over, never guessed at."""
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    try:
        end = next(n for n in range(1, len(lines)) if lines[n].strip() == "---")
    except StopIteration:
        return {}, text
    front: dict[str, Any] = {}
    key = ""
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        item = re.match(r"^\s*-\s+(.*)$", line)
        if item and key:
            if not isinstance(front.get(key), list):
                front[key] = []
            front[key].append(_unquote(item.group(1)))
            continue
        pair = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if pair:
            key, value = pair.group(1), pair.group(2).strip()
            if value in ("", "|", ">", ">-", "|-"):
                front[key] = ""
            elif value.startswith("[") and value.endswith("]"):
                front[key] = [_unquote(v) for v in value[1:-1].split(",") if v.strip()]
            else:
                front[key] = _unquote(value)
            continue
        if key and line[:1] in (" ", "\t") and isinstance(front.get(key), str):
            front[key] = (front[key] + " " + line.strip()).strip()  # a value over several lines
    return front, "\n".join(lines[end + 1 :]).lstrip("\n")


def _triggers(front: dict[str, Any]) -> tuple[str, ...]:
    given = front.get("triggers")
    if isinstance(given, str):
        given = [t for t in (part.strip() for part in given.split(",")) if t]
    if not isinstance(given, list):
        return ()
    return tuple(dict.fromkeys(str(t).strip()[:80] for t in given if str(t).strip()))[:30]


def read_skill(
    folder: Path, *, id: str, source: str, title: str = "", default_on: bool = False
) -> Skill:
    """One skill from its folder, or `ExtensionError` saying what is wrong with it."""
    file = folder / SKILL_FILE
    try:
        if file.stat().st_size > MAX_SKILL_BYTES:
            raise ExtensionError("too_large", f"{SKILL_FILE} is too large to be a skill's text.")
        text = file.read_text(errors="replace")
    except OSError:
        raise ExtensionError("no_skill", f"There is no {SKILL_FILE} in that folder.") from None
    front, content = read_front(text)
    name = str(front.get("name") or folder.name).strip().lower()
    if not NAME.match(name):
        raise ExtensionError(
            "bad_name", "The skill's name must be small letters, digits and dashes."
        )
    description = " ".join(str(front.get("description") or "").split())
    if not description:
        raise ExtensionError("no_description", "The skill does not say what it is for.")
    if not content.strip():
        raise ExtensionError("no_text", "The skill has no text for the agent.")
    return Skill(
        id=id,
        source=source,
        name=name,
        title=title or name.replace("-", " ").capitalize(),
        description=description[:MAX_DESCRIPTION],
        triggers=_triggers(front),
        text=text,
        content=content,
        folder=folder,
        licence=str(front.get("license") or front.get("licence") or "")[:200],
        needs=" ".join(str(front.get("compatibility") or "").split())[:300],
        default_on=default_on,
    )


# ---- a plugin ------------------------------------------------------------------------------------


def _json(path: Path, what: str) -> dict[str, Any]:
    try:
        if path.stat().st_size > MAX_SKILL_BYTES:
            raise ExtensionError("too_large", f"The plugin's {what} is too large.")
        found = json.loads(path.read_text(errors="replace"))
    except OSError:
        raise ExtensionError("no_plugin", f"The plugin's {what} could not be read.") from None
    except ValueError:
        raise ExtensionError("bad_plugin", f"The plugin's {what} is not valid JSON.") from None
    if not isinstance(found, dict):
        raise ExtensionError("bad_plugin", f"The plugin's {what} is not valid.")
    return found


def read_hooks(folder: Path) -> tuple[dict[str, Any], ...]:
    """The hooks a plugin brings, each as one row: when, on which tools, the command. A hook
    that is not a plain command (one that asks a model, or runs on in the background) makes
    the whole plugin unreadable: we never run a part of what was approved as a whole."""
    file = folder / HOOKS_FILE
    if not file.is_file():
        return ()
    given = _json(file, "hooks file")
    given = given.get("hooks", given)
    if not isinstance(given, dict):
        raise ExtensionError("bad_plugin", "The plugin's hooks file is not valid.")
    out: list[dict[str, Any]] = []
    for time, matchers in given.items():
        if time not in HOOK_TIMES:
            raise ExtensionError("bad_hook", f"The plugin has a hook for {time}, which is unknown.")
        for matcher in matchers if isinstance(matchers, list) else []:
            if not isinstance(matcher, dict):
                continue
            for hook in matcher.get("hooks") or []:
                if not isinstance(hook, dict):
                    continue
                command = str(hook.get("command") or "").strip()
                if str(hook.get("type") or "command") != "command" or not command:
                    raise ExtensionError(
                        "bad_hook",
                        "The plugin has a hook that asks a model. Only hooks that are a plain "
                        "command can be used.",
                    )
                if hook.get("async") or hook.get("async_"):
                    raise ExtensionError(
                        "bad_hook",
                        "The plugin has a hook that runs on in the background. A hook may take "
                        "one second at most.",
                    )
                out.append(
                    {
                        "when": HOOK_TIMES[time][0],
                        "when_words": HOOK_TIMES[time][1],
                        "matcher": str(matcher.get("matcher") or "*")[:200],
                        "command": command[:2000],
                    }
                )
    if len(out) > MAX_HOOKS:
        raise ExtensionError("too_large", f"The plugin has more than {MAX_HOOKS} hooks.")
    return tuple(out)


def read_connections(folder: Path) -> tuple[dict[str, Any], ...]:
    """The tool connections a plugin names, for the approval card. Never what they are given
    (a key in its settings is not read back out)."""
    file = folder / CONNECTIONS_FILE
    if not file.is_file():
        return ()
    servers = _json(file, "tool connections").get("mcpServers")
    out = []
    for name, entry in (servers if isinstance(servers, dict) else {}).items():
        entry = entry if isinstance(entry, dict) else {}
        to = str(entry.get("url") or entry.get("command") or "")
        out.append({"name": str(name)[:100], "to": to[:300]})
    return tuple(out[:MAX_HOOKS])


def read_plugin(folder: Path, *, id: str, title: str = "", approved: bool = False) -> Skill:
    """One plugin from its folder, or `ExtensionError` saying what is wrong with it."""
    mark = folder / PLUGIN_MARK
    front = _json(mark, "plugin.json")
    name = str(front.get("name") or folder.name).strip().lower()
    if not NAME.match(name):
        raise ExtensionError(
            "bad_name", "The plugin's name must be small letters, digits and dashes."
        )
    description = " ".join(str(front.get("description") or "").split())
    if not description:
        raise ExtensionError("no_description", "The plugin does not say what it is for.")
    parts = []
    skills = folder / "skills"
    for sub in sorted(skills.iterdir()) if skills.is_dir() else []:
        if sub.is_dir() and not sub.is_symlink() and (sub / SKILL_FILE).is_file():
            parts.append(read_skill(sub, id=f"{id}/{sub.name}", source=ADDED))
    hooks, connections = read_hooks(folder), read_connections(folder)
    if not parts and not hooks and not connections:
        raise ExtensionError("no_text", "The plugin brings no skill, hook or tool connection.")
    return Skill(
        id=id,
        source=ADDED,
        name=name,
        title=title or name.replace("-", " ").capitalize(),
        description=description[:MAX_DESCRIPTION],
        triggers=(),
        text=mark.read_text(errors="replace"),
        content="",
        folder=folder,
        licence=str(front.get("license") or front.get("licence") or "")[:200],
        kind=PLUGIN,
        parts=tuple(parts),
        hooks=hooks,
        connections=connections,
        approved=approved,
    )


# ---- what is offered -----------------------------------------------------------------------------


def short_list(path: Path = MARKETPLACE) -> list[dict[str, Any]]:
    """Our short list: the entries offered in Wasify AI, in the order they are shown."""
    entries = json.loads(path.read_text()).get("entries") or []
    return [e for e in entries if e.get("source") in (OWN, CATALOGUE) and e.get("name")]


def offered(catalogue: Path | None, added: list[dict[str, Any]]) -> list[Skill]:
    """Every skill a person can switch on: the short list (an entry that cannot be read, or a
    catalogue entry when the catalogue is not there, is left out) and then what they added,
    the newest first."""
    out: list[Skill] = []
    for entry in short_list():
        name, source = str(entry["name"]), str(entry["source"])
        if source == CATALOGUE and catalogue is None:
            continue
        folder = (HERE if source == OWN else catalogue or HERE) / "skills" / name
        try:
            out.append(
                read_skill(
                    folder, id=f"{source}:{name}", source=source,
                    title=str(entry.get("title") or ""), default_on=bool(entry.get("on")),
                )
            )  # fmt: skip
        except ExtensionError:
            continue
    for row in added:
        try:
            if row.get("kind") == PLUGIN:
                out.append(
                    read_plugin(
                        Path(row["path"]), id=f"{ADDED}:{row['id']}",
                        title=str(row.get("title") or ""), approved=bool(row.get("approved_at")),
                    )
                )  # fmt: skip
                continue
            out.append(
                read_skill(
                    Path(row["path"]), id=f"{ADDED}:{row['id']}", source=ADDED,
                    title=str(row.get("title") or ""),
                )
            )  # fmt: skip
        except ExtensionError:
            continue  # its folder was removed from under us: it is no longer offered
    return out


def is_on(skill: Skill, switches: dict[str, bool]) -> bool:
    """Whether a skill is on for a project: the person's switch, else the short list's word.
    A plugin that still needs the person's approval is off, whatever its switch says."""
    if skill.needs_approval:
        return False
    return switches.get(skill.id, skill.default_on)


# ---- adding one from a folder --------------------------------------------------------------------


def look(folder: Path) -> dict[str, Any]:
    """What a folder the person chose holds, before anything is copied: a skill with its text,
    or why it cannot be added."""
    if not folder.is_dir():
        raise ExtensionError("no_folder", f"There is no folder at {folder}.")
    plugin = (folder / PLUGIN_MARK).is_file()
    if plugin:
        skill = read_plugin(folder, id=f"{ADDED}:new")
    else:
        skill = read_skill(folder, id=f"{ADDED}:new", source=ADDED)
    files = [p for p in folder.rglob("*") if p.is_file() and not p.is_symlink()]
    size = sum(p.stat().st_size for p in files)
    if len(files) > MAX_FOLDER_FILES or size > MAX_FOLDER_BYTES:
        raise ExtensionError(
            "too_large", "That folder is too large to be added (5 MB and 200 files at most)."
        )
    seen = {
        **skill.view(with_text=True),
        "folder": str(folder),
        "bytes": (folder / (PLUGIN_MARK if plugin else SKILL_FILE)).stat().st_size,
    }
    if not plugin:
        seen["brings"] = "text"  # a skill brings text only: no hook and no tool connection
    return seen


def copy_in(folder: Path, kept: Path, item: str) -> Path:
    """Copy a person's skill folder into the app's own data (links are not followed and not
    copied) and give the copy. The person's folder is not changed."""
    look(folder)  # the same refusals, at the moment of copying
    target = kept / item
    if target.exists():
        raise ExtensionError("taken", "That extension is already there.")
    try:
        shutil.copytree(
            folder, target, symlinks=False,
            ignore=lambda d, names: [n for n in names if (Path(d) / n).is_symlink() or n == ".git"],
        )  # fmt: skip
    except OSError:
        shutil.rmtree(target, ignore_errors=True)
        raise ExtensionError("could_not_copy", "The folder could not be copied.") from None
    return target


# ---- giving a session its skills -----------------------------------------------------------------


def show_to_sandbox(skills: list[Skill], fixed: Path) -> dict[str, Path]:
    """Put the folders of the skills that are on where the sandbox can read and not write them
    (`<app data>/coding-fixed/skills/<key>/`), so that the agent can read a skill's own files
    on demand. Gives each skill's folder there. A folder that is there already, unchanged, is
    left alone; ones no longer on are removed."""
    root = fixed / SHOWN_FOLDER
    root.mkdir(parents=True, exist_ok=True)
    wanted: dict[str, Path] = {}
    for skill in skills:
        mark = hashlib.sha256(skill.text.encode()).hexdigest()[:12]
        key = f"{re.sub(r'[^a-z0-9-]', '-', skill.id.replace(':', '-'))}-{mark}"
        target = root / key
        mark_file = PLUGIN_MARK if skill.kind == PLUGIN else Path(SKILL_FILE)
        if not (target / mark_file).is_file():
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(
                skill.folder, target, symlinks=False,
                ignore=lambda d, names: [n for n in names if (Path(d) / n).is_symlink()],
            )  # fmt: skip
        wanted[skill.id] = target
    keep = {p.name for p in wanted.values()}
    for old in root.iterdir():
        if old.is_dir() and old.name not in keep:
            shutil.rmtree(old, ignore_errors=True)
    return wanted


def for_engine(skills: list[Skill], shown: dict[str, Path]) -> list[dict[str, Any]]:
    """The skills that are on, in the shape the Agent Server takes them in a conversation's
    context. The text goes with them: the server reads no catalogue and fetches nothing."""
    out = []
    flat: list[tuple[Skill, Path | None]] = []
    for skill in skills:
        if skill.kind != PLUGIN:
            flat.append((skill, shown[skill.id] / SKILL_FILE if skill.id in shown else None))
            continue
        for part in skill.parts:  # a plugin's skills, read from the plugin's shown folder
            at = shown.get(skill.id)
            flat.append((part, at / "skills" / part.folder.name / SKILL_FILE if at else None))
    for skill, source in flat:
        entry: dict[str, Any] = {
            "name": skill.name,
            "content": skill.content,
            "description": skill.description,
            "is_agentskills_format": True,
        }
        if source is not None:
            entry["source"] = str(source)
        if skill.triggers:
            entry["trigger"] = {"type": "keyword", "keywords": list(skill.triggers)}
        if skill.licence:
            entry["license"] = skill.licence
        if skill.needs:
            entry["compatibility"] = skill.needs
        out.append(entry)
    return out


def hooks_for_engine(skills: list[Skill], shown: dict[str, Path]) -> dict[str, Any] | None:
    """The hooks of the plugins that are on (so: approved), in the shape the Agent Server takes
    them. Each is a plain command with one second to run, and is told where its plugin's files
    are (`PLUGIN_ROOT`): the copy the sandbox can read and not write."""
    out: dict[str, list[dict[str, Any]]] = {}
    for skill in skills:
        if skill.kind != PLUGIN or skill.needs_approval or skill.id not in shown:
            continue
        for hook in skill.hooks:
            out.setdefault(hook["when"], []).append(
                {
                    "matcher": hook["matcher"],
                    "hooks": [
                        {
                            "type": "command",
                            "command": hook["command"],
                            "timeout": HOOK_LIMIT_S,
                            "plugin_root": str(shown[skill.id]),
                        }
                    ],
                }
            )
    return out or None


def words_of(skill: Skill) -> str:
    """What a person would look an extension up by (ADR-0041)."""
    what = (
        "A plugin for the coding agent" if skill.kind == PLUGIN else "A skill for the coding agent"
    )
    return ". ".join(p for p in (skill.title, what, skill.description) if p)
