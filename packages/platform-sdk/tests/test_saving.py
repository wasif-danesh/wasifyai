"""Saving at a path the person chose: only a file, where a folder exists, never in app data."""

import pytest
from wasifyai_platform_sdk import SaveRefused, copy_to_path, write_to_path
from wasifyai_platform_sdk.saving import chosen_path


def test_a_file_is_written_where_the_person_chose_and_replaces_one_there(tmp_path):
    target = tmp_path / "plan.docx"
    assert write_to_path(str(target), b"one") == target and target.read_bytes() == b"one"
    write_to_path(str(target), b"two")  # the Save As box asked about replacing
    assert target.read_bytes() == b"two"
    assert [p.name for p in tmp_path.iterdir()] == ["plan.docx"]  # no half-written file left


def test_a_file_of_the_app_is_copied_to_the_chosen_path(tmp_path):
    source = tmp_path / "model.glb"
    source.write_bytes(b"glb")
    target = tmp_path / "out" / "mine.glb"
    target.parent.mkdir()
    assert copy_to_path(str(target), source) == target and target.read_bytes() == b"glb"


@pytest.mark.parametrize("path", ["", "relative/name.txt", "name.txt", "bad\x00name"])
def test_a_path_that_is_not_a_full_file_path_is_refused(tmp_path, path):
    with pytest.raises(SaveRefused):
        chosen_path(path)


def test_a_folder_a_missing_folder_and_the_apps_own_data_are_refused(tmp_path):
    with pytest.raises(SaveRefused, match="folder"):
        write_to_path(str(tmp_path), b"x")
    with pytest.raises(SaveRefused, match="does not exist"):
        write_to_path(str(tmp_path / "nope" / "a.txt"), b"x")
    data = tmp_path / "app-data"
    (data / "notebooks").mkdir(parents=True)
    with pytest.raises(SaveRefused, match="belongs to the app"):
        write_to_path(str(data / "secrets.key"), b"x", protect=data)
    with pytest.raises(SaveRefused, match="belongs to the app"):
        write_to_path(str(data / "notebooks" / "a.txt"), b"x", protect=data)
    assert not list(data.rglob("*.txt")) and not (data / "secrets.key").exists()
    assert write_to_path(str(tmp_path / "ok.txt"), b"x", protect=data).read_bytes() == b"x"


def test_a_failed_write_leaves_nothing_behind(tmp_path):
    target = tmp_path / "locked"
    target.mkdir()  # a folder is in the way after the check: the replace fails
    (tmp_path / "x").write_text("keep")
    with pytest.raises(SaveRefused):
        write_to_path(str(target / ".."), b"x")
    assert (tmp_path / "x").read_text() == "keep"
