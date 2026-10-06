"""암호화 — TV 앱(relay/RelayCrypto.kt)과 같은 형식.

  봉투 = b"TVR1" + nonce(12) + AES-256-GCM(평문) + tag(16)
  AAD  = "<tv>/<kind>/<id>/<name>"   (kind: job · res · state)
"""
from __future__ import annotations

import base64
import os

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


class Box:
    def __init__(self, key_b64: str):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as e:  # pragma: no cover
            raise CryptoError("cryptography 라이브러리가 없습니다. tvrun.bat 을 다시 실행하세요.") from e
        self._gcm = AESGCM(decode_key(key_b64))

    def seal(self, plain: bytes, aad_: bytes) -> bytes:
        nonce = os.urandom(12)
        return MAGIC + nonce + self._gcm.encrypt(nonce, plain, aad_)

    def open(self, sealed: bytes, aad_: bytes) -> bytes:
        if len(sealed) < 32 or sealed[:4] != MAGIC:
            raise CryptoError("암호화 형식이 아닙니다")
        try:
            return self._gcm.decrypt(sealed[4:16], sealed[16:], aad_)
        except Exception:
            raise CryptoError("복호화 실패 — PC 와 TV 의 암호키가 다릅니다") from None
