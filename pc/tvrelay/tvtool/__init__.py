"""직원용 업로드 앱 (내장 Python 으로 도는 쪽) — 관리자 PC 프로그램이 폴더마다 zip 으로 구워 나눠 준다.

  "<폴더> 업로드.exe"  (tools/tvtool, Go)  ─ 검은 창 없이 이 Python(pythonw)을 띄우고, Tailscale 을 설치 없이 품고 있다
        └ app/python/pythonw.exe -m tvtool --app app   ← 여기
              · 127.0.0.1 에 화면 서버 (app/tool.html = 비밀번호로 잠긴 직원 화면)
              · 화면이 만든 암호화 꾸러미를 TV 로 전달: Tailscale(TV 100.x:8080/api/pkg) → 안 되면 블루투스(COM 포트)
              · Edge 앱 창(주소창 없는 창)을 띄우고, 창을 닫으면 끝난다 → exe 와 Tailscale 도 함께 끝난다

열쇠(폴더 키 · Tailscale 인증 키)는 이 Python 이 모른다 — 화면이 업로드 비밀번호로 잠금을 푼 뒤 Tailscale 인증 키만 넘겨준다.
꾸러미는 화면이 이미 폴더 키로 암호화했고, 이 Python 은 그대로 나르기만 한다.
"""
