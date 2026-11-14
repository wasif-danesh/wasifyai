"""Checkpoints and undo (ADR-0103, decisions 11 to 13) with a real git on real folders."""

import os
import stat
import subprocess
from pathlib import Path

import pytest
from wasifyai_code.checkpoints import Change, CheckpointError, CheckpointStore

PNG = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0, 0, 0, 13, 0xFF, 0xFE, 0x00, 0x80])


def git(folder: Path, *args: str) -> str:
    """The person's own git, with nothing of this machine's setup."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    done = subprocess.run(
        [
            "git",
            "-c",
            "user.name=Person",
            "-c",
            "user.email=person@example.invalid",
            "-c",
            "init.defaultBranch=main",
            *args,
        ],
        cwd=folder,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def look(root: Path, *, inside_git: bool = False) -> dict[str, tuple]:
    """Everything in a folder: each path with what it is, what it holds and its permissions.
    Folders are listed too, so an empty one shows. `.git` folders are left out unless asked."""
    seen: dict[str, tuple] = {}
    for folder, folders, files in os.walk(root):
        if not inside_git and ".git" in folders:
            folders.remove(".git")
        for name in [*folders, *files]:
            path = Path(folder) / name
            rel = str(path.relative_to(root))
            st = os.lstat(path)
            if stat.S_ISLNK(st.st_mode):
                seen[rel] = ("link", os.readlink(path))
            elif stat.S_ISDIR(st.st_mode):
                seen[rel] = ("folder",)
            else:
                seen[rel] = ("file", path.read_bytes(), stat.S_IMODE(st.st_mode))
    return seen


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    """A small project with one of everything a turn might touch."""
    w = tmp_path / "project"
    (w / "src").mkdir(parents=True)
    (w / "src" / "app.py").write_text("print('one')\n")
    (w / "src" / "old.py").write_text("gone soon\n")
    (w / "logo.png").write_bytes(PNG)
    (w / "run.sh").write_text("#!/bin/sh\necho hi\n")
    (w / "run.sh").chmod(0o755)
    (w / "plain.sh").write_text("echo plain\n")
    (w / "secret.pem").write_text("key\n")
    (w / "secret.pem").chmod(0o600)
    (w / "current").symlink_to("src/app.py")
    (w / "empty" / "inner").mkdir(parents=True)
    (w / ".gitignore").write_text(".env\nnode_modules/\n")
    (w / ".env").write_text("TOKEN=one\n")
    (w / "node_modules" / "lib").mkdir(parents=True)
    (w / "node_modules" / "lib" / "index.js").write_text("module.exports = 1\n")
    return w


@pytest.fixture
def store(tmp_path: Path, ws: Path) -> CheckpointStore:
    return CheckpointStore(tmp_path / "data" / "checkpoints" / "w1", ws)


def a_turn(w: Path) -> None:
    """What an agent might do in one turn: every kind of change the spike tried."""
    (w / "src" / "app.py").write_text("print('two')\n")  # an edit
    (w / "src" / "old.py").unlink()  # a delete
    (w / "docs" / "guide").mkdir(parents=True)  # new files in new folders
    (w / "docs" / "guide" / "start.md").write_text("# Start\n")
    (w / "logo.png").write_bytes(PNG[::-1])  # a binary replaced
    (w / "run.sh").chmod(0o644)  # two modes changed
    (w / "plain.sh").chmod(0o755)
    (w / "secret.pem").chmod(0o644)
    (w / "current").unlink()  # a link pointed elsewhere
    (w / "current").symlink_to("run.sh")
    (w / "empty" / "inner").rmdir()  # an empty folder removed
    (w / "empty").rmdir()
    (w / "scratch").mkdir()  # and an empty one made


def test_a_turn_is_undone_exactly_and_nothing_of_ours_is_in_the_workspace(store, ws):
    before = look(ws)
    first = store.checkpoint("before the turn")
    a_turn(ws)
    assert look(ws) != before

    undone = store.undo(first.id)

    assert look(ws) == before
    assert undone.notes == ()
    assert not (ws / ".git").exists()  # nothing of ours in the project
    assert sorted(p.name for p in ws.iterdir()) == sorted(
        [
            ".env",
            ".gitignore",
            "current",
            "empty",
            "logo.png",
            "node_modules",
            "plain.sh",
            "run.sh",
            "secret.pem",
            "src",
        ]
    )


def test_an_undo_can_itself_be_undone(store, ws):
    first = store.checkpoint("before the turn")
    a_turn(ws)
    after_turn = look(ws)

    undone = store.undo(first.id)
    assert look(ws) != after_turn
    store.undo(undone.before.id)

    assert look(ws) == after_turn
    assert [c.label for c in store.history()][-1] == "before the turn"
    assert [c.label for c in store.history()][:2] == ["before undo", "before undo"]


def test_did_files_change_since_a_checkpoint(store, ws):
    first = store.checkpoint("start")
    assert store.changed_since(first.id) is False
    assert store.tree() == first.tree

    (ws / "src" / "app.py").write_text("print('two')\n")
    assert store.changed_since(first.id) is True

    (ws / "src" / "app.py").write_text("print('one')\n")  # put back by hand: the same files again
    assert store.changed_since(first.id) is False

    (ws / "run.sh").chmod(0o644)  # "runs" and "does not run" is a change
    assert store.changed_since(first.id) is True


def test_the_changes_between_two_checkpoints_are_named(store, ws):
    first = store.checkpoint("start")
    a_turn(ws)
    assert sorted(store.changes(first.id), key=lambda c: c.path) == [
        Change("current", "changed"),
        Change("docs/guide/start.md", "added"),
        Change("logo.png", "changed"),
        Change("plain.sh", "changed"),
        Change("run.sh", "changed"),
        Change("src/app.py", "changed"),
        Change("src/old.py", "deleted"),
    ]
    second = store.checkpoint("after")
    assert store.changes(first.id, second.id) == store.changes(first.id)
    assert store.changes(second.id) == []


def test_ignored_files_are_left_out_and_the_checkpoint_says_so(store, ws):
    first = store.checkpoint("start")
    assert first.left_out == (".env", "node_modules/")
    assert store.left_out() == [".env", "node_modules/"]

    (ws / ".env").write_text("TOKEN=two\n")
    (ws / "node_modules" / "lib" / "index.js").write_text("module.exports = 2\n")
    assert store.changed_since(first.id) is False  # an ignored file is not a change

    (ws / "src" / "app.py").write_text("print('two')\n")
    store.undo(first.id)

    assert (ws / "src" / "app.py").read_text() == "print('one')\n"
    assert (ws / ".env").read_text() == "TOKEN=two\n"  # undo did not touch what it does not keep
    assert (ws / "node_modules" / "lib" / "index.js").read_text() == "module.exports = 2\n"


def test_a_file_comes_back_byte_for_byte_whatever_the_project_says_about_line_endings(store, ws):
    (ws / ".gitattributes").write_text("* text=auto eol=crlf\n*.dat filter=lfs\n")
    (ws / "windows.txt").write_bytes(b"one\r\ntwo\r\n")
    (ws / "mixed.txt").write_bytes(b"one\ntwo\r\nthree")
    (ws / "big.dat").write_bytes(b"\x00\x01data\r\n")
    before = look(ws)
    first = store.checkpoint("start")
    for name in ("windows.txt", "mixed.txt", "big.dat"):
        (ws / name).unlink()

    store.undo(first.id)

    assert look(ws) == before


def test_it_works_where_the_project_has_no_git_and_where_it_has(store, ws):
    assert not (ws / ".git").exists()
    first = store.checkpoint("no git")
    (ws / "src" / "app.py").write_text("changed\n")
    store.undo(first.id)
    assert (ws / "src" / "app.py").read_text() == "print('one')\n"


def test_the_persons_own_commit_branch_and_staged_file_are_put_back(store, ws):
    git(ws, "init", "-q")
    git(ws, "add", "src", ".gitignore")
    git(ws, "commit", "-qm", "the person's commit")
    (ws / "run.sh").write_text("#!/bin/sh\necho staged\n")
    git(ws, "add", "run.sh")  # staged, not committed
    (ws / "src" / "app.py").write_text("print('edited, not staged')\n")
    head, status = git(ws, "rev-parse", "HEAD"), git(ws, "status", "--porcelain=v1")
    assert "A  run.sh" in status and " M src/app.py" in status
    files = look(ws)

    first = store.checkpoint("before the turn")
    # the agent stages everything, commits, makes a branch and commits again
    (ws / "src" / "new.py").write_text("x = 1\n")
    git(ws, "add", "-A")
    git(ws, "commit", "-qm", "the agent's commit")
    git(ws, "checkout", "-q", "-b", "agent-branch")
    (ws / "src" / "more.py").write_text("y = 2\n")
    git(ws, "add", "-A")
    git(ws, "commit", "-qm", "the agent's second commit")
    agents = git(ws, "rev-parse", "HEAD")

    undone = store.undo(first.id)

    assert undone.notes == ()
    assert look(ws) == files
    assert git(ws, "rev-parse", "HEAD") == head
    assert git(ws, "symbolic-ref", "HEAD") == "refs/heads/main"
    assert git(ws, "status", "--porcelain=v1") == status  # the same file staged, the same edit not
    assert git(ws, "cat-file", "-t", agents) == "commit"  # the agent's commits are not destroyed
    assert git(ws, "fsck", "--no-dangling") == ""

    store.undo(undone.before.id)  # and back again: the agent's branch and commit
    assert git(ws, "rev-parse", "HEAD") == agents
    assert git(ws, "symbolic-ref", "HEAD") == "refs/heads/agent-branch"
    assert git(ws, "status", "--porcelain=v1") == ""


def test_a_project_whose_git_has_no_commit_yet_gets_its_empty_state_back(store, ws):
    git(ws, "init", "-q")
    first = store.checkpoint("before")
    git(ws, "add", "-A")
    git(ws, "commit", "-qm", "the agent's commit")

    store.undo(first.id)

    with pytest.raises(subprocess.CalledProcessError):
        git(ws, "rev-parse", "--verify", "HEAD")  # no commit again
    assert git(ws, "symbolic-ref", "HEAD") == "refs/heads/main"
    assert git(ws, "status", "--porcelain=v1").startswith("??")  # nothing staged


def test_a_project_inside_the_project_is_kept_as_plain_files(store, ws):
    """Open point 3 of ADR-0103, decision 13. Left to itself git keeps only a pointer for a folder
    with its own `.git`, and fails altogether when that inner project has no commit."""
    committed, fresh, deep = ws / "vendor" / "lib", ws / "fresh", ws / "vendor" / "lib" / "deeper"
    for folder in (committed, fresh, deep):
        folder.mkdir(parents=True)
    (committed / "lib.py").write_text("v = 1\n")
    (committed / ".gitignore").write_text("build/\n")
    (committed / "build").mkdir()
    (committed / "build" / "out.bin").write_bytes(b"\x00built")
    (committed / "notes.env.txt").write_text("kept\n")
    (fresh / "main.py").write_text("print('fresh')\n")
    (deep / "deep.txt").write_text("deep\n")
    git(committed, "init", "-q")
    git(committed, "add", "lib.py", ".gitignore")
    git(committed, "commit", "-qm", "inner commit")
    git(fresh, "init", "-q")  # no commit at all
    git(deep, "init", "-q")
    inner_head = git(committed, "rev-parse", "HEAD")
    before = look(ws)

    first = store.checkpoint("with inner projects")
    assert "vendor/lib/build/" in first.left_out  # the inner project's own ignore rules hold
    listed = subprocess.run(
        ["git", f"--git-dir={store.store}", "ls-tree", "-r", first.tree],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "160000" not in listed  # no pointer in place of a folder
    for path in ("vendor/lib/lib.py", "vendor/lib/deeper/deep.txt", "fresh/main.py"):
        assert f"\t{path}\n" in listed

    (committed / "lib.py").write_text("v = 2\n")
    (fresh / "main.py").unlink()
    (deep / "deep.txt").write_text("changed\n")
    (committed / "added.py").write_text("new\n")
    assert sorted(c.path for c in store.changes(first.id)) == [
        "fresh/main.py",
        "vendor/lib/added.py",
        "vendor/lib/deeper/deep.txt",
        "vendor/lib/lib.py",
    ]
    second = store.checkpoint("every file of one inner project deleted")  # must not fail
    assert second.tree != first.tree

    store.undo(first.id)

    assert look(ws) == before
    assert (committed / "build" / "out.bin").read_bytes() == b"\x00built"
    assert git(committed, "rev-parse", "HEAD") == inner_head  # its own git is not ours to move
    assert (fresh / ".git").is_dir() and (deep / ".git").is_dir()


def test_an_inner_project_with_nothing_to_keep_does_not_stop_a_checkpoint(store, ws):
    (ws / "bare-inner").mkdir()
    git(ws / "bare-inner", "init", "-q")
    first = store.checkpoint("start")
    (ws / "src" / "app.py").write_text("changed\n")
    assert store.changed_since(first.id) is True
    store.undo(first.id)
    assert (ws / "src" / "app.py").read_text() == "print('one')\n"
    assert (ws / "bare-inner" / ".git").is_dir()


def test_the_persons_git_settings_and_hooks_do_not_reach_our_store(
    store, ws, tmp_path, monkeypatch
):
    home = tmp_path / "home"
    (home / ".config" / "git").mkdir(parents=True)
    (home / ".config" / "git" / "ignore").write_text("*.py\n")  # a global ignore file
    (home / ".gitconfig").write_text(
        "[core]\n\tautocrlf = true\n[commit]\n\tgpgSign = true\n[user]\n\tsigningKey = NOBODY\n"
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "somewhere-else"))
    before = look(ws)

    first = store.checkpoint("start")
    assert "src/app.py" not in first.left_out and store.left_out() == [".env", "node_modules/"]
    (ws / "src" / "app.py").unlink()
    store.undo(first.id)

    assert look(ws) == before


def test_an_unknown_checkpoint_is_refused_before_anything_changes(store, ws):
    store.checkpoint("start")
    (ws / "src" / "app.py").write_text("changed\n")
    count = len(store.history())
    for bad in ("0" * 40, "--help", "HEAD"):
        with pytest.raises(CheckpointError):
            store.undo(bad)
    assert (ws / "src" / "app.py").read_text() == "changed\n"
    assert len(store.history()) == count  # not even the checkpoint an undo takes first


def test_checkpoints_are_listed_newest_first_and_a_new_store_has_none(store, ws):
    assert store.history() == []
    one = store.checkpoint("one")
    (ws / "src" / "app.py").write_text("changed\n")
    two = store.checkpoint("two")
    assert [(c.id, c.label) for c in store.history()] == [(two.id, "two"), (one.id, "one")]
    assert one.at.endswith("+00:00")


def test_a_second_checkpoint_of_a_large_folder_reads_only_what_changed(store, ws):
    for n in range(300):
        (ws / "src" / f"m{n}.py").write_text(f"n = {n}\n")
    first = store.checkpoint("many")
    (ws / "src" / "m7.py").write_text("n = 'seven'\n")
    assert [c.path for c in store.changes(first.id)] == ["src/m7.py"]


def test_a_store_inside_the_workspace_is_refused(ws):
    inside = CheckpointStore(ws / ".wasify" / "checkpoints", ws)
    with pytest.raises(CheckpointError, match="outside the workspace"):
        inside.checkpoint("start")
    assert not (ws / ".wasify").exists()
