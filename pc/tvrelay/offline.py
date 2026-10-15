"""HTML 을 인터넷 없이 TV 에서 뜨게 바꾸기 (올릴 때 변환).

다른 분이 만든 대시보드 HTML 은 흔히 CDN 의 스크립트 · CSS · 글꼴을 쓰고, 큰 그림을 base64 글자로 안에 박아 둔다.
TV 는 인터넷이 느리거나 끊기면 그런 페이지가 안 뜨거나 몇 초씩 멈춘다. 그래서 올릴 때:
  1) <script src="https://…">, <link rel=stylesheet href="https://…">, <img src="https://…"> 등 바깥 자료를 PC 가 내려받아
     HTML 옆의 묶음 폴더('_<이름>_files/')에 넣고, HTML 은 그 폴더를 가리키게 고친다
  2) CSS 안의 @import · url(글꼴 · 그림)도 따라가며 내려받는다 (@font-face 는 woff2 하나만 남겨 크기를 줄임)
  3) (토글) 큰 base64 그림(data:image/…)은 파일로 빼낸다 — JSON · JS 문자열 안에 있어도. 그림 자체는 손대지 않는다
     (shrink 를 켜고 Pillow 가 있을 때만 1920px 로 줄임 — 화면이 달라질 수 있어 기본은 끔)
묶음 폴더는 '_' 로 시작해 TV 메뉴에 보이지 않고, 같은 HTML 을 다시 올리면 지우고 다시 만든다.
원칙: 보이는 결과는 원본과 같아야 한다 — 같은 라이브러리를 같은 판으로 TV 옆에 두고 경로만 바꾸며, 코드는 고치지 않는다.
인터넷 없이 한 번만 쓸 수 있게 받는 것이지 페이지를 빠르게 고쳐 주지는 않는다 — Babel · Tailwind CDN 처럼 TV 에서
매번 코드를 만드는 라이브러리는 그대로 느리다 (보고서에 적어 준다).
"""
from __future__ import annotations

import base64
import hashlib
import io
import posixpath
import re
import urllib.request
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urljoin, urlsplit

from .net import ssl_context

FETCH_TIMEOUT = 25
MAX_ASSET = 60 * 1024 * 1024
MIN_SPLIT_IMAGE = 48 * 1024            # 이보다 큰 base64 그림만 파일로 뺀다
IMAGE_MAX_PX = 1920                    # Pillow 가 있을 때 긴 변을 이만큼으로
LOCAL = "https://localhost/"             # <style> 블록(페이지 자체)의 기준 — 여기서는 절대 주소(http…)만 내려받는다
FONT_KEEP = ("woff2", "woff", "truetype", "opentype")   # @font-face src 에서 앞의 것 하나만 남긴다
SLOW_LIBS = (("cdn.tailwindcss.com", "Tailwind CDN(개발용) — TV 에서 매번 CSS 를 만들어 느립니다. 만든 분께 Tailwind 를 CSS 파일로 빌드해 달라고 하세요"),
             ("@babel/standalone", "Babel standalone — TV 에서 매번 코드를 번역해 느립니다. 만든 분께 JSX 를 미리 변환해 달라고 하세요"))


@dataclass
class Result:
    html: bytes                                     # 고친 HTML
    folder: str                                     # 묶음 폴더 이름 (HTML 과 같은 자리, 예: _index_files)
    files: dict[str, bytes] = field(default_factory=dict)   # 묶음 폴더 안 상대 경로 → 내용
    report: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    by_url: dict[str, str] = field(default_factory=dict)   # 원본 URL → 묶음 안 경로 (UI 최적화에서 사용)


def bundle_folder(html_name: str) -> str:
    stem = re.sub(r"\.[^.]+$", "", html_name.rsplit("/", 1)[-1]) or "page"
    return "_%s_files" % stem


def default_fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 tvrelay-offline"})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT, context=ssl_context()) as r:
        data = r.read(MAX_ASSET + 1)
    if len(data) > MAX_ASSET:
        raise ValueError("너무 큽니다 (%d MB 초과)" % (MAX_ASSET // 1048576))
    return data


def _short(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:8]


def _safe_name(url: str, kind: str, data: bytes) -> str:
    """URL 에서 알아볼 수 있는 파일 이름 (같은 이름이 겹치지 않게 짧은 지문을 붙임)"""
    p = urlsplit(url)
    name = posixpath.basename(p.path) or p.netloc.replace(".", "_")
    name = re.sub(r'[\\/:*?"<>|\s]+', "_", name)[:80]
    if "." not in name:
        name += {"js": ".js", "css": ".css"}.get(kind, "")
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    return "%s-%s%s" % (stem or "file", _short(data), ("." + ext) if ext else "")


class Converter:
    def __init__(self, html_name: str, fetch: Callable[[str], bytes] | None = None, split_images: bool = True, fonts: bool = True, shrink: bool = False):
        self.folder = bundle_folder(html_name)
        self.fetch = fetch or default_fetch
        self.split_images = split_images
        self.fonts = fonts
        self.shrink = shrink
        self.files: dict[str, bytes] = {}
        self.by_url: dict[str, str] = {}           # 내려받은 URL → 묶음 안 경로 (같은 URL 은 한 번만)
        self.report: list[str] = []
        self.failed: list[str] = []
        self.sizes = 0

    # ── 내려받기 ──
    def _get(self, url: str, kind: str, sub: str) -> str | None:
        """url 을 내려받아 묶음 안 sub/ 에 넣고 그 상대 경로(묶음 기준)를 돌려준다. 실패하면 None"""
        url = url.strip()
        if url in self.by_url:
            return self.by_url[url] or None
        if not url.startswith(("http://", "https://")):
            return None
        try:
            data = self.fetch(url)
        except Exception as e:
            self.by_url[url] = ""                    # 같은 URL 은 다시 시도하지 않고 한 번만 보고
            self.failed.append("%s — %s" % (url, e))
            return None
        if kind == "css":
            data = self._css(data, url, sub).encode("utf-8")
        rel = "%s/%s" % (sub, _safe_name(url, kind, data))
        self.files[rel] = data
        self.by_url[url] = rel
        self.sizes += len(data)
        for host, why in SLOW_LIBS:
            if host in url:
                self.report.append("주의: " + why)
        return rel

    # ── CSS 안의 @import · url() ──
    def _css(self, data: bytes, base_url: str, sub: str) -> str:
        text = data.decode("utf-8", "replace")
        if self.fonts:
            text = re.sub(r"(src\s*:\s*)([^;}]+)", lambda m: m.group(1) + self._prune_font_src(m.group(2)), text)

        def imp(m: re.Match) -> str:
            if base_url == LOCAL and not re.match(r"(https?:)?//", m.group(2).strip()):
                return m.group(0)
            u = urljoin(base_url, m.group(2).strip())
            rel = self._get(u, "css", sub)
            return '@import url("\x00%s\x00")' % posixpath.basename(rel) if rel else m.group(0)   # \x00: 아래 url() 처리가 다시 받지 않게 표시
        text = re.sub(r"""@import\s+(?:url\()?\s*(['"]?)([^'")\s]+)\1\s*\)?""", imp, text)

        def url(m: re.Match) -> str:
            raw = m.group(2).strip()
            if raw.startswith(("data:", "#", "about:", "\x00")) or not raw:
                return m.group(0)
            if base_url == LOCAL and not re.match(r"(https?:)?//", raw):   # 페이지 자체의 상대 경로(이미 TV 에 있는 파일)는 그대로
                return m.group(0)
            u = urljoin(base_url, raw)
            if not u.startswith(("http://", "https://")):
                return m.group(0)
            if not self.fonts and re.search(r"\.(woff2?|ttf|otf|eot)(\?|#|$)", u, re.I):
                return m.group(0)
            rel = self._get(u, "asset", sub + "/res")
            return 'url("%s")' % ("res/" + posixpath.basename(rel)) if rel else m.group(0)
        return re.sub(r"""url\(\s*(['"]?)([^'")]+)\1\s*\)""", url, text).replace("\x00", "")

    @staticmethod
    def _prune_font_src(src: str) -> str:
        """@font-face src: url(a.woff2) format("woff2"), url(a.woff) … → 앞선 형식 하나만 (전부 내려받으면 글꼴이 수십 MB)"""
        parts, depth, cur = [], 0, ""
        for ch in src:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if ch == "," and depth == 0:
                parts.append(cur); cur = ""
            else:
                cur += ch
        parts.append(cur)
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) < 2:
            return src
        for want in FONT_KEEP:
            for p in parts:
                if re.search(r"format\(\s*['\"]?%s['\"]?\s*\)" % want, p, re.I) or re.search(r"\.%s[\"')]" % want.replace("truetype", "ttf").replace("opentype", "otf"), p, re.I):
                    return p
        return parts[0]

    # ── HTML ──
    def convert(self, html: bytes) -> Result:
        text = html.decode("utf-8", "replace").lstrip("﻿")
        F = self.folder

        def rewrite_attr(tag_re: str, attr: str, kind: str, sub: str) -> None:
            nonlocal text

            def repl(m: re.Match) -> str:
                before, q, u, after = m.group(1), m.group(2), m.group(3), m.group(4)
                if not u.startswith(("http://", "https://", "//")):
                    return m.group(0)
                full = ("https:" + u) if u.startswith("//") else u
                k, s = kind, sub
                if kind == "link":                   # <link>: 스타일시트만 CSS 로 다루고, 아이콘 · manifest · preload 는 그대로 받는다
                    tag = (before + after).lower()
                    is_css = re.search(r"\.css(\?|#|$)", full, re.I) or "stylesheet" in tag
                    k, s = ("css", "css") if is_css else ("asset", "css/res")
                rel = self._get(full, k, s)
                return m.group(0) if rel is None else "%s%s%s/%s%s%s" % (before, q, F, rel, q, after)
            text = re.sub(r"""(<%s\b[^>]*?\s%s\s*=\s*)(['"])([^'"]+)\2([^>]*>)""" % (tag_re, attr), repl, text, flags=re.I | re.S)

        rewrite_attr("script", "src", "js", "js")
        rewrite_attr("link", "href", "link", "css")
        rewrite_attr("img", "src", "asset", "img")
        rewrite_attr("source", "src", "asset", "img")
        rewrite_attr("video", "src", "asset", "img")
        rewrite_attr("audio", "src", "asset", "img")
        rewrite_attr("video", "poster", "asset", "img")

        # <style> 블록 안의 @import · url()
        def style(m: re.Match) -> str:
            body = self._css(m.group(2).encode("utf-8"), LOCAL, "css")
            return m.group(1) + body.replace('url("res/', 'url("%s/css/res/' % F).replace('@import url("', '@import url("%s/css/' % F) + m.group(3)
        text = re.sub(r"(<style\b[^>]*>)(.*?)(</style>)", style, text, flags=re.I | re.S)

        if self.split_images:
            text = self._split_images(text)

        for host, why in SLOW_LIBS:                  # 내려받지 못했어도 알려 준다
            if host in text and not any(why in r for r in self.report):
                self.report.append("주의: " + why)
        if self.files:
            self.report.insert(0, "바깥 자료 %d개(%s)를 '%s/' 에 넣었습니다 — 인터넷 없이도 뜹니다" % (len(self.files), _fmt(self.sizes), F))
        for f in self.failed:
            self.report.append("받지 못함: " + f)
        return Result(html=text.encode("utf-8"), folder=F, files=self.files, report=self.report, failed=self.failed, by_url=self.by_url)

    def _split_images(self, text: str) -> str:
        n = 0
        saved = 0

        def repl(m: re.Match) -> str:
            nonlocal n, saved
            mime, b64 = m.group(1).lower(), m.group(2)
            if len(b64) < MIN_SPLIT_IMAGE:
                return m.group(0)
            try:
                raw = base64.b64decode(b64, validate=False)
            except Exception:
                return m.group(0)
            ext = {"jpeg": "jpg", "svg+xml": "svg"}.get(mime.split("/")[-1], mime.split("/")[-1])
            raw, ext, note = _shrink(raw, ext) if self.shrink else (raw, ext, "")
            rel = "img/%s.%s" % (_short(raw), ext)
            self.files[rel] = raw
            self.sizes += len(raw)
            n += 1
            saved += len(b64) - len(raw)
            if note:
                self.report.append(note)
            return "%s/%s" % (self.folder, rel)
        out = re.sub(r"data:(image/[\w.+-]+);base64,([A-Za-z0-9+/=]+)", repl, text)
        if n:
            self.report.append("안에 박힌 큰 그림 %d개를 파일로 뺐습니다 (HTML 이 %s 가벼워짐)" % (n, _fmt(max(0, saved))))
        return out


def _shrink(raw: bytes, ext: str) -> tuple[bytes, str, str]:
    """Pillow 가 있으면 긴 변 IMAGE_MAX_PX 로 줄인다 (PNG 는 그대로 PNG, 사진은 JPEG). 없으면 그대로"""
    if ext == "svg":
        return raw, ext, ""
    try:
        from PIL import Image  # type: ignore
    except Exception:
        return raw, ext, ""
    try:
        im = Image.open(io.BytesIO(raw))
        w, h = im.size
        if max(w, h) <= IMAGE_MAX_PX:
            return raw, ext, ""
        k = IMAGE_MAX_PX / max(w, h)
        im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB").resize((max(1, int(w * k)), max(1, int(h * k))), Image.LANCZOS)
        buf = io.BytesIO()
        if ext in ("jpg", "jpeg") or (im.mode == "RGB" and ext != "png"):
            im.convert("RGB").save(buf, "JPEG", quality=85, optimize=True); ext = "jpg"
        else:
            im.save(buf, "PNG", optimize=True); ext = "png"
        out = buf.getvalue()
        return out, ext, "그림 %d×%d → %d×%d 로 줄였습니다 (%s → %s)" % (w, h, im.size[0], im.size[1], _fmt(len(raw)), _fmt(len(out)))
    except Exception:
        return raw, ext, ""


def _fmt(n: int) -> str:
    return "%d B" % n if n < 1024 else "%.1f KB" % (n / 1024) if n < 1048576 else "%.1f MB" % (n / 1048576)


def convert(html: bytes, html_name: str, *, split_images: bool = True, fonts: bool = True, shrink: bool = False, fetch: Callable[[str], bytes] | None = None) -> Result:
    return Converter(html_name, fetch=fetch, split_images=split_images, fonts=fonts, shrink=shrink).convert(html)


def needs_convert(html: bytes) -> bool:
    """바깥 자료나 큰 base64 그림이 있는가 (없으면 변환할 것이 없음)"""
    t = html[:4 * 1024 * 1024].decode("utf-8", "replace")
    return bool(re.search(r"""(src|href)\s*=\s*['"](https?:)?//""", t, re.I) or re.search(r"url\(\s*['\"]?https?://", t, re.I)
                or re.search(r"data:image/[\w.+-]+;base64,[A-Za-z0-9+/=]{%d,}" % MIN_SPLIT_IMAGE, t))
