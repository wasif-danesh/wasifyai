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
folder with scripts is copied as files and read as text. A plugin (a folder with
`.plugin/plugin.json`, which can bring hooks and tool connections) is recognised and refused
here; it is stage X3's work.

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

    @property
    def files(self) -> int:
        return sum(1 for p in self.folder.rglob("*") if p.is_file())

    def view(self, *, with_text: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "kind": "skill",
            "source": self.source,
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "triggers": list(self.triggers),
            "needs": self.needs,
            "default_on": self.default_on,
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
    """Whether a skill is on for a project: the person's switch, else the short list's word."""
    return switches.get(skill.id, skill.default_on)


# ---- adding one from a folder --------------------------------------------------------------------


def look(folder: Path) -> dict[str, Any]:
    """What a folder the person chose holds, before anything is copied: a skill with its text,
    or why it cannot be added."""
    if not folder.is_dir():
        raise ExtensionError("no_folder", f"There is no folder at {folder}.")
    if (folder / PLUGIN_MARK).is_file():
        raise ExtensionError(
            "is_plugin",
            "That folder is a plugin: it can bring hooks and tool connections, not only text. "
            "Plugins cannot be added yet.",
        )
    skill = read_skill(folder, id=f"{ADDED}:new", source=ADDED)
    files = [p for p in folder.rglob("*") if p.is_file() and not p.is_symlink()]
    size = sum(p.stat().st_size for p in files)
    if len(files) > MAX_FOLDER_FILES or size > MAX_FOLDER_BYTES:
        raise ExtensionError(
            "too_large", "That folder is too large to be a skill (5 MB and 200 files at most)."
        )
    return {
        **skill.view(with_text=True),
        "folder": str(folder),
        "bytes": (folder / SKILL_FILE).stat().st_size,
        "brings": "text",  # a skill brings text only: no hook and no tool connection
    }


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
        if not (target / SKILL_FILE).is_file():
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
    for skill in skills:
        entry: dict[str, Any] = {
            "name": skill.name,
            "content": skill.content,
            "description": skill.description,
            "is_agentskills_format": True,
        }
        if skill.id in shown:
            entry["source"] = str(shown[skill.id] / SKILL_FILE)
        if skill.triggers:
            entry["trigger"] = {"type": "keyword", "keywords": list(skill.triggers)}
        if skill.licence:
            entry["license"] = skill.licence
        if skill.needs:
            entry["compatibility"] = skill.needs
        out.append(entry)
    return out


def words_of(skill: Skill) -> str:
    """What a person would look an extension up by (ADR-0041)."""
    return ". ".join(
        p for p in (skill.title, "A skill for the coding agent", skill.description) if p
    )
