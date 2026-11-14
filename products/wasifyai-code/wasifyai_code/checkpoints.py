"""Checkpoints and undo for a workspace (ADR-0103, decisions 11 to 13).

A second git store is kept **outside** the workspace, under the app's data folder, with the
workspace as its work tree. Nothing of ours is ever written into the project, it works where the
project has no git of its own, and it sits where the sandbox does not let the agent write.

    store = CheckpointStore(data / "checkpoints" / workspace_id, workspace)
    before = store.checkpoint("before the turn")     # every file, as one commit in our store
    store.changed_since(before.id)                   # did files change? (rule 4 of the loop)
    store.undo(before.id)                            # one more checkpoint first, then put it back

What a checkpoint holds, and what it does not (the open points of decision 13, settled here; see
`docs/spikes/coding-cores.md`):

- **Files**: every file git does not ignore, with its content, its executable bit, links as links.
  Line endings and filters named in the project's `.gitattributes` are switched off for our store,
  so a file comes back byte for byte.
- **Ignored files are left out** (`.env`, `node_modules`, build output), as the ADR proposed.
  `left_out()` names them so that the screen can say so. Undo does not touch them.
- **The person's own git**: where `HEAD` points, the commit of that branch, and the index (what is
  staged) are saved with each checkpoint and put back by undo. Other branches, tags, stashes and
  a merge in progress are not.
- **A project inside the project** (a folder with its own `.git`): its files are kept as plain
  files, like any others. Its own git state (its `HEAD`, its index) is not saved. Left to itself
  git would keep only a pointer for such a folder, or refuse the whole checkpoint when the inner
  project has no commit yet; `_stage` is how that is avoided.
- **Empty folders** are remembered and made again; **permissions** other than the usual two are
  remembered and set again. Git keeps neither by itself.

Every git call runs with the person's and the system's git configuration switched off, so a
setting of theirs (hooks, signing, line endings, a global ignore file) cannot change what a
checkpoint holds. The functions here block (they run git); call them from a worker thread.
"""

import json
import os
import re
import stat
import subprocess
import tempfile
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HEAD_REF = "refs/wasify/head"
SIDE_FILE, INDEX_FILE = "state.json", "index"
# what the project's .gitattributes may ask for and our store must not do: a checkpoint is bytes
ATTRIBUTES = "* -text -eol -filter -ident -working-tree-encoding\n"
USUAL_MODES = (0o644, 0o755)
_ID = re.compile(r"[0-9a-f]{40,64}")


class CheckpointError(Exception):
    """Git could not do it. The message is git's own."""


@dataclass(frozen=True)
class Checkpoint:
    id: str  # the commit in our store
    tree: (
        str  # the files, as git names them: two checkpoints with the same tree hold the same files
    )
    label: str
    at: str  # UTC, ISO
    left_out: tuple[str, ...] = ()  # ignored files and folders that are not in it


@dataclass(frozen=True)
class Change:
    path: str
    what: str  # "added" | "changed" | "deleted"


@dataclass(frozen=True)
class Undone:
    to: str  # the checkpoint the files were put back to
    before: Checkpoint  # the checkpoint taken first: undo this undo by going back to it
    notes: tuple[str, ...] = field(default=())  # anything that could not be put back, in words


class CheckpointStore:
    """One workspace's checkpoints. `store` is our folder (made on first use); `workspace` is the
    person's folder. One instance may be shared by threads."""

    def __init__(self, store: Path, workspace: Path, *, git: str = "git"):
        self.store, self.workspace, self._git_bin = Path(store), Path(workspace), git
        self._lock = threading.RLock()

    # ---- what the loop calls -------------------------------------------------------------------

    def checkpoint(self, label: str = "") -> Checkpoint:
        """Keep the workspace as it is now."""
        with self._lock:
            self._open()
            tree = self._stage()
            side = self._side_commit()
            parent = self._git("rev-parse", "-q", "--verify", HEAD_REF, check=False).strip()
            parents = ["-p", side, *(["-p", parent] if parent else [])]
            commit = self._git("commit-tree", tree, *parents, "-m", label or "checkpoint").strip()
            self._git("update-ref", HEAD_REF, commit)
            return self._describe(commit, with_left_out=True)

    def tree(self) -> str:
        """The workspace's files as they are now, as a tree id. No checkpoint is made."""
        with self._lock:
            self._open()
            return self._stage()

    def changed_since(self, checkpoint: str) -> bool:
        """Do the workspace's files differ from that checkpoint? (Ignored files do not count.)"""
        with self._lock:
            return self.tree() != self._tree_of(checkpoint)

    def changes(self, since: str, until: str | None = None) -> list[Change]:
        """The files that differ between a checkpoint and a later one (or the workspace now)."""
        with self._lock:
            end = self._tree_of(until) if until else self.tree()
            out = self._git(
                "diff-tree", "-r", "-z", "--no-renames", "--name-status", self._tree_of(since), end
            )
        words = {"A": "added", "D": "deleted"}
        parts = out.split("\0")
        return [
            Change(path, words.get(status[:1], "changed"))
            for status, path in zip(parts[0::2], parts[1::2], strict=False)
            if path
        ]

    def undo(self, to: str) -> Undone:
        """Put the workspace back to a checkpoint. One more checkpoint is taken first, so that this
        undo can itself be undone (`Undone.before`)."""
        with self._lock:
            target = self._tree_of(to)  # an unknown checkpoint fails here, before anything changes
            before = self.checkpoint("before undo")
            self._git("read-tree", "--reset", "-u", target)
            state = self._side_state(to)
            notes = self._restore_folders(state) + self._restore_modes(state)
            notes += self._restore_person_git(to, state)
            return Undone(to=to, before=before, notes=tuple(notes))

    def left_out(self) -> list[str]:
        """The ignored files and folders in the workspace: what a checkpoint does not hold. A
        folder that is ignored whole is named once, with a slash at its end."""
        with self._lock:
            self._open()
            out = self._git("ls-files", "-o", "-i", "--exclude-standard", "--directory", "-z")
        paths = sorted(p for p in out.split("\0") if p)
        folders = tuple(p for p in paths if p.endswith("/"))
        return [p for p in paths if not any(p != f and p.startswith(f) for f in folders)]

    def history(self) -> list[Checkpoint]:
        """Every checkpoint, the newest first."""
        with self._lock:
            if not self.store.is_dir():
                return []
            # a checkpoint's first parent is its side commit and its second the checkpoint before
            commits, at = (
                [],
                self._git("rev-parse", "-q", "--verify", HEAD_REF, check=False).strip(),
            )
            while at:
                commits.append(at)
                at = self._git("rev-parse", "-q", "--verify", f"{at}^2", check=False).strip()
            return [self._describe(c) for c in commits]

    # ---- staging: the workspace into our index ---------------------------------------------------

    def _stage(self) -> str:
        """Bring our index up to the workspace and give its tree.

        `git add -A` does it all, except for a folder that holds its own `.git`: git would record a
        pointer for it and none of its files, and if that inner project has no commit yet the whole
        `add` fails. Once one file of such a folder is in our index, git treats the folder as an
        ordinary one from then on. So each such folder's files are put in by name first; a folder
        with nothing to keep is left out of the `add`."""
        others = self._git("ls-files", "-o", "--exclude-standard", "-z").split("\0")
        skip: list[str] = []
        for inner in (p[:-1] for p in others if p.endswith("/")):
            files = self._files_inside(inner)
            if files:
                self._git("update-index", "--add", "-z", "--stdin", stdin="\0".join(files) + "\0")
            else:
                skip.append(inner)
        self._git("add", "-A", "--", ".", *(f":(exclude,literal){p}" for p in skip))
        return self._git("write-tree").strip()

    def _files_inside(self, folder: str) -> list[str]:
        """The files of a folder that has its own `.git`, as paths from the workspace's top: what
        that project does not ignore, less what ours ignores. Deeper projects are followed too."""
        with tempfile.TemporaryDirectory() as tmp:
            env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}  # an empty index: every file is new
            out = self._git(
                "ls-files",
                "-o",
                "--exclude-standard",
                "-z",
                work_tree=self.workspace / folder,
                env=env,
            )
        found: list[str] = []
        for name in (n for n in out.split("\0") if n):
            if name.endswith("/"):
                found += self._files_inside(f"{folder}/{name[:-1]}")
            else:
                found.append(f"{folder}/{name}")
        if not found:
            return []
        ignored = self._git(
            "check-ignore", "-z", "--stdin", "--no-index", stdin="\0".join(found) + "\0", ok=(0, 1)
        )
        drop = {p for p in ignored.split("\0") if p}
        return [p for p in found if p not in drop]

    # ---- what git does not keep by itself --------------------------------------------------------

    def _side_commit(self) -> str:
        """A small commit beside the checkpoint: the person's git state, the empty folders and the
        unusual permissions. It is the checkpoint's first parent, so it lives as long as it does."""
        state: dict[str, Any] = {"empty": self._empty_folders(), "modes": self._unusual_modes()}
        entries = []
        person = self._person_git_dir()
        if person is not None:
            head = _run_git(
                self._git_bin, ["symbolic-ref", "-q", "HEAD"], git_dir=person, ok=(0, 1)
            )
            commit = _run_git(
                self._git_bin,
                ["rev-parse", "-q", "--verify", "HEAD^{commit}"],
                git_dir=person,
                ok=(0, 1),
            )
            theirs: dict[str, Any] = {"ref": head.strip() or None, "commit": commit.strip() or None}
            state["git"] = theirs
            index = person / "index"
            if index.is_file():
                blob = self._git("hash-object", "-w", "--no-filters", str(index)).strip()
                entries.append(f"100644 blob {blob}\t{INDEX_FILE}")
                theirs["index"] = True
        text = json.dumps(state, sort_keys=True)
        blob = self._git("hash-object", "-w", "--stdin", stdin=text).strip()
        entries.append(f"100644 blob {blob}\t{SIDE_FILE}")
        tree = self._git(
            "mktree", stdin="\n".join(sorted(entries, key=lambda e: e.split("\t")[1])) + "\n"
        )
        return self._git("commit-tree", tree.strip(), "-m", "state").strip()

    def _side_state(self, checkpoint: str) -> dict[str, Any]:
        return json.loads(self._git("cat-file", "blob", f"{checkpoint}^1:{SIDE_FILE}"))

    def _empty_folders(self) -> list[str]:
        """Folders with nothing in them. After staging, git lists a folder as "other" only when it
        has no kept file: either it is empty (perhaps but for empty folders) or it holds ignored
        files only. The second kind is left out, like every ignored thing."""
        out = self._git("ls-files", "-o", "--exclude-standard", "--directory", "-z")
        empty: list[str] = []
        for top in (p[:-1] for p in out.split("\0") if p.endswith("/")):
            leaves: list[str] = []
            for folder, folders, files in os.walk(self.workspace / top):
                if files or ".git" in folders:
                    leaves = []
                    break
                if not folders:
                    leaves.append(str(Path(folder).relative_to(self.workspace)))
            empty += leaves
        return sorted(empty)

    def _unusual_modes(self) -> dict[str, int]:
        """Permissions git does not keep: it knows "runs" and "does not run" and nothing else."""
        modes: dict[str, int] = {}
        for path in self._git("ls-files", "-z").split("\0"):
            if not path:
                continue
            try:
                st = os.lstat(self.workspace / path)
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode) and stat.S_IMODE(st.st_mode) not in USUAL_MODES:
                modes[path] = stat.S_IMODE(st.st_mode)
        return modes

    def _restore_folders(self, state: dict[str, Any]) -> list[str]:
        wanted = set(state.get("empty", []))
        for folder in sorted(set(self._empty_folders()) - wanted, key=len, reverse=True):
            # only ever a folder with nothing in it; then the folders above it that this leaves
            # empty, up to one that was empty at the checkpoint too
            at = Path(folder)
            while at != Path(".") and str(at) not in wanted:
                try:
                    os.rmdir(self.workspace / at)
                except OSError:
                    break
                at = at.parent
        notes = []
        for folder in sorted(wanted):
            try:
                (self.workspace / folder).mkdir(parents=True, exist_ok=True)
            except OSError as e:
                notes.append(f"The empty folder {folder} could not be made again: {e.strerror}.")
        return notes

    def _restore_modes(self, state: dict[str, Any]) -> list[str]:
        notes = []
        wanted: dict[str, int] = state.get("modes", {})
        for path, mode in self._unusual_modes().items():
            if path not in wanted:  # unusual now, usual then: git put back only "runs" or not
                try:
                    os.chmod(self.workspace / path, 0o755 if mode & 0o100 else 0o644)
                except OSError as e:
                    notes.append(f"The permissions of {path} could not be set again: {e.strerror}.")
        for path, mode in wanted.items():
            target = self.workspace / path
            try:
                st = os.lstat(target)
                if stat.S_ISREG(st.st_mode) and stat.S_IMODE(st.st_mode) != mode:
                    os.chmod(target, mode)
            except OSError as e:
                notes.append(f"The permissions of {path} could not be set again: {e.strerror}.")
        return notes

    # ---- the person's own git --------------------------------------------------------------------

    def _person_git_dir(self) -> Path | None:
        """The git folder of the person's project, if the workspace is the top of one."""
        if not (self.workspace / ".git").exists():
            return None
        out = _run_git(
            self._git_bin, ["rev-parse", "--absolute-git-dir"], cwd=self.workspace, ok=(0, 128)
        ).strip()
        return Path(out) if out else None

    def _restore_person_git(self, checkpoint: str, state: dict[str, Any]) -> list[str]:
        """Put the person's `HEAD` and index back as they were at the checkpoint. The commits the
        agent made are not deleted: they stay in the person's git, reachable from its reflog."""
        saved = state.get("git")
        person = self._person_git_dir()
        if saved is None or person is None:
            return []
        notes: list[str] = []

        def run(*args: str) -> None:
            try:
                _run_git(self._git_bin, list(args), git_dir=person)
            except CheckpointError as e:
                notes.append(f"Your own git could not be put back ({' '.join(args[:2])}): {e}")

        ref, commit = saved.get("ref"), saved.get("commit")
        why = "wasify: undo"
        if ref and commit:  # on a branch that had a commit
            run("update-ref", "-m", why, ref, commit)
            run("symbolic-ref", "-m", why, "HEAD", ref)
        elif ref:  # on a branch with no commit yet: whatever was committed since goes from it
            now_at = _run_git(
                self._git_bin, ["rev-parse", "-q", "--verify", ref], git_dir=person, ok=(0, 1)
            ).strip()
            if now_at:
                run("update-ref", "-m", why, "-d", ref)
            run("symbolic-ref", "-m", why, "HEAD", ref)
        elif commit:  # no branch: HEAD named a commit itself
            run("update-ref", "-m", why, "--no-deref", "HEAD", commit)
        index = person / "index"
        if saved.get("index"):
            data = self._git_bytes("cat-file", "blob", f"{checkpoint}^1:{INDEX_FILE}")
            fd, tmp = tempfile.mkstemp(dir=person, prefix="index.wasify.")
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                os.replace(tmp, index)
            except OSError as e:
                Path(tmp).unlink(missing_ok=True)
                notes.append(f"What you had staged could not be put back: {e.strerror}.")
        elif index.exists():
            index.unlink()  # nothing was staged and nothing had ever been: no index at all
        return notes

    # ---- git -------------------------------------------------------------------------------------

    def _open(self) -> None:
        if (self.store / "HEAD").is_file():
            return
        if not self.workspace.is_dir():
            raise CheckpointError(f"the workspace is not a folder: {self.workspace}")
        if self.store.resolve().is_relative_to(self.workspace.resolve()):
            # inside the workspace the agent could write to it, and it would be one of the files
            raise CheckpointError("the checkpoint store must be outside the workspace")
        self.store.mkdir(parents=True, exist_ok=True)
        _run_git(self._git_bin, ["init", "-q", "--bare", str(self.store)])
        (self.store / "info").mkdir(exist_ok=True)
        (self.store / "info" / "attributes").write_text(ATTRIBUTES)
        (self.store / "info" / "exclude").write_text("")

    def _git(
        self,
        *args: str,
        stdin: str | None = None,
        check: bool = True,
        ok: Sequence[int] = (0,),
        work_tree: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        return _run_git(
            self._git_bin,
            list(args),
            git_dir=self.store,
            work_tree=work_tree or self.workspace,
            stdin=stdin,
            ok=None if not check else ok,
            env=env,
        )

    def _git_bytes(self, *args: str) -> bytes:
        return _run_git_bytes(
            self._git_bin, list(args), git_dir=self.store, work_tree=self.workspace
        )

    def _tree_of(self, checkpoint: str) -> str:
        if not _ID.fullmatch(checkpoint) or not (self.store / "HEAD").is_file():
            raise CheckpointError(f"no such checkpoint: {checkpoint}")
        tree = self._git(
            "rev-parse", "-q", "--verify", f"{checkpoint}^{{tree}}", check=False
        ).strip()
        if not tree:
            raise CheckpointError(f"no such checkpoint: {checkpoint}")
        return tree

    def _describe(self, commit: str, *, with_left_out: bool = False) -> Checkpoint:
        out = self._git("show", "-s", "--format=%T%x00%cI%x00%B", commit)
        tree, at, label = out.split("\0", 2)
        at = datetime.fromisoformat(at).astimezone(UTC).isoformat()
        left = tuple(self.left_out()) if with_left_out else ()
        return Checkpoint(commit, tree, label.strip(), at, left)


# settings a checkpoint must not inherit from anyone, given on every call
_SETTINGS = (
    "core.autocrlf=false",
    "core.safecrlf=false",
    "core.fileMode=true",
    "core.symlinks=true",
    "core.quotePath=false",
    "core.excludesFile=/dev/null",
    "core.hooksPath=/dev/null",
    "core.fsmonitor=false",
    "core.untrackedCache=false",
    "commit.gpgSign=false",
    "gc.auto=0",
    "advice.addEmbeddedRepo=false",
    "user.name=Wasify AI",
    "user.email=checkpoints@wasify.invalid",
)


def _env(extra: dict[str, str] | None) -> dict[str, str]:
    """git's environment: nothing of the caller's git setup (`GIT_DIR` and its like), and neither
    the person's nor the system's configuration."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_SYSTEM=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
        LC_ALL="C",
    )
    env.update(extra or {})
    return env


def _run_git_bytes(
    git: str,
    args: list[str],
    *,
    git_dir: Path | None = None,
    work_tree: Path | None = None,
    cwd: Path | None = None,
    stdin: bytes | None = None,
    ok: Sequence[int] | None = (0,),
    env: dict[str, str] | None = None,
) -> bytes:
    cmd = [git]
    for setting in _SETTINGS:
        cmd += ["-c", setting]
    if git_dir is not None:
        cmd += [f"--git-dir={git_dir}"]
    if work_tree is not None:
        cmd += [f"--work-tree={work_tree}"]
    try:
        done = subprocess.run(  # noqa: S603  (git, with arguments we build)
            [*cmd, *args],
            input=stdin,
            capture_output=True,
            env=_env(env),
            cwd=cwd or work_tree or git_dir,
            check=False,
        )
    except OSError as e:
        raise CheckpointError(f"git could not be started: {e}") from e
    if ok is not None and done.returncode not in ok:
        words = (
            done.stderr.decode(errors="replace").strip()
            or f"git {args[0]} ended with {done.returncode}"
        )
        raise CheckpointError(words)
    return done.stdout


def _run_git(
    git: str,
    args: list[str],
    *,
    git_dir: Path | None = None,
    work_tree: Path | None = None,
    cwd: Path | None = None,
    stdin: str | None = None,
    ok: Sequence[int] | None = (0,),
    env: dict[str, str] | None = None,
) -> str:
    out = _run_git_bytes(
        git,
        args,
        git_dir=git_dir,
        work_tree=work_tree,
        cwd=cwd,
        stdin=stdin.encode(errors="surrogateescape") if stdin is not None else None,
        ok=ok,
        env=env,
    )
    return out.decode(errors="surrogateescape")
