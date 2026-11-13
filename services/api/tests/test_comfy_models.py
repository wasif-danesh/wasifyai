"""Fetching an image or video model onto a ComfyUI host (ADR-0097, MV6): the listing and the checks
before anything is fetched. The download itself is the desktop's, tested in test_desktop_models."""

from wasifyai_api.comfy_models import run


async def test_it_lists_each_model_and_what_is_missing(tmp_path):
    lines: list[str] = []
    assert await run([str(tmp_path), "wasifyai-video"], out=lambda *a, **k: lines.append(a[0])) == 0
    ids = [line.split()[0] for line in lines]
    assert ids == ["ltx-video-2b", "wan2.2-14b", "minimax-h3", "ltx-2.5"]
    assert all("missing" in line for line in lines)


async def test_an_unknown_model_is_refused_before_anything_is_fetched(tmp_path):
    lines: list[str] = []
    code = await run(
        [str(tmp_path), "wasifyai-image", "nope"], out=lambda *a, **k: lines.append(a[0])
    )
    assert code == 2 and "nope" in lines[0]
    assert list(tmp_path.iterdir()) == []
    assert await run([], out=lambda *a, **k: lines.append(a[0])) == 2
