#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CalDAV 게이트웨이 점검 — 이 계정으로 어떤 캘린더가 내려오는지 전부 나열한다.

용도: 회사 CalDAV 게이트웨이(예: https://dswcaldav01.daesang.com:16443/kdav/)에 개인 캘린더 말고
      공유 캘린더(예: cal/shared/951290_230407113047.nsf)도 올라와 있는지 PC 에서 한 번에 확인.
방법: CalDAV 규격의 PROPFIND 로 계정 → 캘린더 홈 → 그 안의 모든 컬렉션을 훑고, 각 캘린더에서
      이번 달 일정을 REPORT 로 세어 본다. 추가로 공유 DB 경로 후보 몇 개를 직접 두드려 응답 코드를 보여 준다.
설치할 것 없음(표준 라이브러리만). 비밀번호는 화면에서만 입력받고 어디에도 저장하지 않는다.

  python caldav_check.py                       (주소·아이디·비밀번호를 물어봄)
  python caldav_check.py --url https://host:16443/kdav/ --user dpj
  python caldav_check.py --guess cal/shared/951290_230407113047.nsf   (공유 DB 경로 후보 추가)
  python caldav_check.py --insecure            (회사 인증서 때문에 SSL 오류가 날 때)
  python caldav_check.py --sample              (캘린더마다 이번 달 일정 제목 5개까지 보여 줌)
  python caldav_check.py --as 951290           (다른 계정·팀 계정의 캘린더 홈을 직접 훑어 봄)
"""
import argparse
import base64
import datetime as dt
import getpass
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

DAV = "DAV:"
CAL = "urn:ietf:params:xml:ns:caldav"
CS = "http://calendarserver.org/ns/"
NS = {"d": DAV, "c": CAL, "cs": CS}

DEFAULT_URL = "https://dswcaldav01.daesang.com:16443/kdav/"
DEFAULT_SHARED = "cal/shared/951290_230407113047.nsf"


def say(s=""):
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode("utf-8", "replace").decode("ascii", "replace"))


class Dav:
    def __init__(self, base, user, pw, insecure=False, timeout=20):
        self.base = base if base.endswith("/") else base + "/"
        self.auth = "Basic " + base64.b64encode(("%s:%s" % (user, pw)).encode("utf-8")).decode("ascii")
        self.timeout = timeout
        if insecure:
            self.ctx = ssl._create_unverified_context()
        else:
            self.ctx = None
            try:  # Windows 인증서 저장소의 회사 인증서를 쓰기 위해 (tvrelay 와 같은 방식). 없으면 기본 검증.
                import truststore  # type: ignore
                self.ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            except Exception:
                pass

    def req(self, method, url, body=None, depth=None, ctype="application/xml; charset=utf-8"):
        url = urllib.parse.urljoin(self.base, url)
        data = body.encode("utf-8") if isinstance(body, str) else body
        r = urllib.request.Request(url, data=data, method=method)
        r.add_header("Authorization", self.auth)
        r.add_header("User-Agent", "tv-dashboard caldav_check/1.0")
        if depth is not None:
            r.add_header("Depth", str(depth))
        if data is not None:
            r.add_header("Content-Type", ctype)
        try:
            with urllib.request.urlopen(r, timeout=self.timeout, context=self.ctx) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def propfind_raw(self, url, inner, depth=0):
        body = ('<?xml version="1.0" encoding="utf-8"?><d:propfind xmlns:d="DAV:">%s</d:propfind>' % inner)
        return self.req("PROPFIND", url, body, depth=depth)

    def propfind(self, url, props, depth=0):
        body = ('<?xml version="1.0" encoding="utf-8"?>'
                '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav" xmlns:cs="http://calendarserver.org/ns/">'
                '<d:prop>%s</d:prop></d:propfind>' % "".join("<%s/>" % p for p in props))
        return self.req("PROPFIND", url, body, depth=depth)


def parse_multistatus(data):
    """→ [(href, {prop_tag: Element}), ...]  (200 OK 인 prop 만)"""
    out = []
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return out
    for resp in root.findall("d:response", NS):
        href = (resp.findtext("d:href", default="", namespaces=NS) or "").strip()
        props = {}
        for ps in resp.findall("d:propstat", NS):
            st = ps.findtext("d:status", default="", namespaces=NS) or ""
            if " 200 " not in (" " + st + " "):
                continue
            pe = ps.find("d:prop", NS)
            if pe is None:
                continue
            for child in pe:
                props[child.tag] = child
        out.append((href, props))
    return out


def hrefs_in(el):
    if el is None:
        return []
    return [(h.text or "").strip() for h in el.findall("d:href", NS) if (h.text or "").strip()]


def tag(ns, name):
    return "{%s}%s" % (ns, name)


def is_calendar(props):
    rt = props.get(tag(DAV, "resourcetype"))
    return rt is not None and rt.find("c:calendar", NS) is not None


def comp_set(props):
    el = props.get(tag(CAL, "supported-calendar-component-set"))
    if el is None:
        return ""
    return ",".join(c.get("name", "") for c in el.findall("c:comp", NS))


def report_month(dav, href):
    """이번 달 VEVENT 를 REPORT 로 받아 (개수, 제목들) 를 돌려준다."""
    today = dt.date.today()
    start = today.replace(day=1)
    end = (start + dt.timedelta(days=40)).replace(day=1)
    fmt = lambda d: d.strftime("%Y%m%dT000000Z")
    body = ('<?xml version="1.0" encoding="utf-8"?>'
            '<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            '<d:prop><d:getetag/><c:calendar-data/></d:prop>'
            '<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">'
            '<c:time-range start="%s" end="%s"/></c:comp-filter></c:comp-filter></c:filter>'
            '</c:calendar-query>' % (fmt(start), fmt(end)))
    st, _, data = dav.req("REPORT", href, body, depth=1)
    if st != 207:
        return st, 0, []
    n = 0
    titles = []
    for _, props in parse_multistatus(data):
        cd = props.get(tag(CAL, "calendar-data"))
        txt = (cd.text or "") if cd is not None else ""
        if "BEGIN:VEVENT" not in txt:
            continue
        n += txt.count("BEGIN:VEVENT")
        for m in re.finditer(r"^SUMMARY[^:]*:(.*)$", txt, re.M):
            if len(titles) < 5:
                titles.append(m.group(1).strip())
    return st, n, titles


def main():
    ap = argparse.ArgumentParser(description="CalDAV 게이트웨이가 내주는 캘린더 나열")
    ap.add_argument("--url", help="게이트웨이 주소 (기본: 물어봄, 예 %s)" % DEFAULT_URL)
    ap.add_argument("--user", help="DSW 아이디")
    ap.add_argument("--guess", action="append", default=[], help="공유 DB 경로 후보 추가 (여러 번 가능)")
    ap.add_argument("--insecure", action="store_true", help="SSL 인증서 검증 생략 (회사 인증서 오류 때)")
    ap.add_argument("--sample", action="store_true", help="캘린더마다 이번 달 제목 5개까지 표시")
    ap.add_argument("--as", dest="others", action="append", default=[], help="다른 계정(사번·팀 계정)의 캘린더 홈을 직접 훑기 (여러 번 가능)")
    a = ap.parse_args()

    url = a.url or input("게이트웨이 주소 [%s]: " % DEFAULT_URL).strip() or DEFAULT_URL
    user = a.user or input("DSW 아이디: ").strip()
    pw = getpass.getpass("DSW 비밀번호 (화면에 안 보임): ")
    dav = Dav(url, user, pw, insecure=a.insecure)
    say()
    say("■ 1. 접속 · 로그인 확인  (%s)" % dav.base)
    try:
        st, hd, data = dav.propfind("", ["d:current-user-principal", "d:resourcetype", "d:displayname"], depth=0)
    except urllib.error.URLError as e:
        say("  ✖ 접속 실패: %s" % e.reason)
        if "CERTIFICATE" in str(e.reason).upper() or "SSL" in str(e.reason).upper():
            say("    회사 인증서 때문일 수 있습니다. --insecure 를 붙여 다시 시도해 보세요.")
        return 2
    say("  PROPFIND / → HTTP %s  %s" % (st, "(DAV: %s)" % hd.get("DAV", "") if hd.get("DAV") else ""))
    if st == 401:
        say("  ✖ 아이디·비밀번호가 맞지 않거나 이 주소는 다른 로그인 방식을 씁니다.")
        return 2
    if st not in (207, 200):
        say("  ✖ CalDAV 응답이 아닙니다. 주소 끝의 경로(/kdav/)를 확인하세요. 응답 일부:")
        say("    " + data[:300].decode("utf-8", "replace").replace("\n", " "))
        return 2

    principal = None
    for href, props in parse_multistatus(data):
        cup = props.get(tag(DAV, "current-user-principal"))
        hs = hrefs_in(cup)
        if hs:
            principal = hs[0]
    say("  계정(principal): %s" % (principal or "(안 알려줌)"))

    say()
    say("■ 2. 캘린더 홈 · 위임(proxy) 확인")
    homes = []
    proxies = []
    if principal:
        st, _, data = dav.propfind(principal, ["c:calendar-home-set", "cs:calendar-proxy-read-for",
                                               "cs:calendar-proxy-write-for", "d:group-membership", "d:displayname"], depth=0)
        say("  PROPFIND %s → HTTP %s" % (principal, st))
        for href, props in parse_multistatus(data):
            homes += hrefs_in(props.get(tag(CAL, "calendar-home-set")))
            for k in ("calendar-proxy-read-for", "calendar-proxy-write-for"):
                proxies += hrefs_in(props.get(tag(CS, k)))
            proxies += hrefs_in(props.get(tag(DAV, "group-membership")))
    if not homes:
        homes = [""]  # 홈을 안 알려주면 기본 주소 자체를 훑는다
    say("  캘린더 홈: %s" % ", ".join(h or dav.base for h in homes))
    say("  위임받은 계정(proxy/group): %s" % (", ".join(proxies) if proxies else "없음"))

    say()
    say("■ 3. 이 계정으로 보이는 캘린더 전부")
    found = []
    seen = set()
    todo = list(homes)
    # 위임받은 계정의 캘린더 홈도 같이 훑는다 (공유 캘린더가 위임 형태로 나오는 서버 대응)
    for p in proxies:
        st, _, data = dav.propfind(p, ["c:calendar-home-set"], depth=0)
        for _, props in parse_multistatus(data):
            todo += hrefs_in(props.get(tag(CAL, "calendar-home-set")))
    for home in todo:
        if home in seen:
            continue
        seen.add(home)
        st, _, data = dav.propfind(home, ["d:displayname", "d:resourcetype", "c:supported-calendar-component-set",
                                          "c:calendar-description", "d:owner", "cs:shared-url"], depth=1)
        say("  PROPFIND %s (Depth 1) → HTTP %s" % (home or "/", st))
        if st != 207:
            continue
        for href, props in parse_multistatus(data):
            if not is_calendar(props):
                continue
            name_el = props.get(tag(DAV, "displayname"))
            name = (name_el.text or "").strip() if name_el is not None else ""
            desc_el = props.get(tag(CAL, "calendar-description"))
            desc = (desc_el.text or "").strip() if desc_el is not None else ""
            own = hrefs_in(props.get(tag(DAV, "owner")))
            found.append((href, name, comp_set(props), desc, own[0] if own else ""))
    if not found:
        say("  (캘린더 컬렉션을 하나도 찾지 못했습니다)")
    for href, name, comps, desc, own in found:
        st, n, titles = report_month(dav, href)
        say("  • %s" % (name or "(이름 없음)"))
        say("      주소: %s" % href)
        say("      종류: %s%s%s" % (comps or "?", ("  · 설명: " + desc) if desc else "", ("  · 소유: " + own) if own else ""))
        say("      이번 달 일정: %s" % ("%d건" % n if st == 207 else "REPORT 실패 HTTP %s" % st))
        if a.sample and titles:
            for t in titles:
                say("        - %s" % t)

    say()
    say("■ 3b. 게이트웨이 상위 목록 (다른 계정·공용 캘린더가 경로로 드러나는지)")
    top_homes = []
    for top in ("", "principals/", "calendars/", "calendars/public/", "public/"):
        st, _, data = dav.propfind(top, ["d:displayname", "d:resourcetype"], depth=1)
        rows = parse_multistatus(data) if st == 207 else []
        say("  PROPFIND %-18s (Depth 1) → HTTP %s%s" % (top or "/", st, ("  · 항목 %d개" % max(0, len(rows) - 1)) if rows else ""))
        for href, props in rows[1:41]:
            name_el = props.get(tag(DAV, "displayname"))
            name = (name_el.text or "").strip() if name_el is not None else ""
            kind = "캘린더" if is_calendar(props) else ("폴더" if props.get(tag(DAV, "resourcetype")) is not None and len(list(props[tag(DAV, "resourcetype")])) else "항목")
            say("      %-7s %s%s" % (kind, href, ("  (" + name + ")") if name else ""))
            if is_calendar(props):
                top_homes.append((href, name))
        if len(rows) > 41:
            say("      ... 외 %d개" % (len(rows) - 41))
    # 공유 DB 이름 앞의 숫자(사번으로 보임)와 --as 로 준 계정의 캘린더 홈을 직접 훑는다
    others = list(a.others)
    for g in (a.guess or [DEFAULT_SHARED]):
        m = re.match(r"(\d{4,})", g.strip("/").rsplit("/", 1)[-1])
        if m and m.group(1) not in others:
            others.append(m.group(1))
    for who in others:
        say("  --- 계정 '%s' 의 캘린더 홈 ---" % who)
        for home in ("calendars/" + who + "/", "principals/" + who + "/", who + "/"):
            st, _, data = dav.propfind(home, ["d:displayname", "d:resourcetype", "c:calendar-home-set"], depth=1)
            say("  PROPFIND %-40s → HTTP %s" % (home, st))
            if st != 207:
                continue
            for href, props in parse_multistatus(data):
                for h in hrefs_in(props.get(tag(CAL, "calendar-home-set"))):
                    say("      캘린더 홈: %s" % h)
                if is_calendar(props):
                    name_el = props.get(tag(DAV, "displayname"))
                    name = (name_el.text or "").strip() if name_el is not None else ""
                    st2, n, _ = report_month(dav, href)
                    say("      ★ 캘린더 %s%s · 이번 달 %s" % (href, (" (" + name + ")") if name else "", ("%d건" % n) if st2 == 207 else "REPORT HTTP %s" % st2))
                    found.append((href, name or ("계정 " + who), "", "", who))

    say()
    say("■ 4. 공유 DB 경로를 직접 두드려 보기 (게이트웨이가 목록에 안 보여 줘도 경로로는 열릴 수 있음)")
    guesses = a.guess or [DEFAULT_SHARED]
    cands = []
    for g in guesses:
        g = g.strip("/")
        short = g.rsplit("/", 1)[-1]
        stem = short[:-4] if short.lower().endswith(".nsf") else short
        num = re.match(r"(\d{4,})", stem)
        num = num.group(1) if num else stem
        for c in (g + "/", short + "/", stem + "/", "calendars/" + user + "/" + stem + "/", "calendars/" + stem + "/",
                  "shared/" + stem + "/", "shared/" + short + "/", "calendars/" + num + "/", "calendars/" + num + "/Calendar/",
                  "calendars/" + num + "/default/", "calendars/public/" + stem + "/", "calendars/public/" + num + "/"):
            if c not in cands:
                cands.append(c)
    ok_any = False
    for c in cands:
        st, hd, data = dav.propfind(c, ["d:displayname", "d:resourcetype"], depth=0)
        mark = "  "
        detail = ""
        if st == 207:
            rows = parse_multistatus(data)
            cal = any(is_calendar(p) for _, p in rows)
            mark = "★" if cal else "○"
            ok_any = ok_any or cal
            # 207 이라도 안에 404 가 들어 있으면 '없음' 이다 — 실제 내용을 보여 준다
            try:
                root = ET.fromstring(data)
                sts = [(r.findtext("d:href", default="", namespaces=NS) or "").strip() + " " +
                       " / ".join((x.text or "").strip() for x in r.findall(".//d:status", NS)) for r in root.findall("d:response", NS)]
                detail = "  → " + ("; ".join(sts) if sts else "응답 비어 있음(response 없음)")
            except ET.ParseError:
                detail = "  → XML 아님: " + data[:120].decode("utf-8", "replace").replace("\n", " ")
            if len(detail) > 160:
                detail = detail[:160] + "…"
        say("  %s %-60s HTTP %s%s" % (mark, c, st, "  ← 캘린더!" if mark == "★" else detail))

    say()
    say("■ 5. 등록 문서의 속성 · 서버가 허용하는 명령 (공유 캘린더를 직접 등록할 여지가 있는지)")
    STD = {DAV, CAL, CS, "http://apple.com/ns/ical/", "urn:ietf:params:xml:ns:carddav"}
    def shortns(t):
        if t.startswith("{"):
            ns, nm = t[1:].split("}", 1)
            return (ns if ns in STD else "★" + ns) + " " + nm
        return t
    targets = [("캘린더 홈", homes[0] if homes and homes[0] else "")] + [("캘린더 " + (n or h), h) for h, n, _, _, _ in found[:3]]
    for label, href in targets:
        st, hd, _ = dav.req("OPTIONS", href)
        say("  [%s] %s" % (label, href or dav.base))
        say("      OPTIONS → HTTP %s · Allow: %s" % (st, hd.get("Allow", "(없음)")))
        if hd.get("DAV"):
            say("      DAV: %s" % hd.get("DAV"))
        st, _, data = dav.propfind_raw(href, "<d:propname/>", depth=0)
        names = []
        if st == 207:
            try:
                root = ET.fromstring(data)
                for pe in root.findall(".//d:prop", NS):
                    for ch in pe:
                        if ch.tag not in names:
                            names.append(ch.tag)
            except ET.ParseError:
                pass
        say("      속성 이름 %d개 (★ = 표준 아님, 게이트웨이 고유): " % len(names))
        for t in names:
            say("        " + shortns(t))
        st, _, data = dav.propfind_raw(href, "<d:allprop/>", depth=0)
        if st == 207:
            for _, props in parse_multistatus(data):
                for t, el in props.items():
                    ns = t[1:].split("}", 1)[0] if t.startswith("{") else ""
                    if ns in STD:
                        continue
                    val = (el.text or "").strip() or "".join(ET.tostring(c, encoding="unicode") for c in el)
                    val = re.sub(r"\s+", " ", val)[:200]
                    say("      ★값 %s = %s" % (shortns(t), val or "(비어 있음)"))
    say("  해석: Allow 에 MKCALENDAR 가 있고 ★속성에 노츠 DB 경로(…nsf)가 보이면, 같은 속성으로 공유 DB 를 등록해 볼 여지가 있습니다.")

    say()
    say("■ 결론")
    names = [n or h for h, n, _, _, _ in found]
    say("  게이트웨이가 이 계정에 내주는 캘린더: %d개 — %s" % (len(found), ", ".join(names) if names else "없음"))
    shared_like = [n for n in names if re.search(r"shared|공유|951290|team|팀", n, re.I)]
    if shared_like or ok_any:
        say("  → 공유 캘린더로 보이는 것이 있습니다: %s" % (", ".join(shared_like) or "경로로 열림(★)"))
        say("    이 주소를 TV 앱의 자동 받기에 쓸 수 있습니다.")
    else:
        say("  → 공유 캘린더는 이 게이트웨이에 없습니다. 개인 캘린더만 내려옵니다.")
        say("    공유 캘린더는 DSW 의 ?ReadViewEntries&OutputFormat=JSON 주소를 TV 앱이 주기적으로 받는 방식으로 자동화해야 합니다.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
