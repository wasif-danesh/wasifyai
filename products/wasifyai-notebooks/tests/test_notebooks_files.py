"""Where a notebook's files are kept: folders on the desktop, objects on the web."""

import pytest
from wasifyai_notebooks.files import LocalFiles, ObjectFiles, artifact_key, original_key
from wasifyai_platform_sdk import memory_storage


@pytest.fixture(params=["folder", "object"])
def library(request, tmp_path):
    if request.param == "folder":
        return LocalFiles(tmp_path / "nb")
    return ObjectFiles(memory_storage())


def test_a_file_is_kept_read_and_removed(library, tmp_path):
    fs = library.for_owner("t1", "u1")
    key = "files/n1/d1/report.pdf"
    assert not fs.exists(key) and fs.read_bytes(key) is None
    fs.put_bytes(key, b"%PDF-body", "application/pdf")
    assert fs.exists(key) and fs.read_bytes(key) == b"%PDF-body"
    source = tmp_path / "local.bin"
    source.write_bytes(b"from a file")
    fs.put_file("files/n1/d2/other.bin", source)
    assert fs.read_bytes("files/n1/d2/other.bin") == b"from a file"

    # a reader that needs a path gets one, and a missing file gives None
    with fs.local(key) as path:
        assert path is not None and path.read_bytes() == b"%PDF-body"
    with fs.local("files/n1/d1/missing.pdf") as path:
        assert path is None

    fs.delete_prefix("files/n1/d1")
    assert not fs.exists(key) and fs.exists("files/n1/d2/other.bin")
    fs.delete_prefix("files/n1/d1")  # nothing there is not an error
    fs.delete_prefix("files/n1")
    assert not fs.exists("files/n1/d2/other.bin")


def test_removing_a_folder_leaves_one_whose_name_only_starts_the_same(library):
    fs = library.for_owner("t1", "u1")
    fs.put_bytes("files/n1/d/a.txt", b"one")
    fs.put_bytes("files/n10/d/a.txt", b"ten")
    fs.delete_prefix("files/n1")
    assert not fs.exists("files/n1/d/a.txt") and fs.exists("files/n10/d/a.txt")


def test_a_key_cannot_leave_the_store(library):
    fs = library.for_owner("t1", "u1")
    for bad in ("../outside", "files/../../x", "", "/", "a/./b", "a\\b"):
        with pytest.raises(ValueError):
            fs.put_bytes(bad, b"x")
        with pytest.raises(ValueError):
            fs.read_bytes(bad)


def test_a_title_with_spaces_and_accents_is_a_valid_key(library):
    fs = library.for_owner("t1", "u1")
    doc = {"id": "d1", "title": "Budget plan (final) é 東京.pdf"}
    key = original_key("n1", doc)
    fs.put_bytes(key, b"x")
    assert fs.read_bytes(key) == b"x" and fs.exists(key)
    assert artifact_key("n1", "a1", "dir/launch plan.docx") == "artifacts/n1/a1/launch plan.docx"
    fs.put_bytes(artifact_key("n1", "a1", "launch plan.docx"), b"y")
    assert fs.read_bytes(artifact_key("n1", "a1", "launch plan.docx")) == b"y"


def test_object_files_belong_to_their_owner_and_only_folders_can_be_streamed():
    library = ObjectFiles(memory_storage())
    mine = library.for_owner("t1", "u1")
    mine.put_bytes("files/n1/d1/secret.txt", b"mine")
    for tenant, user in (("t1", "u2"), ("t2", "u1")):
        assert not library.for_owner(tenant, user).exists("files/n1/d1/secret.txt")
        assert library.for_owner(tenant, user).read_bytes("files/n1/d1/secret.txt") is None
    assert mine.local_path("files/n1/d1/secret.txt") is None  # an object is read, not streamed
    with pytest.raises(ValueError):
        library.for_owner("", "u1")


def test_a_folder_store_streams_its_own_file(tmp_path):
    fs = LocalFiles(tmp_path).for_owner("t", "u")
    fs.put_bytes("files/n/d/a.txt", b"x")
    assert fs.local_path("files/n/d/a.txt") == tmp_path / "files/n/d/a.txt"
    assert fs.local_path("files/n/d/none.txt") is None
