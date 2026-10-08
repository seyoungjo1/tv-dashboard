# tv-dashboard 작업 규칙

## 버전
- PC 프로그램(`pc/tvrelay/VERSION`)은 안드로이드 앱 버전과 **같이** 간다. 안드로이드를 1.6.0 으로 배포하면 PC 도 1.6.0.
- 안드로이드는 그대로이고 PC 만 고쳐서 내보낼 때는 `<안드로이드 버전>_p<번호>` — 예: 1.6.0 → 1.6.0_p1 → 1.6.0_p2.
  다음 안드로이드 배포(예: 1.7.0) 때 PC 도 다시 1.7.0 으로 맞춘다.
- 안드로이드 배포: Actions `android.yml` workflow_dispatch (version=X.Y.Z, publish=true, unsigned_build=false).
  versionCode 는 버전에서 자동 계산되므로 항상 올라가는 버전을 쓴다.

## 화면보호기
- `app/src/main/assets/screensaver/` 가 원본이고, PC 미리보기용 사본이 `pc/tvrelay/screensaver/` 에 있다 (폰트 제외).
  원본을 고치면 사본도 같이 복사한다 — `pc/tests` 가 두 사본이 같은지 검사한다.
- **화면보호기 페이지(index.html · ss.js · ss.css · 그림)만 고친 변경은 APK 를 만들지 않는다.** PC 버전만 `_pN` 으로 올리고,
  PC 프로그램의 [화면보호기 설정] → [화면보호기 화면 TV 로 보내기]로 배포한다 (TV 의 `_screensaver/` 폴더, 있으면 내장 페이지 대신 씀).
  안드로이드(Kotlin · 레이아웃 · 설정 키) 변경이 있을 때만 APK 버전을 올린다.

## 보안
- 서명 키·비밀번호는 GitHub Secrets 에만. `tvrelay.json`·`grants.json` 은 커밋하지 않는다.
