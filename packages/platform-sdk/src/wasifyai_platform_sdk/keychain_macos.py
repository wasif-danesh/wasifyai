"""The macOS keychain through the Security framework, with ctypes and nothing else.

One generic password per secret: service = the app, account = the secret's name. Values travel
as CFData inside this process; no command line, no file. Used by `KeychainSecretStore` only."""

import ctypes
import ctypes.util
import sys
from ctypes import POINTER, byref, c_char_p, c_int32, c_long, c_uint32, c_void_p

from wasifyai_platform_sdk.secretbox import SecretsUnavailable

ERR_NOT_FOUND = -25300
ERR_DUPLICATE = -25299
_REASONS = {
    -128: "you cancelled the keychain prompt",
    -25293: "the keychain refused the password",
    -25308: "the keychain is locked and cannot ask you to unlock it",
    -25291: "the keychain is not available",
    -34018: "this app is not allowed to use the keychain",
}
_UTF8 = 0x08000100


class _Api:
    # declared here so a type checker on Linux or Windows, which treats the platform check below
    # as always failing, still knows the attributes exist
    sec: ctypes.CDLL
    cf: ctypes.CDLL
    key_callbacks: c_void_p
    value_callbacks: c_void_p
    true: c_void_p

    def __init__(self) -> None:
        if sys.platform != "darwin":
            raise SecretsUnavailable("the keychain is only on macOS")
        sec = ctypes.util.find_library("Security")
        cf = ctypes.util.find_library("CoreFoundation")
        if not sec or not cf:
            raise SecretsUnavailable("the Security framework was not found")
        self.sec = ctypes.CDLL(sec)
        self.cf = ctypes.CDLL(cf)
        self.cf.CFStringCreateWithCString.restype = c_void_p
        self.cf.CFStringCreateWithCString.argtypes = (c_void_p, c_char_p, c_uint32)
        self.cf.CFDataCreate.restype = c_void_p
        self.cf.CFDataCreate.argtypes = (c_void_p, c_char_p, c_long)
        self.cf.CFDataGetLength.restype = c_long
        self.cf.CFDataGetLength.argtypes = (c_void_p,)
        self.cf.CFDataGetBytePtr.restype = c_void_p
        self.cf.CFDataGetBytePtr.argtypes = (c_void_p,)
        self.cf.CFDictionaryCreate.restype = c_void_p
        self.cf.CFDictionaryCreate.argtypes = (
            c_void_p, c_void_p, c_void_p, c_long, c_void_p, c_void_p,
        )  # fmt: skip
        self.cf.CFRelease.restype = None
        self.cf.CFRelease.argtypes = (c_void_p,)
        self.sec.SecItemAdd.restype = c_int32
        self.sec.SecItemAdd.argtypes = (c_void_p, POINTER(c_void_p))
        self.sec.SecItemCopyMatching.restype = c_int32
        self.sec.SecItemCopyMatching.argtypes = (c_void_p, POINTER(c_void_p))
        self.sec.SecItemDelete.restype = c_int32
        self.sec.SecItemDelete.argtypes = (c_void_p,)
        self.key_callbacks = c_void_p.in_dll(self.cf, "kCFTypeDictionaryKeyCallBacks")
        self.value_callbacks = c_void_p.in_dll(self.cf, "kCFTypeDictionaryValueCallBacks")
        self.true = c_void_p.in_dll(self.cf, "kCFBooleanTrue")

    def k(self, name: str) -> c_void_p:
        return c_void_p.in_dll(self.sec, name)

    def string(self, value: str) -> c_void_p:
        return c_void_p(self.cf.CFStringCreateWithCString(None, value.encode(), _UTF8))

    def data(self, value: bytes) -> c_void_p:
        return c_void_p(self.cf.CFDataCreate(None, value, len(value)))

    def dictionary(self, items: list[tuple[c_void_p, c_void_p]]) -> c_void_p:
        n = len(items)
        keys = (c_void_p * n)(*[k for k, _ in items])
        values = (c_void_p * n)(*[v for _, v in items])
        return c_void_p(
            self.cf.CFDictionaryCreate(
                None, keys, values, n, byref(self.key_callbacks), byref(self.value_callbacks)
            )
        )

    def release(self, *refs: c_void_p) -> None:
        for ref in refs:
            if ref and ref.value:
                self.cf.CFRelease(ref)


def _refused(status: int, what: str) -> SecretsUnavailable:
    reason = _REASONS.get(status, f"the keychain answered {status}")
    return SecretsUnavailable(f"could not {what} in the keychain: {reason}")


class Keychain:
    def __init__(self, service: str):
        self._service = service
        self._api = _Api()

    def _query(self, name: str, *extra: tuple[c_void_p, c_void_p]) -> tuple[c_void_p, list]:
        api = self._api
        owned = [api.string(self._service), api.string(name)]
        items = [
            (api.k("kSecClass"), api.k("kSecClassGenericPassword")),
            (api.k("kSecAttrService"), owned[0]),
            (api.k("kSecAttrAccount"), owned[1]),
            *extra,
        ]
        return api.dictionary(items), owned

    def get(self, name: str) -> str | None:
        api = self._api
        query, owned = self._query(
            name,
            (api.k("kSecReturnData"), api.true),
            (api.k("kSecMatchLimit"), api.k("kSecMatchLimitOne")),
        )
        out = c_void_p()
        try:
            status = api.sec.SecItemCopyMatching(query, byref(out))
            if status == ERR_NOT_FOUND:
                return None
            if status != 0:
                raise _refused(status, "read a secret")
            length = api.cf.CFDataGetLength(out)
            raw = ctypes.string_at(api.cf.CFDataGetBytePtr(out), length)
            return raw.decode("utf-8")
        finally:
            api.release(out, query, *owned)

    def set(self, name: str, value: str) -> None:
        self.delete(name)
        api = self._api
        data = api.data(value.encode("utf-8"))
        attrs, owned = self._query(name, (api.k("kSecValueData"), data))
        try:
            status = api.sec.SecItemAdd(attrs, None)
            if status != 0:
                raise _refused(status, "keep a secret")
        finally:
            api.release(attrs, data, *owned)

    def delete(self, name: str) -> None:
        api = self._api
        query, owned = self._query(name)
        try:
            status = api.sec.SecItemDelete(query)
            if status not in (0, ERR_NOT_FOUND):
                raise _refused(status, "remove a secret")
        finally:
            api.release(query, *owned)
