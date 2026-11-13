"""Allowed folders under hostile paths (ADR-0069 decision 6; spike S2)."""

import os
import sys

import pytest
from wasifyai_platform_sdk.folders import AllowedFolders, PathRefused


@pytest.fixture
def world(tmp_path):
    """A home with Documents (read and write), a Pictures folder (read only), places outside,
    and the links an attacker would plant."""
    docs = tmp_path / "home" / "Documents"
    pics = tmp_path / "home" / "Pictures"
    secret = tmp_path / "etc" / "passwd"
    for d in (docs / "sub", pics, secret.parent, tmp_path / "home" / "Documents2"):
        d.mkdir(parents=True)
    (docs / "note.txt").write_text("hello")
    (docs / "sub" / "deep.txt").write_text("deep")
    (pics / "cat.png").write_bytes(b"png")
    secret.write_text("root:x")
    (tmp_path / "home" / "Documents2" / "x.txt").write_text("x")
    (docs / "out.txt").symlink_to(secret)  # a file link that leaves the folder
    (docs / "outdir").symlink_to(secret.parent)  # a folder link that leaves the folder
    (docs / "inlink.txt").symlink_to(docs / "note.txt")  # a link that stays inside
    (tmp_path / "home" / "Docs").symlink_to(docs)  # the folder itself, by another name
    os.mkfifo(docs / "pipe")
    folders = AllowedFolders.of(read=[str(pics)], write=[str(docs)])
    return tmp_path, docs, pics, secret, folders


def test_the_folders_and_honest_paths_work(world):
    root, docs, pics, _, f = world
    assert f.resolve(str(docs / "note.txt"), "read") == docs / "note.txt"
    assert f.resolve(str(docs / "sub" / "deep.txt"), "read") == docs / "sub" / "deep.txt"
    assert f.resolve(str(pics / "cat.png"), "read") == pics / "cat.png"
    assert f.resolve(str(docs / "inlink.txt"), "read") == docs / "note.txt"  # inside: fine
    assert f.resolve(str(root / "home" / "Docs" / "note.txt"), "read") == docs / "note.txt"
    assert f.resolve(str(docs / "new.wav"), "write") == docs / "new.wav"  # may not exist yet
    assert f.resolve(str(docs / "note.txt"), "write") == docs / "note.txt"  # overwriting a file
    assert f.resolve(str(docs / "sub" / "new.txt"), "write") == docs / "sub" / "new.txt"


HOSTILE = [
    # (what the client sends, mode, the rule that refuses it)
    ("note.txt", "read", "not_absolute"),
    ("~/Documents/note.txt", "read", "not_absolute"),
    ("file://{docs}/note.txt", "read", "not_absolute"),
    ("", "read", "no_path"),
    ("   ", "read", "no_path"),
    ("{docs}/../../etc/passwd", "read", "dotdot"),
    ("{docs}/sub/../note.txt", "read", "dotdot"),  # stays inside, still refused: no guessing
    ("{docs}/..", "write", "dotdot"),
    ("{docs}/note.txt\0.png", "read", "bad_characters"),
    ("{docs}/note\n.txt", "read", "bad_characters"),
    ("{docs}\\..\\..\\etc\\passwd", "read", "bad_characters"),
    ("{secret}", "read", "outside"),
    ("{root}/home/Documents2/x.txt", "read", "outside"),  # a prefix is not a folder
    ("{docs}/out.txt", "read", "outside"),  # a link that leaves the folder
    ("{docs}/outdir/passwd", "read", "outside"),  # through a linked folder
    ("{docs}/outdir/new.txt", "write", "outside"),
    ("{docs}/missing.txt", "read", "missing"),
    ("{docs}/sub", "read", "not_a_file"),
    ("{docs}/pipe", "read", "not_a_file"),
    ("{pics}/new.png", "write", "outside"),  # read-only folder
    ("{root}/home/new.txt", "write", "outside"),  # the folder's parent
    ("{docs}/nowhere/new.txt", "write", "no_folder"),
    ("{docs}/out.txt", "write", "link"),  # writing through a link
    ("{docs}/sub", "write", "not_a_file"),
    ("{docs}/pipe", "write", "not_a_file"),
    ("/", "write", "outside"),
]


@pytest.mark.parametrize(("raw", "mode", "code"), HOSTILE)
def test_hostile_paths_are_refused_with_the_rule_named(world, raw, mode, code):
    root, docs, pics, secret, f = world
    path = raw.format(root=root, docs=docs, pics=pics, secret=secret)
    with pytest.raises(PathRefused) as e:
        f.resolve(path, mode)
    assert e.value.code == code, e.value.message
    assert e.value.message.endswith(".")


def test_a_path_too_long_and_a_non_string_are_refused(world):
    *_, f = world
    with pytest.raises(PathRefused, match="too long"):
        f.resolve("/" + "a" * 5000, "read")
    with pytest.raises(PathRefused, match="full path"):
        f.resolve(None, "read")
    with pytest.raises(PathRefused, match="full path"):
        f.resolve(["/x"], "read")


@pytest.mark.skipif(sys.platform != "darwin", reason="a case-insensitive file system")
def test_another_spelling_of_the_folder_is_refused_not_guessed(world):
    _, docs, _, _, f = world
    other = str(docs).replace("Documents", "documents")
    with pytest.raises(PathRefused, match="outside"):
        f.resolve(f"{other}/note.txt", "read")


def test_an_empty_connection_may_read_and_write_nothing(world):
    _, docs, _, _, _ = world
    none = AllowedFolders()
    with pytest.raises(PathRefused, match="outside"):
        none.resolve(str(docs / "note.txt"), "read")
    with pytest.raises(PathRefused, match="outside"):
        none.resolve(str(docs / "new.txt"), "write")


def test_a_folder_to_write_into_must_be_one_of_the_write_folders(world):
    root, docs, pics, _, f = world
    assert f.resolve_folder(str(docs)) == docs
    assert f.resolve_folder(str(docs / "sub")) == docs / "sub"
    assert f.resolve_folder(str(root / "home" / "Docs")) == docs  # the folder by another name
    for raw, code in [
        (str(pics), "outside"),  # read only
        (str(root / "home"), "outside"),
        (str(docs / "outdir"), "outside"),  # a link that leaves
        (str(docs / "nowhere"), "no_folder"),
        (str(docs / "note.txt"), "no_folder"),  # a file, not a folder
        ("Documents", "not_absolute"),
        (str(docs / ".." / "Documents"), "dotdot"),
    ]:
        with pytest.raises(PathRefused) as e:
            f.resolve_folder(raw)
        assert e.value.code == code, raw
