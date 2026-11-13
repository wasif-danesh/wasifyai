# ruff: noqa: E501  (prose in the docstring reads better on long lines)
"""Sets up AI Toolkit's environment with AI Toolkit's own manager (ADR-0073, amendment 2026-11-07).

Run by the picture trainer's setup as `python -I training_aitk_install.py <the AI Toolkit folder>`, with the
engine's own Python: the manager needs only the standard library. The manager knows what each computer needs
(PyTorch for the graphics chip of a Mac with Apple silicon, or the CUDA build that matches an NVIDIA card on
Windows and Linux, and FFmpeg), so the same steps work everywhere. Its web UI (Node.js and its packages) is
not set up: the app drives the trainer itself.

The last line is `AITK-SETUP-OK <backend>` when it worked; anything else, and a non-zero exit, when it did
not. Nothing here is imported by the engine."""

import sys


def main(root: str) -> int:
    sys.path.insert(0, root)
    import os

    os.chdir(root)
    from manager import detect, env, ffmpeg, gitwin, spec, uvbin  # type: ignore[import-not-found]

    detection = detect.detect()
    try:
        s = spec.build_spec(detection, allow_cpu=False)
    except RuntimeError as e:
        print(f"AITK-SETUP-UNSUPPORTED {e}", flush=True)
        return 3
    for note in s.notes:
        print(note, flush=True)
    uvbin.ensure_uv()
    gitwin.ensure_git()
    if s.backend == "cu134":  # Windows on Arm with a native CUDA driver
        from manager import sparkdeps  # type: ignore[import-not-found]

        sparkdeps.ensure_spark_runtime()
    env.ensure_venv(s)
    env.write_sitecustomize(spec=s)  # before torch is imported to check it
    changed = env.ensure_torch(s)
    env.ensure_requirements(s, force=changed)
    ffmpeg.ensure_ffmpeg(detection, spec=s)
    env.write_sitecustomize(spec=s)
    print(f"AITK-SETUP-OK {s.backend}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
