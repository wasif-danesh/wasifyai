"""The Windows Credential Manager through `advapi32`, with ctypes and nothing else.

One generic credential per secret, target `<service>/<name>`, the value as UTF-8 bytes in the
credential blob (the Credential Manager caps a blob at 2,560 bytes). Used by
`KeychainSecretStore` only; importable on Windows alone."""

import ctypes
import sys
from collections.abc import Callable
from ctypes import POINTER, Structure, byref, c_void_p, c_wchar_p
from ctypes import wintypes as wt
from typing import Any

from wasifyai_platform_sdk.secretbox import SecretsUnavailable

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2  # kept for this user on this computer, across sign-ins
ERROR_NOT_FOUND = 1168
ERROR_NO_SUCH_LOGON_SESSION = 1312
MAX_BLOB = 5 * 512
_REASONS = {
    5: "access to the Credential Manager was denied",
    1312: "there is no sign-in session to keep it in",
    1783: "the Credential Manager rejected the request",
}


class _Credential(Structure):
    _fields_ = [
        ("Flags", wt.DWORD),
        ("Type", wt.DWORD),
        ("TargetName", c_wchar_p),
        ("Comment", c_wchar_p),
        ("LastWritten", wt.FILETIME),
        ("CredentialBlobSize", wt.DWORD),
        ("CredentialBlob", POINTER(ctypes.c_byte)),
        ("Persist", wt.DWORD),
        ("AttributeCount", wt.DWORD),
        ("Attributes", c_void_p),
        ("TargetAlias", c_wchar_p),
        ("UserName", c_wchar_p),
    ]


# `ctypes.get_last_error` exists on Windows only; elsewhere this module is never used
_last_error: Callable[[], int] = getattr(ctypes, "get_last_error", lambda: 0)


class _Api:
    adv: Any

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise SecretsUnavailable("the Credential Manager is only on Windows")
        self.adv = ctypes.WinDLL("advapi32", use_last_error=True)  # type: ignore[attr-defined]
        self.adv.CredWriteW.restype = wt.BOOL
        self.adv.CredWriteW.argtypes = (POINTER(_Credential), wt.DWORD)
        self.adv.CredReadW.restype = wt.BOOL
        self.adv.CredReadW.argtypes = (
            c_wchar_p, wt.DWORD, wt.DWORD, POINTER(POINTER(_Credential)),
        )  # fmt: skip
        self.adv.CredDeleteW.restype = wt.BOOL
        self.adv.CredDeleteW.argtypes = (c_wchar_p, wt.DWORD, wt.DWORD)
        self.adv.CredFree.restype = None
        self.adv.CredFree.argtypes = (c_void_p,)


def _refused(code: int, what: str) -> SecretsUnavailable:
    reason = _REASONS.get(code, f"the Credential Manager answered {code}")
    return SecretsUnavailable(f"could not {what} in the Credential Manager: {reason}")


class Keychain:
    def __init__(self, service: str):
        self._service = service
        self._api = _Api()

    def _target(self, name: str) -> str:
        return f"{self._service}/{name}"

    def get(self, name: str) -> str | None:
        out = POINTER(_Credential)()
        ok = self._api.adv.CredReadW(self._target(name), CRED_TYPE_GENERIC, 0, byref(out))
        if not ok:
            code = _last_error()
            if code == ERROR_NOT_FOUND:
                return None
            raise _refused(code, "read a secret")
        try:
            cred = out.contents
            raw = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
            return raw.decode("utf-8")
        finally:
            self._api.adv.CredFree(out)

    def set(self, name: str, value: str) -> None:
        blob = value.encode("utf-8")
        if len(blob) > MAX_BLOB:
            raise SecretsUnavailable(
                f"a secret of {len(blob)} bytes is too long for the Credential Manager "
                f"(at most {MAX_BLOB})"
            )
        buffer = (ctypes.c_byte * len(blob)).from_buffer_copy(blob)
        cred = _Credential()
        cred.Type = CRED_TYPE_GENERIC
        cred.TargetName = self._target(name)
        cred.Comment = "Wasify AI secret"
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = ctypes.cast(buffer, POINTER(ctypes.c_byte))
        cred.Persist = CRED_PERSIST_LOCAL_MACHINE
        cred.UserName = name
        if not self._api.adv.CredWriteW(byref(cred), 0):
            raise _refused(_last_error(), "keep a secret")

    def delete(self, name: str) -> None:
        if not self._api.adv.CredDeleteW(self._target(name), CRED_TYPE_GENERIC, 0):
            code = _last_error()
            if code != ERROR_NOT_FOUND:
                raise _refused(code, "remove a secret")
