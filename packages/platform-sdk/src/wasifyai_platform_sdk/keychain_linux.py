"""The Secret Service (GNOME Keyring, KDE Wallet through its bridge) on Linux, through
libsecret's `secret-tool`, which takes the value on stdin and answers it on stdout: nothing on
a command line, nothing in a file. Used by `KeychainSecretStore` only.

`available()` needs the tool on the PATH and a session bus (`DBUS_SESSION_BUS_ADDRESS` or
`$XDG_RUNTIME_DIR/bus`); a headless machine or a container has neither and keeps the encrypted
file."""

import os
import shutil
import subprocess
from pathlib import Path

from wasifyai_platform_sdk.secretbox import SecretsUnavailable

TOOL = "secret-tool"
TIMEOUT_S = 15  # the first use may show the keyring's unlock prompt


def available() -> bool:
    if shutil.which(TOOL) is None:
        return False
    if os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        return True
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    return bool(runtime) and (Path(runtime) / "bus").exists()


class Keychain:
    def __init__(self, service: str):
        self._service = service
        self._tool = shutil.which(TOOL)
        if self._tool is None:
            raise SecretsUnavailable("secret-tool (libsecret) is not installed")

    def _run(self, args: list[str], stdin: bytes | None, what: str) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                [self._tool or TOOL, *args],
                input=stdin,
                capture_output=True,
                timeout=TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SecretsUnavailable(
                f"could not {what} in the keyring: {type(exc).__name__}"
            ) from exc

    def _attrs(self, name: str) -> list[str]:
        return ["service", self._service, "account", name]

    def get(self, name: str) -> str | None:
        done = self._run(["lookup", *self._attrs(name)], None, "read a secret")
        if done.returncode != 0:
            if not done.stdout and not done.stderr.strip():
                return None  # not found: secret-tool answers 1 and says nothing
            raise SecretsUnavailable(
                "could not read a secret in the keyring: "
                + (done.stderr.decode(errors="replace").strip() or f"exit {done.returncode}")
            )
        return done.stdout.decode("utf-8").rstrip("\n")

    def set(self, name: str, value: str) -> None:
        label = f"{self._service}: {name}"
        done = self._run(
            ["store", f"--label={label}", *self._attrs(name)], value.encode("utf-8"), "keep"
        )
        if done.returncode != 0:
            raise SecretsUnavailable(
                "could not keep a secret in the keyring: "
                + (done.stderr.decode(errors="replace").strip() or f"exit {done.returncode}")
            )

    def delete(self, name: str) -> None:
        done = self._run(["clear", *self._attrs(name)], None, "remove a secret")
        if done.returncode != 0 and done.stderr.strip():
            raise SecretsUnavailable(
                "could not remove a secret in the keyring: "
                + done.stderr.decode(errors="replace").strip()
            )
