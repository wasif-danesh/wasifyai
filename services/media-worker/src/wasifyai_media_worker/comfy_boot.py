"""Start ComfyUI's `main.py` so that it ends when the engine that started it ends.

Run by the sidecar as `<ComfyUI's python> -P comfy_boot.py <engine pid> <ComfyUI's arguments>`
in ComfyUI's folder. It runs in ComfyUI's own environment, so it uses the standard library only
(-P: this folder holds the engine's modules, such as `comfy.py`, which must not shadow ComfyUI's
own `comfy` package).

Why: the engine stops ComfyUI when it closes, but an engine that is killed (a crash, a forced
quit, `kill -9`) cannot, and ComfyUI was left running with its models in memory. A thread here
looks at the parent every second; when the engine is gone the process is handed to the system
(the parent id changes) and ComfyUI exits at once.
"""

import os
import runpy
import sys
import threading
import time


def watch(engine: int, every: float = 1.0) -> None:
    while True:
        time.sleep(every)
        if os.getppid() != engine:
            os._exit(0)  # nothing of ComfyUI's state is worth keeping once its engine is gone


def main() -> None:
    engine = int(sys.argv[1])
    if os.getppid() != engine:  # already orphaned before this line ran
        os._exit(0)
    threading.Thread(target=watch, args=(engine,), daemon=True, name="engine-watch").start()
    sys.argv = ["main.py", *sys.argv[2:]]
    sys.path.insert(0, os.getcwd())  # ComfyUI's folder, as `python main.py` would have it
    runpy.run_path("main.py", run_name="__main__")


if __name__ == "__main__":
    main()
