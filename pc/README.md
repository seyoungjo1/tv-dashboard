# TV 대시보드 원격 관리 (PC 프로그램)

다른 공유기·다른 망에 있는 PC 에서 TV(대상 오산공장 Dashboard 앱)에 폴더·파일·설정·앱 업데이트를 보냅니다.
Tailscale 같은 별도 앱 없이, **GitHub 공개 레포를 우체통으로만** 씁니다.

```
PC (tvrun.bat → 브라우저 화면)  ──암호화된 작업──▶  GitHub 중계 레포  ◀── TV 앱이 10초마다 확인해서 가져감
                                                   (TV 가 가져가면 즉시 삭제)        자료는 TV 에만 저장
```

- 모든 내용(파일·파일명·설정·목록)은 **AES-256-GCM 으로 암호화**되어 지나갑니다. 공개 레포여도 내용은 보이지 않습니다.
- 암호키는 처음 설정할 때 **자동으로 만들어져 이 폴더의 `tvrelay.json` 에만** 저장됩니다(레포에 올라가지 않음).
- 반영까지 TV 확인 주기(기본 10초)만큼 걸립니다. TV 가 꺼져 있으면 켜졌을 때 처리됩니다.

## 처음 한 번 설정

1. **중계 레포 만들기** — GitHub 에서 New repository → 이름 `tv-dashboard-relay`, **Public**, **Add a README file** 체크 → Create
2. **토큰 만들기** — GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token
   - Repository access: **Only select repositories** → `tv-dashboard-relay`
   - Permissions → Repository permissions → **Contents: Read and write**
   - 만료일은 회사 정책에 맞게(만료되면 새 토큰으로 다시 설정)
3. **PC** — Python 3.9 이상 설치(설치 시 "Add python.exe to PATH" 체크) → 이 폴더의 `tvrun.bat` 실행
   → 브라우저의 [처음 설정]에 토큰 붙여넣기 → 저장 → 폴더에 `tvrelay.json` 생성
4. **TV** — `tvrelay.json` 을 USB 로 옮겨 TV 의 ⚙ 설정 → **원격 중계** → **중계 설정 파일(tvrelay.json) 불러오기**
   (같은 망이면 TV 관리 웹 `http://<TV주소>:8080` → 설정 → 원격 중계 → 불러오기 도 가능)
5. PC 화면 위쪽에 **TV 온라인** 이 표시되면 끝입니다.

> `tvrelay.json` 에는 암호키와 토큰이 들어 있습니다. 이 파일을 가진 사람은 TV 를 관리할 수 있으니 메일·메신저로 보내지 말고 USB 로만 옮기세요.
> 유출이 의심되면: GitHub 에서 토큰 삭제 → `tvrelay.json` 삭제 후 [처음 설정]을 다시 하고 → TV 에 새 파일을 다시 불러옵니다.

## 사용

- **tvrun.bat** — 화면 열기. 실행할 때마다 프로그램을 자동으로 최신 버전으로 업데이트합니다.
  - 파일 관리: 폴더 만들기·이름 변경·삭제, 파일 업로드(여러 개·폴더째·끌어다 놓기)·교체·다운로드, 예제 대시보드 만들기
  - TV 설정: 상단 제목, 대기 화면(멘트·시간·소리), 자동 새로고침, PIN 등
  - 앱 업데이트: 서명된 APK 를 보내면 TV 화면에 설치 확인 창 → TV 앞에서 승인
- **tvupload.bat** — 작업 스케줄러용 무인 업로드
  ```
  tvupload.bat C:\data\생산팀\data.json 01_생산팀/data.json
  ```
  TV 에 반영되면 종료 코드 0, 기록은 `out\upload.log`. (TV 가 꺼져 있으면 3분 기다린 뒤 코드 3 — 작업은 TV 가 켜지면 처리됩니다)
- 명령줄: `python -m tvrelay status` (TV 상태), `python -m tvrelay put <PC 파일> <TV 경로>`

## 폴더 안의 파일

| 파일 | 설명 |
|---|---|
| `tvrun.bat`, `tvupload.bat` | 실행 파일 (ASCII 전용 — 한글을 넣지 마세요) |
| `tvrelay/` | 프로그램 (자동 업데이트로 교체됨) |
| `tvrelay.json` | **내 설정·암호키·토큰** (업데이트해도 그대로, 백업 권장) |
| `venv/` · `out/` · `backup/` · `downloads/` | 자동 생성 (가상환경 · 기록 · 업데이트 전 백업 · TV 에서 내려받은 파일) |
