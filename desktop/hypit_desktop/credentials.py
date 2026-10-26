"""API keys live in the Windows Credential Manager, never in settings.json or a project folder.

The store talks to advapi32 directly (CredRead/CredWrite), so no extra package is needed and the PyInstaller build
stays small. A key typed in Settings wins; the old environment variables still work as a fallback so existing
setups keep running."""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Optional, Protocol

LLM_KEY = "llm-api-key"       # DeepSeek: the name older versions already used
ARK_KEY = "ark-api-key"
_LEGACY_NAMES = {"deepseek": LLM_KEY, "ark": ARK_KEY}
TARGET_PREFIX = "HypitDesktop/"
PLACEHOLDER_KEY = "placeholder-not-a-real-key"   # what the AI director's own shell sees instead of a real key


class KeyStore(Protocol):
    def get(self, name: str) -> str: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...


class MemoryStore:
    """For tests and non-Windows machines."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def get(self, name: str) -> str:
        return self._values.get(name, "")

    def set(self, name: str, value: str) -> None:
        self._values[name] = value

    def delete(self, name: str) -> None:
        self._values.pop(name, None)


class _Credential(ctypes.Structure):
    _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]


CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168


class WindowsCredentialStore:
    def __init__(self) -> None:
        self._advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        self._advapi.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                           ctypes.POINTER(ctypes.POINTER(_Credential))]
        self._advapi.CredReadW.restype = wintypes.BOOL
        self._advapi.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
        self._advapi.CredWriteW.restype = wintypes.BOOL
        self._advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self._advapi.CredDeleteW.restype = wintypes.BOOL
        self._advapi.CredFree.argtypes = [ctypes.c_void_p]

    def get(self, name: str) -> str:
        pointer = ctypes.POINTER(_Credential)()
        if not self._advapi.CredReadW(TARGET_PREFIX + name, CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
            return ""
        try:
            credential = pointer.contents
            raw = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
            return raw.decode("utf-16-le")
        finally:
            self._advapi.CredFree(pointer)

    def set(self, name: str, value: str) -> None:
        blob = value.encode("utf-16-le")
        buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        credential = _Credential()
        credential.Type = CRED_TYPE_GENERIC
        credential.TargetName = TARGET_PREFIX + name
        credential.CredentialBlobSize = len(blob)
        credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        credential.Persist = CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = name
        if not self._advapi.CredWriteW(ctypes.byref(credential), 0):
            raise OSError(f"无法保存到 Windows 凭据管理器(错误 {ctypes.get_last_error()})")

    def delete(self, name: str) -> None:
        if not self._advapi.CredDeleteW(TARGET_PREFIX + name, CRED_TYPE_GENERIC, 0):
            if ctypes.get_last_error() != ERROR_NOT_FOUND:
                raise OSError(f"无法从 Windows 凭据管理器删除(错误 {ctypes.get_last_error()})")


def key_name(provider_id: str) -> str:
    """Credential Manager entry for a provider. One key per provider, whether it serves as director or generator."""
    return _LEGACY_NAMES.get(provider_id, f"key-{provider_id}")


def default_store() -> KeyStore:
    return WindowsCredentialStore() if os.name == "nt" else MemoryStore()


def stored_or_env(store: Optional[KeyStore], name: str, env_var: str) -> str:
    """The key typed in Settings, else the environment variable (older setups), else empty."""
    value = ""
    if store is not None:
        try:
            value = store.get(name)
        except OSError:
            value = ""
    return value or (os.environ.get(env_var, "") if env_var else "")
