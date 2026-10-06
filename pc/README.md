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

## 처음 한 번 설정 (TV 에서는 할 것이 없습니다)

1. **중계 레포 만들기** — GitHub 에서 New repository → 이름 `tv-dashboard-relay`, **Public**, **Add a README file** 체크 → Create
2. **토큰 만들기** — https://github.com/settings/personal-access-tokens/new
   (프로필 사진 → Settings → 왼쪽 맨 아래 Developer settings → Personal access tokens → Fine-grained tokens)
   - Repository access: **Only select repositories** → `tv-dashboard-relay`
   - Permissions → Repository permissions → **Contents: Read and write**
3. **PC** — Python 3.9 이상 설치("Add python.exe to PATH" 체크) → 이 폴더의 `tvrun.bat` 실행 → 화면의 [1. GitHub 토큰]에 붙여넣기 → 저장
   (암호키는 자동으로 만들어져 `tvrelay.json` 에 저장됩니다. 설치할 라이브러리도 없습니다 — Windows 내장 암호화 사용)
4. **TV 연결** — TV 앱 화면(자료가 없을 때 안내 화면) 또는 TV ⚙ 설정 → 원격 중계 → **연결 코드**(예: `K7QM-4PXD`)를 보고
   PC 화면의 [2. TV 연결]에 입력 → 15초쯤 뒤 "TV 연결 완료"
   - PC 는 연결 정보(레포·암호키·토큰)를 **그 코드로 암호화**해 레포에 잠깐 올리고, TV 가 토큰 없이 읽어 가져간 뒤 바로 지웁니다.
   - 코드를 모르면 풀 수 없습니다. 다시 연결하려면 TV ⚙ 설정 → **원격 연결 초기화** 후 새 코드로 연결하세요.

> `tvrelay.json` 에는 암호키와 토큰이 들어 있습니다. 이 파일을 가진 사람은 TV 를 관리할 수 있으니 공유하지 마세요.

## 사용

- **tvrun.bat** — 화면 열기. 실행할 때마다 프로그램을 자동으로 최신 버전으로 업데이트합니다.
  - 화면이 켜져 있는 동안에는 오른쪽 위 **[프로그램 업데이트]** 를 누르면 새 버전을 받고, 검은 창을 끄지 않아도 화면이
    새 버전으로 저절로 다시 시작·새로고침됩니다 (s4bridge 와 같은 방식: 검은 창이 감시자, 화면은 그 자식).
  - 업데이트는 레포의 커밋을 고정해서 받고, 받기 전에 `backup/<시각>/` 에 백업하며, 실패하면 기존 버전을 그대로 씁니다.
  - **파일 탐색기**: 왼쪽 = TV 폴더 트리(☰ 로 숨기기/열기). PC 탐색기에서 파일·폴더를 **폴더 위에 끌어다 놓으면** 그 폴더로 올라갑니다.
    오른쪽 = **미리보기** — 폴더를 고르면 그 폴더의 index.html 을 TV 와 똑같이 띄우고, 이미지·동영상·JSON·텍스트도 바로 봅니다
    (TV 에서 받아 오는 데 10~20초, 방금 올린 파일은 즉시). 폴더 만들기·이름 변경·삭제·교체·다운로드·예제 대시보드 만들기
  - TV 설정: 상단 제목, 대기 화면(멘트·시간·소리), 자동 새로고침, PIN 등
  - 앱 업데이트: 서명된 APK 를 보내면 TV 화면에 설치 확인 창 → TV 앞에서 승인
- **tvupload.bat** — 작업 스케줄러용 무인 업로드
  ```
  tvupload.bat C:\data\생산팀\data.json 01_생산팀/data.json
  ```
  TV 에 반영되면 종료 코드 0, 기록은 `out\upload.log`. (TV 가 꺼져 있으면 3분 기다린 뒤 코드 3 — 작업은 TV 가 켜지면 처리됩니다)
- 명령줄: `python -m tvrelay status` (TV 상태), `python -m tvrelay put <PC 파일> <TV 경로>`, `python -m tvrelay pair <연결 코드>`

## 폴더 안의 파일

| 파일 | 설명 |
|---|---|
| `tvrun.bat`, `tvupload.bat` | 실행 파일 (ASCII 전용 — 한글을 넣지 마세요) |
| `tvrelay/` | 프로그램 (자동 업데이트로 교체됨) |
| `tvrelay.json` | **내 설정·암호키·토큰** (업데이트해도 그대로, 백업 권장) |
| `venv/` · `out/` · `backup/` · `downloads/` | 자동 생성 (가상환경 · 기록·미리보기 · 업데이트 전 백업 · TV 에서 내려받은 파일) |
| `tvrelay/requirements.txt` | 필요한 라이브러리 목록 — 프로그램이 실행할 때 확인·설치 (Windows 는 회사망용 truststore 하나, 휠만 설치) |
