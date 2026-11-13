"""The web's API image installs the API and the products, not the media worker
(`services/api/Containerfile`; it is in the API's `desktop` extra, for the desktop's engine). The
app must load without it, or the API pod never starts (CI's helm-kind job, 2026-10-29: the
own-keys code imported it). A desktop module may use it only inside the functions the desktop
runs. (The trainers come in through the products' entry points, which an image without them
simply does not have.)"""

import subprocess
import sys
import textwrap

DESKTOP_ONLY = ("wasifyai_media_worker",)


def test_the_api_loads_without_the_media_worker():
    code = textwrap.dedent(f"""
        import importlib.abc, sys

        class Missing(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path=None, target=None):
                if name.split(".")[0] in {DESKTOP_ONLY!r}:
                    raise ModuleNotFoundError(f"No module named {{name!r}}")
                return None

        sys.meta_path.insert(0, Missing())
        import wasifyai_api.main  # noqa: F401
        import wasifyai_api.assemble  # noqa: F401
        print("loaded")
    """)
    run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0 and "loaded" in run.stdout, run.stderr[-2000:]
