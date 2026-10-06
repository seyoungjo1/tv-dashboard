"""HTTPS 설정 — 회사망의 SSL 검사 장비(자체 인증서)를 통과하도록 Windows 인증서 저장소를 쓴다 (s4bridge/sso.py 와 같은 방식)."""
from __future__ import annotations

import ssl

_CTX: list[ssl.SSLContext] = []


def ssl_context() -> ssl.SSLContext:
    if not _CTX:
        try:
            import truststore  # type: ignore
            _CTX.append(truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
        except Exception:
            _CTX.append(ssl.create_default_context())
    return _CTX[0]


def explain(e: BaseException) -> str:
    s = str(e)
    if "CERTIFICATE_VERIFY_FAILED" in s:
        return ("인증서 확인 실패 — 회사망의 보안 장비 때문일 수 있습니다. tvrun.bat 을 다시 실행해 truststore 가 설치되었는지 확인하세요. (%s)" % s)
    return s
