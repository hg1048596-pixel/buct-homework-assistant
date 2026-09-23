# -*- coding: utf-8 -*-
"""Windows DPAPI（用户作用域）加解密，零第三方依赖。

绑定当前 Windows 用户：换用户/换机器无法解密。
"""
import ctypes
import ctypes.wintypes as wt


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _to_blob(data: bytes) -> _DATA_BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _from_blob(blob: _DATA_BLOB) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob.pbData)


def protect(data: bytes, description: str = "buct-assistant") -> bytes:
    inp = _to_blob(data)
    out = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(inp), description, None, None, None, 0, ctypes.byref(out))
    if not ok:
        raise ctypes.WinError()
    return _from_blob(out)


def unprotect(data: bytes) -> bytes:
    inp = _to_blob(data)
    out = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out))
    if not ok:
        raise ctypes.WinError()
    return _from_blob(out)
