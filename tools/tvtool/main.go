// tvtool — 직원용 업로드 앱의 실행 파일 (Windows, 검은 창 없음).
//
//   직원 zip:  "<폴더> 업로드.exe" (이 프로그램)  +  app\python\pythonw.exe (내장 Python)  +  app\tvtool\ (화면 서버)  +  app\tool.html
//
// 하는 일
//  1. 127.0.0.1 의 임시 포트에 제어 서버를 열고(무작위 토큰), 내장 Python(pythonw, 창 없음)을 띄운다.
//     Python 이 화면(Edge 앱 창)을 띄우고, 창이 닫히면 Python 이 끝난다 → 이 프로그램도 끝난다 (Tailscale 도 같이 내려감).
//  2. Tailscale 을 설치 없이 이 프로그램 안에서만 켠다 (tsnet, 사용자 공간 — 관리자 권한 · VPN 어댑터 없음).
//     인증 키는 직원이 업로드 비밀번호로 화면의 잠금을 푼 뒤에야 Python 을 거쳐 넘어온다 (/ts/start).
//     기기는 임시(ephemeral)로 들어가 앱을 끄면 Tailscale 관리 화면에서 저절로 사라진다.
//  3. Python 이 TV 로 보내는 암호화 꾸러미를 Tailscale 망 안의 TV(100.x:8080/api/pkg)로 넘겨 준다 (/ts/fwd).
//
// 제어 서버 (헤더 X-Tvtool-Token 필수)
//   POST /ts/start   {"authKey","hostname"}          → {"ok","state","ips"}
//   GET  /ts/status                                   → {"state","ips","error"}
//   POST /ts/fwd?to=100.x.y.z:8080&path=/api/pkg     본문 그대로 넘기고 TV 응답을 그대로 돌려준다
package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"tailscale.com/tsnet"
)

var (
	mu      sync.Mutex
	ts      *tsnet.Server
	tsState = "off"
	tsErr   = ""
	tsIPs   []string
	token   string
	logf    = log.Printf
)

func main() {
	exe, _ := os.Executable()
	base := filepath.Dir(exe)
	app := filepath.Join(base, "app")
	data := filepath.Join(userDir(), "tvtool")
	_ = os.MkdirAll(data, 0o700)
	if f, err := os.OpenFile(filepath.Join(data, "tvtool.log"), os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600); err == nil {
		log.SetOutput(f)
		defer f.Close()
	}
	b := make([]byte, 16)
	_, _ = rand.Read(b)
	token = hex.EncodeToString(b)

	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		fatal("제어 포트를 열 수 없습니다: " + err.Error())
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/ts/start", auth(start))
	mux.HandleFunc("/ts/status", auth(status))
	mux.HandleFunc("/ts/fwd", auth(fwd))
	go func() { _ = http.Serve(ln, mux) }()

	py := filepath.Join(app, "python", pythonName())
	if _, err := os.Stat(py); err != nil {
		fatal("내장 Python 이 없습니다: " + py + "\nzip 을 통째로 풀었는지 확인하세요.")
	}
	cmd := exec.Command(py, "-m", "tvtool", "--app", app)
	cmd.Dir = app
	cmd.Env = append(os.Environ(),
		"TVTOOL_HELPER=http://"+ln.Addr().String(),
		"TVTOOL_TOKEN="+token,
		"TVTOOL_DATA="+data,
		"PYTHONPATH="+app,
		"PYTHONIOENCODING=utf-8",
	)
	hideWindow(cmd)
	if err := cmd.Start(); err != nil {
		fatal("Python 을 시작하지 못했습니다: " + err.Error())
	}
	err = cmd.Wait() // 화면 창이 닫히면 Python 이 끝난다 → 여기서 함께 끝
	logf("python exited: %v", err)
	mu.Lock()
	if ts != nil {
		_ = ts.Close()
	}
	mu.Unlock()
	if err != nil {
		if ee, ok := err.(*exec.ExitError); ok && ee.ExitCode() == 3 {
			fatal("화면을 띄우지 못했습니다. 기록: " + filepath.Join(data, "tvtool.log"))
		}
	}
}

func auth(h http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Tvtool-Token") != token {
			http.Error(w, "forbidden", http.StatusForbidden)
			return
		}
		h(w, r)
	}
}

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	_ = json.NewEncoder(w).Encode(v)
}

func start(w http.ResponseWriter, r *http.Request) {
	var req struct {
		AuthKey  string `json:"authKey"`
		Hostname string `json:"hostname"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.AuthKey == "" {
		http.Error(w, "authKey 가 필요합니다", http.StatusBadRequest)
		return
	}
	mu.Lock()
	if ts == nil {
		host := req.Hostname
		if host == "" {
			host = "tvtool"
		}
		ts = &tsnet.Server{
			Dir:       filepath.Join(userDir(), "tvtool", "ts-"+safe(host)),
			Hostname:  host,
			AuthKey:   req.AuthKey,
			Ephemeral: true,
			Logf:      func(string, ...any) {},
			UserLogf:  logf,
		}
		tsState = "starting"
		srv := ts
		go func() {
			ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
			defer cancel()
			st, err := srv.Up(ctx)
			mu.Lock()
			defer mu.Unlock()
			if err != nil {
				tsState, tsErr = "error", err.Error()
				return
			}
			tsState, tsErr = "up", ""
			tsIPs = nil
			for _, ip := range st.TailscaleIPs {
				tsIPs = append(tsIPs, ip.String())
			}
		}()
	}
	out := map[string]any{"ok": true, "state": tsState, "ips": tsIPs, "error": tsErr}
	mu.Unlock()
	writeJSON(w, out)
}

func status(w http.ResponseWriter, r *http.Request) {
	mu.Lock()
	out := map[string]any{"state": tsState, "ips": tsIPs, "error": tsErr}
	mu.Unlock()
	writeJSON(w, out)
}

func fwd(w http.ResponseWriter, r *http.Request) {
	mu.Lock()
	srv, state := ts, tsState
	mu.Unlock()
	if srv == nil || state != "up" {
		http.Error(w, "Tailscale 이 아직 켜지지 않았습니다 ("+state+")", http.StatusServiceUnavailable)
		return
	}
	to := r.URL.Query().Get("to")
	path := r.URL.Query().Get("path")
	host, _, err := net.SplitHostPort(to)
	if err != nil || !strings.HasPrefix(host, "100.") || !strings.HasPrefix(path, "/api/") {
		http.Error(w, "잘못된 대상", http.StatusBadRequest) // Tailscale 주소의 TV API 로만
		return
	}
	body, err := io.ReadAll(io.LimitReader(r.Body, 70<<20))
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	client := srv.HTTPClient()
	client.Timeout = 15 * time.Minute
	req, _ := http.NewRequest(http.MethodPost, "http://"+to+path, strings.NewReader(string(body)))
	req.Header.Set("Content-Type", "application/octet-stream")
	resp, err := client.Do(req)
	if err != nil {
		http.Error(w, "TV 에 닿지 않습니다: "+err.Error(), http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()
	w.Header().Set("Content-Type", resp.Header.Get("Content-Type"))
	w.WriteHeader(resp.StatusCode)
	_, _ = io.Copy(w, resp.Body)
}

func safe(s string) string {
	var b strings.Builder
	for _, c := range s {
		if c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '-' {
			b.WriteRune(c)
		}
	}
	if b.Len() == 0 {
		return "tvtool"
	}
	return b.String()
}

func userDir() string {
	if d := os.Getenv("LOCALAPPDATA"); d != "" {
		return d
	}
	if d, err := os.UserCacheDir(); err == nil {
		return d
	}
	return os.TempDir()
}

func fatal(msg string) {
	logf("fatal: %s", msg)
	showError(msg)
	os.Exit(1)
}

var _ = fmt.Sprintf
