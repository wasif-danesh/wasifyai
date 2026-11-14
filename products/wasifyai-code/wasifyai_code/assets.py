"""Wasify AI's own products as tools of a coding session (stage C4): a picture or speech made by
the app and put into the project.

The agent has no tool for this and no connection to the app. It runs one small command in its
terminal, alone:

    wasify-make picture "a round logo of a loaf of bread" assets/logo.png [--size wide]
    wasify-make speech "Welcome to the bakery." assets/welcome.wav

(`cd <the project> &&` or `mkdir -p <folder> &&` in front is read too: models often write that.)

Like every command it waits before it runs (`rules.py`: the kind `make`, asked in every mode
unless the person allowed it for the project). When it is let through, **this module** runs the
app's own action (`image.generate`, `speech.speak`) for the person, outside the sandbox, through
the one action executor, copies the result into the project, and leaves a note of how it went.
The command inside the sandbox then only reads that note (`services/coding-engine/wasify-make`).
So no token of the app is ever inside the sandbox, the descriptions of the app's 67 tools are
never sent to the model, and what is made is in the person's library like anything else they make.
"""

import asyncio
import hashlib
import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wasifyai_code.rules import path_in

COMMAND = "wasify-make"
PICTURE, SPEECH = "picture", "speech"
SIZES = ("square", "landscape", "portrait", "wide", "tall")
ENDINGS = {PICTURE: (".png",), SPEECH: (".wav",)}
MAX_TEXT = 4000
NOTES = "made"  # under the folder the sandbox reads and cannot write


class AssetError(Exception):
    """Nothing was made. `message` is said to the agent."""


@dataclass(frozen=True)
class Ask:
    kind: str
    text: str
    path: str  # as the agent wrote it
    size: str = "square"
    cwd: str = ""  # the folder the agent went into first (`cd <folder> && wasify-make ...`)

    @property
    def key(self) -> str:
        return hashlib.sha256(
            "\0".join((self.kind, self.text, self.path, self.size)).encode()
        ).hexdigest()


def is_make(command: str) -> bool:
    """Whether a command line is a call of `wasify-make` (alone or not)."""
    return any(part.split()[:1] == [COMMAND] for part in command.replace("&&", ";").split(";"))


def parse(command: str) -> Ask:
    """One call of `wasify-make`, as the whole command, or `AssetError` saying what is wrong."""
    try:
        lexer = shlex.shlex(command.strip(), posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        every = list(lexer)
    except ValueError:
        raise AssetError("The command could not be read. Put the description in quotes.") from None
    # what a model often puts in front: going into the project, making the folder. Nothing else.
    parts: list[list[str]] = [[]]
    for word in every:
        if word in ("&&", ";"):
            parts.append([])
        elif word and all(c in "();<>|&" for c in word):
            raise AssetError(f"Run {COMMAND} alone, as the whole command.")
        else:
            parts[-1].append(word)
    *before, words = parts
    cwd = ""
    for part in before:
        if len(part) == 2 and part[0] == "cd":
            cwd = part[1]
        elif not (part[:1] == ["mkdir"] and len(part) in (2, 3)):
            raise AssetError(f"Run {COMMAND} alone, as the whole command.")
    if not words or words[0] != COMMAND:
        raise AssetError(f"Run {COMMAND} alone, as the whole command.")
    size, rest, n = "square", [], 1
    while n < len(words):
        if words[n] == "--size" and n + 1 < len(words):
            size, n = words[n + 1], n + 2
        elif words[n].startswith("--size="):
            size, n = words[n].split("=", 1)[1], n + 1
        elif words[n].startswith("--"):
            raise AssetError(f"{COMMAND} does not know {words[n]}.")
        else:
            rest.append(words[n])
            n += 1
    if len(rest) != 3 or rest[0] not in (PICTURE, SPEECH):
        raise AssetError(f'Use: {COMMAND} picture "<what it shows>" <file.png>')
    kind, text, path = rest
    if size not in SIZES:
        raise AssetError("--size is one of: " + ", ".join(SIZES))
    if not text.strip() or len(text) > MAX_TEXT:
        raise AssetError("Say what to make, in at most 4,000 characters.")
    if not path.lower().endswith(ENDINGS[kind]):
        raise AssetError(f"A {kind} is saved as a {ENDINGS[kind][0]} file.")
    return Ask(kind, text, path, size, cwd)


def _note(notes: Path, key: str, ok: bool, message: str) -> None:
    notes.mkdir(parents=True, exist_ok=True)
    (notes / f"{key}.json").write_text(json.dumps({"ok": ok, "message": message}))


async def _picture(state: Any, identity: Any, ask: Ask) -> tuple[bytes, str]:
    done = await state.actions.run_action(
        "image.generate", {"prompt": ask.text, "size": ask.size}, "window",
        actor=identity, person_approved=True,
    )  # fmt: skip
    if done.status != "ok" or not done.output.get("image_id"):
        raise AssetError(done.text or "The picture could not be made.")
    try:
        from wasifyai_image.images import image_store
    except ImportError:
        raise AssetError("Pictures cannot be made here.") from None
    row = await image_store(state.engine).get(
        identity.tenant_id, identity.user_id, done.output["image_id"]
    )
    if row is None:
        raise AssetError("The picture was made and could not be read.")
    data = await state.storage.get_for(
        (identity.tenant_id, "wasifyai-image", identity.user_id), row.image_key
    )
    return data, f"{row.width} by {row.height}"


async def _speech(state: Any, identity: Any, ask: Ask) -> tuple[bytes, str]:
    done = await state.actions.run_action(
        "speech.speak", {"text": ask.text}, "window", actor=identity, person_approved=True
    )
    if done.status != "ok" or not done.output.get("speech_id"):
        raise AssetError(done.text or "The speech could not be made.")
    store = getattr(state, "voice_store", None)
    if store is None:
        raise AssetError("Speech cannot be made here.")
    row = await asyncio.to_thread(
        store.get_speech, identity.tenant_id, identity.user_id, done.output["speech_id"]
    )
    data = await state.storage.get_for(
        (identity.tenant_id, "wasifyai-voice", identity.user_id), row["audio_key"]
    )
    return data, f"{round(float(row['seconds']), 1)} seconds"


async def make(state: Any, identity: Any, workspace: Path, notes: Path, command: str) -> str:
    """Do what one let-through `wasify-make` asks: make it with the app's own product for the
    person, write it into the project, and leave the note the command reads. Gives the sentence
    that was left. It never raises: a failure is a note too."""
    key = hashlib.sha256(command.encode()).hexdigest()  # for a command that cannot be read
    try:
        ask = parse(command)
        key = ask.key
        went = path_in(workspace, ask.cwd) if ask.cwd else ""
        inside = (
            None
            if went is None
            else path_in(workspace, str(Path(went) / ask.path) if went else ask.path)
        )
        if inside is None:
            raise AssetError("The file must be inside this project.")
        if getattr(state, "actions", None) is None or getattr(state, "storage", None) is None:
            raise AssetError("Wasify AI's products cannot be used here.")
        data, about = await (_picture if ask.kind == PICTURE else _speech)(state, identity, ask)
        target = workspace / inside
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_bytes, data)
        message = f"Made {inside} ({about}). It is also in the person's library."
        ok = True
    except AssetError as e:
        ok, message = False, f"Nothing was made: {e}"
    except Exception:  # noqa: BLE001  (whatever a product raised: said, never thrown at the turn)
        ok, message = False, "Nothing was made: Wasify AI could not make it just now."
    await asyncio.to_thread(_note, notes, key, ok, message)
    return message
