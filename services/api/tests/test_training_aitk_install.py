"""The picture trainer's install script: the constraints file gets a path with no space in it."""

from pathlib import Path
from types import SimpleNamespace

from wasifyai_api import training_aitk_install as install


def test_the_constraints_file_is_given_as_a_path_from_the_ai_toolkit_folder(tmp_path: Path):
    # the app's data folder on a Mac is ".../Application Support/...": uv cuts the value at a space
    root = tmp_path / "Application Support" / "ai-toolkit"
    full = root / ".venv" / "aitk_torch_constraints.txt"
    env = SimpleNamespace(
        _torch_pin_args=lambda spec, dry_run=False: [
            "--constraint",
            str(full),
            "--find-links",
            "https://example.test/wheels",
        ]
    )

    install._short_constraint_path(env, str(root))
    args = env._torch_pin_args(None, dry_run=True)

    assert args == [
        "--constraint",
        str(Path(".venv") / "aitk_torch_constraints.txt"),
        "--find-links",
        "https://example.test/wheels",
    ]
    assert " " not in args[1]
    assert (root / args[1]) == full
