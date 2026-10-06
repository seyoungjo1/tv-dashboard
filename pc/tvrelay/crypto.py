"""암호화 — TV 앱(relay/RelayCrypto.kt)과 같은 형식.

  봉투 = b"TVR1" + nonce(12) + AES-256-GCM(평문) + tag(16)
  AAD  = "<tv>/<kind>/<id>/<name>"   (kind: job · res · state)
"""
from __future__ import annotations

import base64
import os
import sys

MAGIC = b"TVR1"


class CryptoError(Exception):
    pass


def new_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("=")


def decode_key(s: str) -> bytes:
    t = s.strip()
    pad = "=" * (-len(t) % 4)
    try:
        raw = base64.urlsafe_b64decode(t + pad)
    except Exception:
        raw = base64.b64decode(t + pad)
    if len(raw) != 32:
        raise CryptoError("암호키 길이가 올바르지 않습니다")
    return raw


def aad(tv: str, kind: str, id_: str, name: str) -> bytes:
    return ("%s/%s/%s/%s" % (tv, kind, id_, name)).encode("utf-8")


# ── AES-256-GCM 백엔드 ────────────────────────────────────────────────────────
# 1) Windows: 운영체제에 들어 있는 CNG(bcrypt.dll) — 설치할 것이 없다 (회사망·32비트·최신 Python 도 문제없음)
# 2) 그 밖(Linux·macOS·시험 환경): cryptography 라이브러리
# 어느 쪽이든 처음 한 번 알려진 정답(KAT)과 맞는지 스스로 확인한 뒤에만 쓴다.

_KAT_KEY = bytes(range(32))
_KAT_NONCE = bytes(range(12))
_KAT_PLAIN = b"tvrelay-selftest-0123456789"
_KAT_AAD = b"kat"
_KAT_OUT = bytes.fromhex("3374a47ea984bb36fe24fbedc58c0b19aee6b606c34f6a4a0f5fdc1eef15b676eafca1a6c681f0d33413a5")


class _Cng:
    """Windows CNG AES-GCM (ctypes). 출력 = 암호문 + tag(16)."""
    STATUS_AUTH_TAG_MISMATCH = 0xC000A002

    def __init__(self, key: bytes):
        import ctypes
        from ctypes import wintypes
        self.ct = ctypes
        bc = ctypes.WinDLL("bcrypt")
        for name in ("BCryptOpenAlgorithmProvider", "BCryptSetProperty", "BCryptGenerateSymmetricKey",
                     "BCryptEncrypt", "BCryptDecrypt", "BCryptDestroyKey", "BCryptCloseAlgorithmProvider"):
            getattr(bc, name).restype = ctypes.c_long
        self.bc = bc

        class Info(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.ULONG), ("dwInfoVersion", wintypes.ULONG),
                        ("pbNonce", ctypes.c_void_p), ("cbNonce", wintypes.ULONG),
                        ("pbAuthData", ctypes.c_void_p), ("cbAuthData", wintypes.ULONG),
                        ("pbTag", ctypes.c_void_p), ("cbTag", wintypes.ULONG),
                        ("pbMacContext", ctypes.c_void_p), ("cbMacContext", wintypes.ULONG),
                        ("cbAAD", wintypes.ULONG), ("cbData", ctypes.c_ulonglong), ("dwFlags", wintypes.ULONG)]
        self.Info = Info
        self.alg = ctypes.c_void_p()
        self._ok(bc.BCryptOpenAlgorithmProvider(ctypes.byref(self.alg), ctypes.c_wchar_p("AES"), None, 0), "OpenAlgorithmProvider")
        mode = ctypes.create_unicode_buffer("ChainingModeGCM")
        self._ok(bc.BCryptSetProperty(self.alg, ctypes.c_wchar_p("ChainingMode"), mode, ctypes.sizeof(mode), 0), "SetProperty")
        self._keybuf = ctypes.create_string_buffer(key, len(key))
        self.key = ctypes.c_void_p()
        self._ok(bc.BCryptGenerateSymmetricKey(self.alg, ctypes.byref(self.key), None, 0, self._keybuf, len(key), 0), "GenerateSymmetricKey")

    def _ok(self, st: int, what: str) -> None:
        if st != 0:
            raise CryptoError("Windows 암호화(CNG) %s 실패: 0x%08X" % (what, st & 0xFFFFFFFF))

    def _info(self, nonce, aad_, tag):
        ct = self.ct
        info = self.Info()
        info.cbSize = ct.sizeof(self.Info)
        info.dwInfoVersion = 1
        info.pbNonce = ct.cast(nonce, ct.c_void_p)
        info.cbNonce = 12
        info.pbAuthData = ct.cast(aad_, ct.c_void_p) if len(aad_.raw) else None
        info.cbAuthData = len(aad_.raw)
        info.pbTag = ct.cast(tag, ct.c_void_p)
        info.cbTag = 16
        return info

    def encrypt(self, nonce: bytes, plain: bytes, aad_: bytes) -> bytes:
        ct = self.ct
        nb, ab, tag = ct.create_string_buffer(nonce, 12), ct.create_string_buffer(aad_, len(aad_)), ct.create_string_buffer(16)
        info = self._info(nb, ab, tag)
        inp = ct.create_string_buffer(plain, len(plain))
        out = ct.create_string_buffer(max(len(plain), 1))
        n = ct.c_ulong()
        self._ok(self.bc.BCryptEncrypt(self.key, inp, len(plain), ct.byref(info), None, 0, out, len(plain), ct.byref(n), 0), "Encrypt")
        return out.raw[:n.value] + tag.raw

    def decrypt(self, nonce: bytes, data: bytes, aad_: bytes) -> bytes:
        ct = self.ct
        if len(data) < 16:
            raise CryptoError("암호문이 너무 짧습니다")
        body, tagv = data[:-16], data[-16:]
        nb, ab, tag = ct.create_string_buffer(nonce, 12), ct.create_string_buffer(aad_, len(aad_)), ct.create_string_buffer(tagv, 16)
        info = self._info(nb, ab, tag)
        inp = ct.create_string_buffer(body, len(body))
        out = ct.create_string_buffer(max(len(body), 1))
        n = ct.c_ulong()
        st = self.bc.BCryptDecrypt(self.key, inp, len(body), ct.byref(info), None, 0, out, len(body), ct.byref(n), 0)
        if st != 0:
            raise CryptoError("복호화 실패 — PC 와 TV 의 암호키가 다릅니다")
        return out.raw[:n.value]


class _Lib:
    def __init__(self, key: bytes):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        self.g = AESGCM(key)

    def encrypt(self, nonce: bytes, plain: bytes, aad_: bytes) -> bytes:
        return self.g.encrypt(nonce, plain, aad_)

    def decrypt(self, nonce: bytes, data: bytes, aad_: bytes) -> bytes:
        try:
            return self.g.decrypt(nonce, data, aad_)
        except Exception:
            raise CryptoError("복호화 실패 — PC 와 TV 의 암호키가 다릅니다") from None


def _backend(key: bytes):
    errors = []
    kinds = [_Cng, _Lib] if sys.platform == "win32" else [_Lib]
    for kind in kinds:
        try:
            probe = kind(_KAT_KEY)
            if probe.encrypt(_KAT_NONCE, _KAT_PLAIN, _KAT_AAD) != _KAT_OUT or \
                    probe.decrypt(_KAT_NONCE, _KAT_OUT, _KAT_AAD) != _KAT_PLAIN:
                raise CryptoError("자체 검사(KAT) 결과가 다릅니다")
            return kind(key)
        except Exception as e:
            errors.append("%s: %s" % (kind.__name__, e))
    raise CryptoError("이 PC 에서 AES-GCM 암호화를 쓸 수 없습니다 (%s)" % "; ".join(errors))


class Box:
    def __init__(self, key_b64: str):
        self._gcm = _backend(decode_key(key_b64))

    def seal(self, plain: bytes, aad_: bytes) -> bytes:
        nonce = os.urandom(12)
        return MAGIC + nonce + self._gcm.encrypt(nonce, plain, aad_)

    def open(self, sealed: bytes, aad_: bytes) -> bytes:
        if len(sealed) < 32 or sealed[:4] != MAGIC:
            raise CryptoError("암호화 형식이 아닙니다")
        return self._gcm.decrypt(sealed[4:16], sealed[16:], aad_)
