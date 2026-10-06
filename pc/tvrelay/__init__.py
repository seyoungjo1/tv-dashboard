"""tvrelay — 다른 망에 있는 PC 에서 TV 대시보드(APK)를 관리하는 프로그램.

GitHub 공개 레포를 '우체통'으로만 쓴다. 모든 내용은 PC 와 TV 가 함께 가진 키로 암호화(AES-256-GCM)되어
잠깐 지나가고, TV 가 받아 가면 바로 지워진다. 자료는 TV 에만 저장된다.
"""
from pathlib import Path

try:
    __version__ = (Path(__file__).resolve().parent / "VERSION").read_text(encoding="utf-8-sig").strip()
except OSError:
    __version__ = "0"
