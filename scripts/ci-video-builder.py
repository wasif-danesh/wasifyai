"""Install the Video Builder component the way the app does (the pinned downloads, every hash
checked) into the folder given as the first argument, and print the folder the tests should use.

    uv run python scripts/ci-video-builder.py "$RUNNER_TEMP/video-builder-data"

CI runs the hostile-composition tests against it (test_video_builder_hostile.py)."""

import asyncio
import sys
from pathlib import Path

from wasifyai_api.video_builder_runtime import VideoBuilderInstaller, component_root, find_install


async def main(data_dir: Path) -> int:
    installer = VideoBuilderInstaller(data_dir)
    if not installer.supported:
        print("This computer is not one Video Builder was measured on.", file=sys.stderr)
        return 2
    installer.start(installer.total_bytes)
    assert installer._task is not None  # noqa: SLF001
    await installer._task  # noqa: SLF001
    if installer.progress.state != "ready" or find_install(data_dir) is None:
        print(f"Video Builder did not install: {installer.progress.message}", file=sys.stderr)
        return 1
    print(component_root(data_dir))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(Path(sys.argv[1]))))
