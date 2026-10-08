# TV 대시보드 (LG CreateBoard 75TR3DQ용 자료 열람·파일 관리 APK)

TV를 **자료 저장소 + 화면 표시기**로 사용하는 Android 앱입니다.
관리자가 PC 브라우저로 TV 안의 자료 폴더에 HTML·이미지·JSON을 올리면,
**상단에 대상 로고와 "대상 오산공장 Dashboard"**, **왼쪽 사이드바에 정사각형 아이콘 메뉴(맨 아래 설정)**,
**오른쪽에 선택한 대시보드(index.html)** 가 표시됩니다. (vDesk 스타일: 어두운 헤더·사이드바 + 밝은 콘텐츠)

```
┌──────────────────────────────────────────────────────────────┐
│ [daesang] 대상 오산공장 Dashboard              2026.10.06 (화) 09:00 │
├────────┬─────────────────────────────────────────────────────┤
│ [icon] │                                                     │
│ 생산팀  │   선택한 폴더의 index.html (WebView)                    │
│ [icon] │   같은 폴더의 data.json · 이미지 · CSS · JS               │
│ 지원팀  │                                          [⛶ 전체화면] │
│        │                                                     │
│ ⚙ 설정 │                                                     │
└────────┴─────────────────────────────────────────────────────┘
 일정 시간 입력이 없으면: 루트 동영상 + 멘트 오버레이 ("화면을 터치하면 대시보드로 들어갑니다")
```

```
관리자 PC ──(브라우저 / API, Tailscale 또는 같은 공유기)──▶ TV 안의 APK
                                                          ├─ 내장 웹서버(파일 관리 API, 포트 8080)
                                                          ├─ 자료 폴더 (TV 내부 저장소)
                                                          └─ 화면 표시 (메뉴 + WebView + 대기 화면)
```

- 별도 OS·PC·서버 장비가 필요 없습니다. TV에 원래 설치된 Android 위에서 APK 하나로 동작합니다.
- **Tailscale은 접속 통로(VPN)일 뿐**이며, 파일 저장·관리·표시는 모두 이 APK가 담당합니다.
- 자료는 TV 내부에 저장되므로 **인터넷이 끊겨도 열람**할 수 있습니다.

---

## 1. 기기 호환성 (75TR3DQ)

| 항목 | 내용 |
|---|---|
| 모델 | LG CreateBoard **75TR3DQ-B** (터치 인터랙티브 디스플레이) |
| OS | **Android 14**, Google **EDLA** 인증 (Play 스토어·Google 서비스 포함) |
| 사양 | 옥타코어, RAM 8GB, 저장소 64GB, 4K UHD, 50점 멀티터치, Wi-Fi 6E, 유선 LAN |
| 이 앱의 요구 사항 | minSdk 26(Android 8.0) / targetSdk 34(Android 14) → **75TR3DQ에 맞춰 빌드** |
| APK 설치 | Android 14 표준 방식으로 가능: 파일 관리자·브라우저 앱에 **'출처를 알 수 없는 앱 설치'** 허용 후 설치 |

> 출처: 판매처 사양표([Onedirect](https://www.onedirect.co.uk/product/lg-createboard-tr3dq-75-inch-uhd-interactive-display), [AVLGear](https://avlgear.com/products/lg-75tr3dq-b-createboard-standard-interactive-display-75-inch), [MyITHub](https://www.myithub.com.au/?p=650273)).
> 같은 CreateBoard라도 구형 TR3BF/TR3DJ는 OS 버전이 다르므로 모델명을 꼭 확인하세요.

**설치 전에 TV에서 직접 확인할 것**
1. `설정 > 휴대전화 정보(디바이스 정보) > Android 버전` 이 14인지
2. 관리자(MDM/EDLA 정책)로 **알 수 없는 출처 앱 설치가 막혀 있지 않은지**
   – 막혀 있으면 기기 관리자/LG 관리 콘솔에서 허용해야 합니다(앱이 우회할 수 없음).
3. `설정 > 앱 > 특별한 앱 접근` 에 **'출처를 알 수 없는 앱 설치'**, **'다른 앱 위에 표시'**, **'모든 파일에 대한 접근'** 메뉴가 있는지
   – 앱의 설정 화면 버튼은 이 메뉴들을 엽니다. 제조사가 숨긴 경우 일부 기능(재부팅 후 화면 자동 실행, 공용 폴더)은 사용할 수 없고 나머지는 정상 동작합니다.
4. 절전 설정: `설정 > 전원/화면` 의 **자동 꺼짐·대기 모드** 시간 (아래 7장 참고)

---

## 2. 최초 설치

1. [Releases](../../releases) 에서 `tv-dashboard-vX.Y.Z.apk` 를 받습니다.
   (Releases 가 아직 없으면 [Actions](../../actions) 의 최신 실행 → Artifacts 의 debug APK 로 먼저 시험 가능 — 아래 주의 참고)
2. USB 메모리로 TV에 복사 → TV의 파일 관리자에서 APK 실행
   (또는 TV 브라우저로 Releases 페이지에서 직접 다운로드)
3. "이 출처의 앱 설치 허용" → 설치
4. 앱 실행 → 왼쪽 아래 ⚙ 설정 → **관리자 비밀번호**(초기 비밀번호)와 **접속 주소** 확인

> ⚠ debug APK(`com.seyoungjo.tvdashboard.debug`)는 시험용으로 정식 앱과 **별개의 앱**으로 설치됩니다.
> 실제 운영은 처음부터 **서명된 Release APK** 를 설치하세요. 그래야 이후 업데이트가 앱 삭제 없이 이어집니다.

---

## 3. 최소 기능 흐름: 폴더 생성 → 업로드 → 메뉴 생성 → 표시

1. 관리자 PC 브라우저에서 `http://<TV 주소>:8080` 접속 → 초기 비밀번호로 로그인 → 비밀번호 변경
2. **[예제 대시보드 만들기]** 클릭 (또는 직접)
   - [새 폴더] → `생산팀`
   - `생산팀` 폴더로 들어가 `index.html`, `data.json`, `icon.png` 업로드
     (`sample/자료/` 폴더의 예제를 [폴더째 업로드]로 올려도 됩니다)
3. TV 왼쪽에 `생산팀` 정사각형 버튼이 **자동으로 생기고**, 오른쪽에 index.html 이 표시됩니다.
4. `data.json` 을 다시 올리면(교체) 화면이 자동 새로고침됩니다.

---

## 4. 메뉴 규칙 (단순·일관)

| 규칙 | 내용 |
|---|---|
| 버튼 | 자료 폴더 **바로 아래 폴더 1개 = 버튼 1개** |
| 버튼 이름 | 폴더명. 앞의 정렬 번호는 숨김 (`01_생산팀` → `생산팀`, `2. 지원팀` → `지원팀`) |
| 순서 | PC 프로그램의 TV 미리보기에서 **아이콘을 끌어 순서를 바꾸고 [순서 저장]** → 자료 폴더의 `메뉴순서.txt`(한 줄에 폴더 이름 하나). 적히지 않은 폴더는 그 뒤에 폴더명 자연 정렬 (`2_` < `10_`) |
| main 폴더 | 메뉴가 아니라 **화면보호기** (12-1 참고) |
| 아이콘 | 폴더 안 **`icon.png`** — **흰색 아이콘 + 투명 배경** PNG(정사각형, 256px 권장). 색·틀 없이 검은 사이드바 위에 그대로 표시, 선택 항목은 왼쪽 흰 막대. icon.jpg/webp 도 가능. 없으면 이름 첫 글자 |
| 표시 파일 | 폴더의 `index.html` (없으면 `index.htm`). 없으면 안내 문구 표시 |
| 숨김 | `.` 또는 `_` 로 시작하는 폴더는 메뉴에 나오지 않음 |
| 대기 화면 동영상 | 자료 폴더 **루트**의 동영상(mp4·webm·mkv 등). 여러 개면 이름순으로 반복 재생 |
| 상단 로고·제목 | 로고: 기본 대상 로고, 자료 폴더 루트에 `logo.png` 를 올리면 교체. 제목: 설정의 '상단 제목'(기본 "대상 오산공장 Dashboard") |

```
자료/
  대기화면.mp4            ← 대기 화면 동영상 (루트)
  logo.png               ← (선택) 상단 로고 교체
  01_생산팀/
    icon.png             ← 메뉴 아이콘
    index.html
    data.json
    style.css · app.js · 기타 이미지
  02_지원팀/
    ...
  03_일정/
    icon.png · index.html
    CustomEventList.json  ← 노츠 캘린더 뷰 내보내기(JSON) 를 그대로 올리면 월 달력으로 표시
```

### 예제 대시보드 (vDesk 스타일)
`sample/자료/01_생산팀` 은 색상 타일 4개 + 목록 2개 + 게이지·막대·도넛 카드로 구성되며, **화면 내용은 전부 `data.json` 으로 바꿉니다.**
`tiles[]`(label·value·sub·color), `lists[]`(title·color·items[time·text·tag]), `cards[]`(type: gauge / bars / donut).
색 이름: blue · green · red · orange · sky · teal · purple · pink · gray (또는 `#RRGGBB`). 외부 라이브러리를 쓰지 않아 오프라인에서도 그대로 표시됩니다.

### 예제 일정 캘린더 (1796 × 1002 기준)
`sample/자료/03_일정` 은 같은 폴더의 **`CustomEventList.json`**(노츠 캘린더 뷰 `?ReadViewEntries&OutputFormat=JSON` 내보내기, 파일명 고정)을 상대 경로로 읽어
월 달력(일요일·공휴일 빨강, 토요일 파랑, 오늘 표시, 기간 일정 막대, 칸을 넘치면 `+N 더보기`)과 오른쪽에 선택한 날의 일정 목록을 보여 줍니다.
- 열 해석: `$147` 제목 · `$153` 담당 · `$144`/`$146` 시작·끝 · `$StartDate`/`$EndDate` 날짜 · `_AllDay` 종일 · `$Color` 색(`#RRGGBB|`) · `$Custom` 장소(`|장소|`).
  색이 없으면 제목으로 분류(휴가·출장·교육·기타)해 색을 정합니다. 뷰가 기간 일정을 날짜마다 한 줄씩 넣어 주므로 같은 문서·같은 기간은 막대 하나로 이어 그립니다.
- 저장·누적하지 않습니다. JSON 을 다시 올리면 그 내용만 다시 그립니다(1분마다 다시 읽고, 바뀌었으면 갱신).
- 공휴일은 2025~2027 이 내장되어 있고, 같은 폴더에 `holidays.json`(`{"20280101":"신정"}`) 을 두면 덧붙여집니다.
- 화면은 1796 × 1002 로 설계되어 있고 WebView 크기에 맞춰 비율을 유지한 채 확대·축소됩니다.

### 폰트
앱 화면은 **Pretendard Bold/ExtraBold**(굵은 한글 서체, SIL OFL 무료 라이선스)를 사용합니다. 대시보드 HTML에서도 앱에 내장된 폰트를 인터넷 없이 쓸 수 있습니다:
```css
@font-face { font-family: "Pretendard"; font-weight: 700;
  src: url("https://appassets.androidplatform.net/assets/fonts/Pretendard-Bold.woff2") format("woff2"); }
/* SemiBold(600) · ExtraBold(800) 도 같은 방식: Pretendard-SemiBold.woff2 / Pretendard-ExtraBold.woff2 */
body { font-family: "Pretendard", sans-serif; font-weight: 700; }
```

### index.html 작성 규칙
- 같은 폴더의 파일은 **상대 경로**로 사용: `fetch('data.json')`, `<img src="chart.png">`, `<link href="style.css">`
- TV 앱은 `https://appassets.androidplatform.net/data/<폴더>/index.html` 주소로 열기 때문에 `file://` 의 CORS 제약 없이 JSON을 읽을 수 있습니다.
- 캐시를 쓰지 않으므로 교체된 파일이 바로 반영됩니다. 페이지가 스스로 `setInterval` 로 data.json 을 다시 읽어도 됩니다.
- **오프라인 열람을 위해 외부 CDN(차트 라이브러리 등)도 폴더에 함께 넣으세요.** 인터넷 주소를 참조하면 인터넷이 끊겼을 때 표시되지 않습니다.
- 다른 폴더 파일은 `../공통/lib.js` 처럼 참조 가능합니다 (자료 폴더 밖은 불가).

---

## 5. TV 조작

| 동작 | 터치 | 리모컨 |
|---|---|---|
| 메뉴 이동 | 스크롤 | ▲▼ |
| 대시보드 열기 | 버튼 터치 | 확인(OK) |
| 대시보드 → 메뉴로 | 메뉴 버튼 터치 | 뒤로 (페이지 안에서 이동했다면 먼저 이전 페이지로) |
| 전체 화면 / 해제 | 오른쪽 위 ⛶ / ☰ | 버튼 선택 / 뒤로 |
| 대기 화면 해제 | 두 번 터치 (한 번 누르면 물결 + "한 번 더 눌러 주세요", 5초 안에 한 번 더) | 아무 키 |
| 앱 종료 | – | 메뉴에서 뒤로 2번 |
| 설정 | 왼쪽 사이드바 맨 아래 ⚙ 설정 (PIN 설정 가능) | ⚙ 선택 |

---

## 6. 원격 파일 관리 (관리 웹 + API)

관리 웹 `http://<TV 주소>:8080`
- 폴더 생성·이름 변경·삭제, 파일 업로드(여러 개·폴더째·드래그)·다운로드·교체·삭제
- 대기 화면/새로고침/PIN/업데이트 주소 설정, 비밀번호 변경, API 토큰 확인·재발급, APK 업로드(업데이트)

**업로드 안전성**: 업로드 내용은 자료 폴더의 숨김 폴더 `.tmp` 에 먼저 저장 → 디스크 동기화(fsync) → **원자적 이름 변경**으로 교체합니다.
화면은 항상 "이전 완성본" 또는 "새 완성본"만 읽으므로 불완전한 파일이 표시되지 않습니다. 업로드가 끊기면 기존 파일이 그대로 남습니다.
화면 표시 중에도 업로드할 수 있습니다.

### API (PC 프로그램에서 JSON 주기 업로드)
모든 요청에 `Authorization: Bearer <API 토큰>` 헤더 (토큰: TV 설정 또는 관리 웹 > 설정)

```
GET    /api/status                        상태(버전·저장 위치·남은 공간)
GET    /api/menu                          TV 메뉴 구성
GET    /api/list?path=폴더                 목록
GET    /api/file?path=폴더/파일            다운로드
PUT    /api/file?path=폴더/파일            업로드/교체 (본문 = 파일 내용, &overwrite=0 이면 덮어쓰기 금지)
DELETE /api/file?path=경로[&recursive=1]   삭제
POST   /api/mkdir?path=폴더                폴더 생성
POST   /api/rename?path=원래경로&to=새경로  이름 변경/이동
POST   /api/reload                        TV 화면 새로고침
GET|PUT /api/settings                     설정(JSON)
PUT    /api/update/apk                    APK 업로드 → TV 에서 설치 승인
```

```bat
:: Windows curl (경로는 URL 인코딩)
curl -X PUT -H "Authorization: Bearer 토큰" --data-binary "@data.json" ^
  "http://100.64.0.10:8080/api/file?path=%EC%83%9D%EC%82%B0%ED%8C%80/data.json"
```
PowerShell 예시와 작업 스케줄러용 스크립트: [`scripts/upload-json.ps1`](scripts/upload-json.ps1), Linux/cron: [`scripts/upload-json.sh`](scripts/upload-json.sh)

### 보안
- 관리자 로그인: 최초 실행 시 **임의 초기 비밀번호**를 만들어 **TV 설정 화면에만** 표시 → 관리 웹에서 변경 권장(변경 후에는 표시되지 않음, 분실 시 TV 설정에서 초기화)
- 비밀번호는 PBKDF2 해시로만 저장, IP별 로그인 5회 실패 시 60초 잠금
- API 토큰은 파일·설정 API만 사용 가능(비밀번호 변경·토큰 재발급은 관리자 로그인 전용)
- 모든 경로는 **자료 폴더 안으로 제한** (`..`, 숨김 파일, 심볼릭 링크로 벗어나기 차단)
- 설정 **'Tailscale 주소(100.x)에서만 접속 허용'** 을 켜면 같은 공유기에서도 Tailscale을 통해서만 접속됩니다.
- 통신은 HTTP 입니다. **Tailscale 사용 시 구간 전체가 WireGuard로 암호화**됩니다. 공유기 포트포워딩으로 인터넷에 직접 노출하지 마세요.
- 터치 화면에서 누구나 설정을 열지 못하도록 **설정 잠금 PIN** 을 지정하세요.

---

## 7. 외부 접속 (서로 다른 공유기) — Tailscale

1. TV: Play 스토어에서 **Tailscale** 설치 → 로그인 → 연결
   - `Android 설정 > 네트워크 > VPN > Tailscale > ⚙` 에서 **'상시 VPN(Always-on)'** 켜기 (재부팅 후 자동 연결)
2. 관리자 PC: Tailscale 설치 → **같은 계정(tailnet)** 으로 로그인
3. TV 앱 ⚙ 설정의 접속 주소 중 `100.x.y.z (Tailscale)` 로 접속: `http://100.x.y.z:8080`
   (MagicDNS 사용 시 `http://<TV 기기명>:8080`)

> Tailscale 은 VPN 앱이고 OS가 아닙니다. 파일은 TV 내부 자료 폴더에 저장되고, 관리·표시는 이 APK가 합니다.
> Tailscale 이 끊겨도 TV 화면 표시와 같은 공유기 내 접속은 계속 동작합니다.

---

### TV 주소 고정
- **Tailscale 주소는 고정입니다.** TV에 한 번 부여된 `100.x.y.z` 는 공유기·통신사·내부 IP가 바뀌어도 그대로라서 `http://100.x.y.z:8080` 을 계속 쓰면 됩니다.
  - 이름으로 접속: Tailscale 관리 콘솔(login.tailscale.com) → Machines 에서 TV 이름을 예: `osan-tv` 로 변경 → **MagicDNS** 켜기 → `http://osan-tv:8080`
  - 같은 화면에서 TV 항목 ⋯ → **Disable key expiry** (기본 180일 후 재로그인 요구를 없앰)
- 같은 공유기 안에서 내부 IP(192.168.x.x)를 고정하려면: 공유기 관리 화면의 **DHCP 고정 할당(MAC 주소 예약)** 또는 TV `설정 > 네트워크 > IP 설정 > 고정` 사용.

### Tailscale 없이: GitHub 중계 + PC 프로그램 (추천)
TV 와 PC 에 별도 앱을 깔지 않고 **GitHub 공개 레포를 우체통으로만** 써서 어느 망에서든 관리할 수 있습니다.
- PC: `pc/` 폴더(또는 Releases 의 `tvrelay-pc-vX.Y.Z.zip`)의 `tvrun.bat` 실행 → 브라우저 화면에서 파일·설정·APK 를 보냄
- 레포에는 **암호화된 작업이 잠깐** 지나가고 TV 가 가져가면 바로 지워집니다. 자료는 **TV 에만** 저장됩니다.
- **TV 에서는 설정할 것이 없습니다.** TV 화면의 연결 코드(예: `K7QM-4PXD`)를 PC 프로그램에 입력하면 연결 정보가 코드로 암호화되어 전달됩니다.
- PC 화면은 탐색기형: 왼쪽 폴더 트리(끌어다 놓기로 올리기) · 오른쪽 미리보기(대시보드를 TV 와 똑같이 표시)
- TV 앱 상단 ☰ 버튼으로 왼쪽 메뉴를 숨기기/열기 할 수 있습니다.
- 설정 방법: [`pc/README.md`](pc/README.md)

## 8. 절전 · 화면 꺼짐 · 재부팅 시 동작

| 상황 | 동작 |
|---|---|
| 앱 화면 표시 중 | 화면 꺼짐 방지(설정에서 끄기 가능). 서버는 별도 **포그라운드 서비스**로 동작 |
| 다른 앱으로 전환 / 앱 화면 종료 | 서버는 계속 동작 (알림 영역에 '파일 관리 서버 실행 중') |
| 화면만 꺼짐(백라이트 off) | 서버 유지: 앱이 CPU·Wi-Fi 잠금(WakeLock/WifiLock)을 잡고 있음 |
| TV **대기/전원 끔(리모컨 전원)** | 기기가 SoC·네트워크를 끄는 대기 모드라면 **어떤 앱도 서버를 유지할 수 없습니다.** 원격 관리가 필요하면 TV 설정에서 자동 꺼짐·대기 진입을 끄거나 '네트워크 대기/빠른 시작' 옵션을 확인하세요 |
| 재부팅 | 부팅 완료 시 **서버 자동 시작**. 화면(앱)까지 자동으로 띄우려면 ⚙ 설정 → **'다른 앱 위에 표시' 권한 허용** (Android 10+ 정책) |
| 앱 업데이트 직후 | 서버 자동 재시작 (위 권한이 있으면 화면도 다시 열림) |

> 실제 75TR3DQ 의 대기 모드에서 네트워크가 유지되는지는 **현장에서 1회 확인**이 필요합니다:
> 리모컨 전원 끄기 → 관리자 PC에서 `http://<TV주소>:8080/api/ping` 응답 여부 확인.

---

## 9. 저장 위치와 앱 삭제 시 자료

| 설정 | 위치 | 권한 | 앱 **업데이트** | 앱 **삭제** |
|---|---|---|---|---|
| 앱 전용 폴더(기본) | `/sdcard/Android/data/com.seyoungjo.tvdashboard/files/자료` | 불필요 | 유지 | **자료 삭제됨** |
| 공용 폴더 | `/sdcard/자료` | '모든 파일에 대한 접근' 허용 필요 | 유지 | **자료 남음** (설정·비밀번호는 삭제) |

- ⚙ 설정 → **'앱 삭제 시 자료 안내'** 에서 현재 상태를 확인할 수 있고, 관리 웹 상단에도 표시됩니다.
- 저장 위치를 바꿔도 기존 자료는 자동으로 옮겨지지 않습니다(관리 웹에서 다운로드 후 다시 업로드).
- 업데이트는 항상 기존 앱 위에 설치되므로 자료와 설정이 유지됩니다.

---

## 10. 빌드 · 배포 (GitHub Actions)

워크플로: [`.github/workflows/android.yml`](.github/workflows/android.yml)

| 트리거 | 결과 |
|---|---|
| 브랜치 push / PR | 단위 테스트 + 디버그 APK 빌드(검증), Artifacts 에 14일 보관 |
| 태그 `v1.2.3` push | **서명된 Release APK** 빌드 → GitHub **Releases** 게시 (`tv-dashboard-v1.2.3.apk` + `update.json`) |
| Actions 화면 **Run workflow** | 버전 입력 시 서명된 Release APK 빌드(Artifacts), `publish` 체크 시 Releases 게시 |

**버전 규칙**: `versionCode = 주*1,000,000 + 부*1,000 + 수` (예: v1.2.3 → 1002003).
태그 버전을 올리면 versionCode 가 항상 증가하며, 워크플로가 **이전 릴리스보다 낮거나 같은 버전의 게시를 거부**합니다.
패키지명 `com.seyoungjo.tvdashboard` 와 서명 키는 **절대 바꾸지 마세요** (바꾸면 업데이트 불가 → 삭제 후 재설치 = 앱 전용 폴더 자료 삭제).

### 10-1. 최초 1회: 서명 키 · Secrets 설정
1. 서명 키 만들기 (저장소 **밖**의 안전한 PC에서)
   - Windows: `powershell -ExecutionPolicy Bypass -File scripts\create-keystore.ps1`
   - Linux/macOS: `./scripts/create-keystore.sh`
   - 직접: `keytool -genkeypair -keystore release.jks -storetype PKCS12 -alias tvdashboard -keyalg RSA -keysize 4096 -validity 10000`
2. GitHub 저장소 → **Settings → Secrets and variables → Actions → New repository secret**

   | 이름 | 값 |
   |---|---|
   | `ANDROID_KEYSTORE_BASE64` | `release.jks` 를 base64 로 인코딩한 문자열 (스크립트가 만든 `release.jks.b64` 내용) |
   | `ANDROID_KEYSTORE_PASSWORD` | 키스토어 비밀번호 |
   | `ANDROID_KEY_ALIAS` | `tvdashboard` |
   | `ANDROID_KEY_PASSWORD` | 키 비밀번호 (스크립트 사용 시 키스토어 비밀번호와 동일) |
3. `release.jks.b64` 는 삭제, `release.jks` 와 비밀번호는 **사내 금고/백업 매체에 2곳 이상 보관**
   (`.gitignore` 가 `*.jks`, `*.b64` 커밋을 막습니다. 키를 잃으면 기존 설치본 위에 업데이트할 수 없습니다.)

### 10-2. 버전 배포
```bash
# (선택) 변경사항을 TV 업데이트 창에 보여주려면
#   release-notes/v1.0.1.md 작성 (없으면 직전 태그 이후 커밋 제목으로 자동 작성)
git tag v1.0.1
git push origin v1.0.1
```
또는 GitHub → Actions → **Android APK** → **Run workflow** → version `1.0.1`, publish ✔

릴리스마다 두 가지가 함께 만들어집니다.

| 결과물 | 용도 |
|---|---|
| `tv-dashboard-vX.apk` (direct) | 지금처럼 APK 를 직접 설치. 앱 안에서 스스로 업데이트, 공용 폴더 선택 가능 |
| `tv-dashboard-vX-play.aab` (play) | **Google Play** 배포용. Play 정책상 제한 권한(자체 APK 설치 · 모든 파일 접근)을 빼고, 업데이트는 Play 스토어가 맡음 |

- **Google Play 사전 검사** (Actions 가 자동): targetSdk(36) · versionCode · 제한 권한 없음 · 서명 · 디버그 아님 · 포그라운드 서비스 설명 · lint 오류 요약. 하나라도 어긋나면 릴리스가 멈춥니다.
- **Play 자동 업로드**: Secrets 에 `PLAY_SERVICE_ACCOUNT_JSON` 이 있으면 Play Console 의 트랙(기본 **내부 테스트**, 실행 화면에서 선택)에 자동으로 올라갑니다.
  처음 한 번 준비:
  1. Play Console 에서 앱 만들기 (패키지 `com.seyoungjo.tvdashboard`) → 릴리스의 `…-play.aab` 를 **직접 한 번** 내부 테스트에 올림 (Play API 는 첫 업로드를 못 함)
     - 앱 서명: **"내 앱 서명 키 사용"** 을 골라 지금 쓰는 `release.jks` 를 등록하면, 직접 설치한 APK 와 Play 버전이 서로 덮어쓰기 설치됩니다
     - 앱 콘텐츠 → 포그라운드 서비스 권한 신고: '특수 용도 — 매장 디스플레이용 로컬 파일 관리 서버'
  2. Google Cloud 에서 서비스 계정 + JSON 키 만들기 → Play Console › 사용자 및 권한 에서 그 계정을 초대(앱 출시 권한)
  3. GitHub › Settings › Secrets › Actions 에 `PLAY_SERVICE_ACCOUNT_JSON` = JSON 내용 전체
- Play 로 설치한 TV 는 Play Protect 확인이 끝난 앱으로 설치·자동 업데이트됩니다 (직접 설치 APK 는 설치할 때 Play Protect 검사가 뜰 수 있음)

---

## 11. TV에서 앱 업데이트

**방법 A — TV에서 '업데이트 확인' (공개 저장소 기본값)**
1. ⚙ 설정 → **업데이트 확인** → 새 버전이면 버전명·변경사항 표시
2. [다운로드 후 설치] → 다운로드(SHA-256·패키지명·버전 검증) → **Android 설치 화면** → 사용자가 **'업데이트'** 승인
3. 기존 앱 위에 설치되어 자료·설정 유지, 설치 후 서버 자동 재시작

- 업데이트 주소 기본값: `https://github.com/seyoungjo1/tv-dashboard/releases/latest/download/update.json`
- 최초 1회 이 앱에 **'출처를 알 수 없는 앱 설치'** 허용이 필요합니다(설정 화면에 버튼 있음).
- Android 정책상 일반 APK 는 **무인 자동 설치가 불가**합니다. 항상 TV 앞에서 승인해야 합니다.
- 다운로드·검증·설치 중 실패하거나 취소하면 **기존 버전이 그대로 동작**합니다.

**방법 B — 관리 웹에서 APK 업로드 (비공개 저장소·인터넷 차단 환경용)**
- 관리 웹 → [앱 업데이트] → APK 선택 → 업로드 → TV에 설치 확인 창 → 승인
- 저장소를 **비공개로 전환**하면 방법 A의 GitHub 주소에 토큰 없이 접근할 수 없습니다.
  **장기 GitHub 토큰을 APK에 넣지 마세요.** 대신
  ① 방법 B 사용, 또는 ② `update.json` 과 APK 를 사내 웹서버/공개 배포용 저장소 등에 올리고 ⚙ 설정의 **업데이트 주소**를 그 `update.json` 으로 변경하세요.

`update.json` 형식 (Release 에 자동 첨부됨):
```json
{ "versionName": "1.0.1", "versionCode": 1000001,
  "apkUrl": "https://.../tv-dashboard-v1.0.1.apk",
  "sha256": "…", "notes": "- 변경사항" }
```

---

## 12. 대기 화면 (동영상 + 멘트)

- 설정한 시간(기본 300초) 동안 터치·리모컨 입력이 없으면 자료 폴더 **루트의 동영상**을 전체 화면으로 재생하고 **멘트**를 겹쳐 표시합니다.
- 기본 멘트: `화면을 터치하면 대시보드로 들어갑니다`
- 설정(TV ⚙ 또는 관리 웹 > 설정): 사용 켬/끔, 대기 시간(초), 멘트, 멘트 표시 시간/숨김 시간(깜빡임), 동영상 소리
  - 멘트 표시 시간 0 = 계속 표시 / 표시 5·숨김 2 = 5초 보이고 2초 숨김 반복 / 표시 10·숨김 0 = 10초 후 사라짐
- 동영상이 없으면 검은 화면에 멘트만 표시합니다. 터치하거나 아무 키나 누르면 해제됩니다.
- ⚙ 설정 → **대기 화면 미리보기** 로 바로 확인할 수 있습니다.

### 12-1. 화면보호기 (main 폴더)

자료 폴더에 **`main`** 폴더가 있으면 대기 화면이 아래 화면보호기로 바뀝니다. `main` 은 왼쪽 메뉴에 나타나지 않습니다.
다른 폴더와 똑같이 PC 프로그램·자동 업로드 .bat·업로드 도구로 올리면 됩니다.

| main 안의 파일 | 표시 |
|---|---|
| `생산.json` · `sd.json` · `fi.json` · `plan.json` | 매출·생산량. 생성기 형식(`{"2025.01.02\|당류": 값}`)과 표 형식(`{"columns": […], "rows": [{"달력일", "제품계층구조(…)", "수량(KG)" 또는 "매출실적"}]}`) 둘 다 읽음 |
| 동영상·사진 (이름 그대로) | 오른쪽 동영상·사진. 재생 목록(설정.json)의 순서대로, 목록에 없는 것은 그 뒤에 이름순 (`icon`·`logo` 그림, `_` 로 시작하는 파일 제외) |
| `공지.txt` | 왼쪽 위 공지 (한 줄에 하나, 5개까지). 없으면 공지 칸 숨김 |
| `설정.json` | **재생 목록** — 동영상·유튜브 링크의 순서와 영상별 표시 방식 (PC 프로그램에서 설정) |
| `제목.txt` (선택) | 상단 제목 (없으면 `오산공장 스마트 현황판`) |
| `현황판.json` (선택) | 실적 칸 정의 — 어떤 JSON 을 어떤 제목·단위·색·비교로 보여 줄지. 전력량 같은 항목을 **앱 업데이트 없이** 추가·변경 (아래 예시) |

`현황판.json` 예시 (없으면 매출 · 생산량 2개, 최대 4개):

```json
{ "panels": [
  { "title": "매출",   "file": "sd.json",   "unit": "억원", "divide": 100000, "decimals": 1, "color": "#f2801f",
    "compare": "plan", "plan": "plan.json", "planDivide": 1000, "adjust": "fi.json", "exclude": ["면류"] },
  { "title": "생산량", "file": "생산.json", "unit": "톤",   "divide": 1000,   "decimals": 0, "color": "#2f7be6", "compare": "prev", "exclude": ["면류"] },
  { "title": "전력량", "file": "전력.json", "unit": "MWh",  "divide": 1000,   "decimals": 1, "color": "#2fb36a", "compare": "prev", "value": "사용량" }
] }
```

- `file`: 일별 표 JSON (날짜 칸 · 구분 칸 · 숫자 칸을 값 모양으로 찾음. 생성기 형식 `{"2025.01.02|구분": 값}` 도 됨) · `value`: 숫자 칸이 여럿이면 이름으로 고르는 정규식
- `divide` · `decimals` · `unit`: 표시 단위 (값 ÷ divide, 소수 자리) · `color`: 그래프·배지 색
- `compare`: `prev` = 전년 같은 기간 대비 % · `plan` = 월 계획(`plan`, 원 단위면 `planDivide`) 대비 달성율 (당월은 경과일 일할) · `none` = 배지 없음 · `badge`: 배지 글자 바꾸기
- `exclude`: 제외할 구분 · `adjust`: fi.json 식 보정 비율 (매출만)


- 매출 = SD × 환산비율(그 달 FI÷SD, 없으면 전년 동월, 둘 다 없으면 1), 면류 제외 — 생성기와 같은 계산. 단위 **억원**
- 생산량 = KG ÷ 1,000 = **톤**
- 당월 = 기준일까지 누적, 누계 = 1월~전월 + 당월. 기준일 = 최신 데이터의 달(이번 달이면 어제, 지난 달이면 말일)
- 배지: 매출 **목표** = 계획(plan) 대비 달성율(당월은 경과일 일할) / 생산량 **전년비** = 전년 같은 기간 대비
- 그래프: 그 해 1~12월 월별 (당월은 기준일까지)
- 영상마다 **크롭**(칸을 꽉 채우고 긴 쪽을 자름 — 위쪽·가운데·아래쪽 맞춤) 또는 **확장**(작은 쪽을 맞춰 전체가 보임 — 남는 곳은 블러 또는 단색)
  또는 **직접 조절**: 100% 기준(크롭 크기 / 확장 크기)을 고르고 크기(%), 가로 기준(왼쪽·가운데·오른쪽)+px, 세로 기준(위쪽·가운데·아래쪽)+px.
  넘친 곳은 잘리고 남는 곳은 블러/단색. px 는 1080p 화면 기준, 음수 가능
- **유튜브 링크**(쇼츠 포함)도 재생 목록에 넣을 수 있습니다. 공식 플레이어로 소리 없이 재생하며, TV 가 인터넷에 연결돼 있어야 하고 퍼가기가 막힌 영상은 건너뜁니다
- **사진**(jpg · png · webp · gif)도 재생 목록에 넣을 수 있습니다. 사진마다 보여 줄 시간(초, 기본 8)과 전환 효과
  **모핑 · 쉐이딩 · 닦아내기 · 원형 · 블라인드 · 랜덤** 을 PC 프로그램에서 정합니다. 동영상 → 사진은 동영상의 마지막 장면에서 사진으로 전환됩니다
- **공지 바로 고치기**: 공지 줄 맨 오른쪽의 반투명 **수정 아이콘**(공지가 없으면 매출 카드 왼쪽 위) → 위쪽 팝업의 숫자패드(3×4)로 **공지 수정 비밀번호 6자리**(TV ⚙ 설정 또는 PC 의 TV 설정에서 정함)
  → 공지 입력란 + 화면 키보드로 고치고 [저장]. 아이콘·팝업은 눌러도 대시보드로 넘어가지 않고, 리모컨 뒤로 = 취소. 5번 틀리면 1분 잠김
- 멘트(`화면을 터치하면 대시보드로 들어갑니다`)는 화면 맨 아래에 표시됩니다
- PC 프로그램: `main` 폴더를 고르면 **[화면보호기 설정]**(공지 · 크롭/맞춤)과 **[공지사항 편집 HTML 받기]**
  (비밀번호로 잠근, 공지만 조회·수정할 수 있는 HTML — 담당자에게 나눠 줄 수 있음)

---

## 13. 소스 구조

```
app/src/main/java/com/seyoungjo/tvdashboard/
  App.kt                       초기화
  BootReceiver.kt              재부팅/업데이트 후 자동 실행
  data/  PathGuard.kt          자료 폴더 밖 접근 차단
         MenuScanner.kt        메뉴 규칙(버튼·대표 이미지·정렬), 루트 동영상
         ContentStore.kt       저장 위치(앱 전용/공용), WebView 주소
         AppSettings.kt        설정값
         ChangeBus.kt          업로드 → 화면 갱신 이벤트
  server/ AdminServer.kt       내장 웹서버(NanoHTTPD) + 파일 관리 API
         ServerService.kt      포그라운드 서비스, WakeLock/WifiLock
         Auth.kt               관리자 비밀번호·세션·API 토큰
  update/ UpdateManager.kt     update.json 확인·다운로드·검증·PackageInstaller
  ui/    MainActivity.kt       좌측 메뉴 + 우측 WebView + 대기 화면
         DataPathHandler.kt    WebView ↔ 자료 폴더 연결(https 가상 주소)
         SettingsActivity.kt   TV 설정 화면
app/src/main/assets/admin/index.html   관리 웹 페이지
app/src/main/assets/sample/            '예제 대시보드 만들기'에 쓰는 vDesk 스타일 예제
app/.../relay/                         원격 중계 (GitHub 경유, 암호화) — TV 쪽
pc/                                    원격 관리 PC 프로그램 (Python + 브라우저 화면, tvrun.bat)
sample/자료/                           예제 자료 (폴더째 업로드 가능)
scripts/                               서명 키 생성, JSON 자동 업로드 예시
```

로컬 빌드: JDK 17 + Android SDK(34) 설치 후 `./gradlew assembleDebug` (Android Studio 로 열어도 됩니다)
