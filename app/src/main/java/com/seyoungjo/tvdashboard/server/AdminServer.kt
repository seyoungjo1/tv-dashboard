package com.seyoungjo.tvdashboard.server

import android.content.Context
import android.util.Log
import com.seyoungjo.tvdashboard.data.AppEvent
import com.seyoungjo.tvdashboard.data.AppSettings
import com.seyoungjo.tvdashboard.data.ChangeBus
import com.seyoungjo.tvdashboard.data.ContentStore
import com.seyoungjo.tvdashboard.data.FileOps
import com.seyoungjo.tvdashboard.data.PathGuard
import com.seyoungjo.tvdashboard.relay.RelaySettings
import com.seyoungjo.tvdashboard.relay.RelayWorker
import com.seyoungjo.tvdashboard.update.UpdateManager
import fi.iki.elonen.NanoHTTPD
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileInputStream
import java.net.URLEncoder
import java.util.UUID

/**
 * TV 안에서 동작하는 파일 관리 웹서버.
 *   GET  /                  관리 웹 페이지
 *   POST /api/login         {"password"} → {"token"}
 *   그 외 /api/...          Authorization: Bearer <세션 토큰 또는 API 토큰>
 * 모든 경로는 자료 폴더 안으로 제한됩니다.
 */
class AdminServer(private val ctx: Context, port: Int) : NanoHTTPD(port) {

    private val ops = FileOps(ctx)

    private class HttpError(val status: Int, message: String) : Exception(message)

    private class St(private val code: Int, private val text: String) : Response.IStatus {
        override fun getDescription() = "$code $text"
        override fun getRequestStatus() = code
    }

    private enum class Role { NONE, API, ADMIN }

    private val bodyRead = ThreadLocal<Boolean>()

    override fun serve(session: IHTTPSession): Response {
        bodyRead.set(false)
        val ip = session.remoteIpAddress ?: ""
        val resp = try {
            if (AppSettings.tailscaleOnly && !NetInfo.isTailscale(ip) && !NetInfo.isLoopback(ip)) {
                throw HttpError(403, "Tailscale 주소에서만 접속할 수 있도록 설정되어 있습니다.")
            }
            route(session, ip)
        } catch (e: HttpError) {
            errorResponse(e.status, e.message ?: "")
        } catch (e: FileOps.OpError) {
            errorResponse(e.status, e.message ?: "")
        } catch (e: PathGuard.InvalidPathException) {
            errorResponse(400, e.message ?: "잘못된 경로")
        } catch (e: IllegalArgumentException) {
            errorResponse(400, e.message ?: "잘못된 요청")
        } catch (e: Exception) {
            Log.e(TAG, "request failed", e)
            errorResponse(500, "서버 오류: ${e.javaClass.simpleName} ${e.message ?: ""}")
        }
        // 본문을 읽지 않고 응답하면 같은 연결의 다음 요청이 깨지므로 연결을 닫습니다.
        val len = session.headers["content-length"]?.toLongOrNull() ?: 0
        if (len > 0 && bodyRead.get() != true) resp.addHeader("Connection", "close")
        resp.addHeader("Cache-Control", "no-store")
        resp.addHeader("X-Content-Type-Options", "nosniff")
        return resp
    }

    private fun route(s: IHTTPSession, ip: String): Response {
        val uri = s.uri ?: "/"
        val m = s.method
        if (!uri.startsWith("/api/")) {
            if (m != Method.GET && m != Method.HEAD) throw HttpError(405, "허용되지 않는 메서드")
            return when (uri) {
                "/", "/index.html" -> asset("admin/index.html", "text/html; charset=utf-8")
                "/fonts/Pretendard-SemiBold.woff2", "/fonts/Pretendard-Bold.woff2", "/fonts/Pretendard-ExtraBold.woff2" ->
                    asset(uri.removePrefix("/"), "font/woff2")
                else -> throw HttpError(404, "Not Found")
            }
        }
        if (uri == "/api/login" && m == Method.POST) return login(s, ip)
        if (uri == "/api/ping") return json(JSONObject().put("ok", true).put("app", "tv-dashboard"))

        val role = authenticate(s)
        if (role == Role.NONE) throw HttpError(401, "로그인이 필요합니다.")

        return when (uri to m) {
            "/api/logout" to Method.POST -> { bearer(s)?.let { Auth.endSession(it) }; ok() }
            "/api/status" to Method.GET -> status()
            "/api/menu" to Method.GET -> menu()
            "/api/list" to Method.GET -> list(param(s, "path"))
            "/api/file" to Method.GET -> download(param(s, "path"))
            "/api/file" to Method.HEAD -> download(param(s, "path"))
            "/api/file" to Method.PUT -> upload(s, param(s, "path"), param(s, "overwrite") != "0")
            "/api/file" to Method.POST -> upload(s, param(s, "path"), param(s, "overwrite") != "0")
            "/api/file" to Method.DELETE -> delete(param(s, "path"), param(s, "recursive") == "1")
            "/api/mkdir" to Method.POST -> mkdir(param(s, "path"))
            "/api/sample" to Method.POST -> sample(param(s, "path"))
            "/api/rename" to Method.POST -> rename(param(s, "path"), param(s, "to"))
            "/api/reload" to Method.POST -> { ChangeBus.post(AppEvent.Reload); ok() }
            "/api/settings" to Method.GET -> getSettings()
            "/api/settings" to Method.PUT -> putSettings(readJson(s))
            "/api/settings" to Method.POST -> putSettings(readJson(s))
            "/api/update/apk" to Method.PUT -> uploadApk(s)
            "/api/update/apk" to Method.POST -> uploadApk(s)
            // 아래는 관리자 로그인 세션 전용 (API 토큰으로는 불가)
            "/api/password" to Method.POST -> adminOnly(role) { changePassword(readJson(s)) }
            "/api/token" to Method.GET -> adminOnly(role) { json(JSONObject().put("token", Auth.apiToken)) }
            "/api/relay" to Method.GET -> adminOnly(role) { getRelay() }
            "/api/relay" to Method.PUT -> adminOnly(role) { putRelay(readJson(s)) }
            "/api/relay" to Method.POST -> adminOnly(role) { putRelay(readJson(s)) }
            "/api/token/regenerate" to Method.POST -> adminOnly(role) {
                json(JSONObject().put("token", Auth.regenerateApiToken()))
            }
            else -> throw HttpError(404, "알 수 없는 API: ${m.name} $uri")
        }
    }

    private inline fun adminOnly(role: Role, block: () -> Response): Response {
        if (role != Role.ADMIN) throw HttpError(403, "관리자 로그인으로만 사용할 수 있습니다.")
        return block()
    }

    // ── 인증 ──────────────────────────────────────────────────────────────
    private fun bearer(s: IHTTPSession): String? {
        val h = s.headers["authorization"]
        if (h != null && h.startsWith("Bearer ", ignoreCase = true)) return h.substring(7).trim()
        return s.headers["x-api-key"]?.trim()
    }

    private fun authenticate(s: IHTTPSession): Role {
        val t = bearer(s) ?: return Role.NONE
        if (t.isEmpty()) return Role.NONE
        if (Auth.isSession(t)) return Role.ADMIN
        if (Auth.isApiToken(t)) return Role.API
        return Role.NONE
    }

    private fun login(s: IHTTPSession, ip: String): Response {
        val locked = Auth.lockedSeconds(ip)
        if (locked > 0) throw HttpError(429, "로그인 실패가 많습니다. ${locked}초 후 다시 시도하세요.")
        val body = readJson(s)
        val pw = body.optString("password", "")
        if (!Auth.verifyPassword(pw)) {
            Auth.recordFailure(ip)
            throw HttpError(401, "비밀번호가 올바르지 않습니다.")
        }
        Auth.recordSuccess(ip)
        return json(
            JSONObject().put("token", Auth.newSession())
                .put("mustChange", Auth.initialPassword != null)
        )
    }

    private fun changePassword(body: JSONObject): Response {
        if (!Auth.verifyPassword(body.optString("current", ""))) throw HttpError(400, "현재 비밀번호가 올바르지 않습니다.")
        Auth.changePassword(body.optString("new", ""))
        return ok()
    }

    // ── 조회 · 변경 (실제 작업은 FileOps — 원격 중계와 같은 코드) ─────────────
    private fun status(): Response = json(ops.status())

    private fun menu(): Response = json(ops.menu())

    private fun list(path: String?): Response = json(ops.list(path))

    private fun download(path: String?): Response {
        val f = ops.file(path)
        val r = newFixedLengthResponse(St(200, "OK"), Mime.of(f.name), FileInputStream(f), f.length())
        val enc = URLEncoder.encode(f.name, "UTF-8").replace("+", "%20")
        r.addHeader("Content-Disposition", "attachment; filename*=UTF-8''$enc")
        return r
    }

    /**
     * 업로드: 본문을 .tmp 폴더에 먼저 저장 → 디스크 동기화 → 원자적 이동(rename)으로 교체.
     * 화면(WebView)은 항상 '이전 완성본' 또는 '새 완성본'만 읽게 됩니다.
     */
    private fun upload(s: IHTTPSession, path: String?, overwrite: Boolean): Response {
        val length = contentLength(s)
        ops.checkPut(path, overwrite, length)       // 본문을 읽기 전에 거절할 것은 먼저 거절
        bodyRead.set(true)
        val rel = ops.put(path, length, s.inputStream, overwrite)
        Log.i(TAG, "uploaded $rel ($length bytes)")
        return json(JSONObject().put("ok", true).put("path", rel).put("size", length))
    }

    private fun mkdir(path: String?): Response = json(JSONObject().put("ok", true).put("path", ops.mkdir(path)))

    private fun sample(path: String?): Response = json(JSONObject().put("ok", true).put("path", ops.sample(path)))

    private fun rename(path: String?, to: String?): Response =
        json(JSONObject().put("ok", true).put("path", ops.rename(path, to)))

    private fun delete(path: String?, recursive: Boolean): Response {
        ops.delete(path, recursive)
        return ok()
    }

    // ── 설정 ──────────────────────────────────────────────────────────────
    private fun getSettings(): Response = json(AppSettings.remoteJson())

    private fun putSettings(body: JSONObject): Response {
        AppSettings.applyRemote(body)
        return getSettings()
    }

    /** 원격 중계 설정 (관리자 로그인 전용). 토큰·키는 돌려주지 않는다. */
    private fun getRelay(): Response = json(RelaySettings.publicJson())

    private fun putRelay(body: JSONObject): Response {
        RelaySettings.apply(body)
        RelayWorker.kick()
        return getRelay()
    }

    // ── 앱 업데이트 APK 업로드 ─────────────────────────────────────────────
    private fun uploadApk(s: IHTTPSession): Response {
        val length = contentLength(s)
        ops.ensureSpace(UpdateManager.updateDir(ctx), length)
        val tmp = File(UpdateManager.updateDir(ctx), "upload-" + UUID.randomUUID() + ".part")
        try {
            bodyRead.set(true)
            FileOps.receive(s.inputStream, length, tmp)
            val meta = ops.acceptApk(tmp)
            return json(
                JSONObject().put("ok", true).put("versionName", meta.versionName)
                    .put("versionCode", meta.versionCode)
                    .put("message", "TV 화면에 설치 확인 창이 표시됩니다. TV 에서 '설치'를 눌러야 업데이트됩니다.")
            )
        } finally {
            if (tmp.exists()) tmp.delete()
        }
    }

    // ── 도우미 ────────────────────────────────────────────────────────────
    private fun param(s: IHTTPSession, name: String): String? = s.parameters[name]?.firstOrNull()

    private fun contentLength(s: IHTTPSession): Long {
        val len = s.headers["content-length"]?.toLongOrNull()
            ?: throw HttpError(411, "Content-Length 헤더가 필요합니다.")
        if (len < 0) throw HttpError(400, "잘못된 Content-Length")
        return len
    }

    private fun readJson(s: IHTTPSession): JSONObject {
        val len = s.headers["content-length"]?.toLongOrNull() ?: 0
        if (len > 1024 * 1024) throw HttpError(413, "요청이 너무 큽니다.")
        if (len <= 0) return JSONObject()
        bodyRead.set(true)
        val out = ByteArrayOutputStream()
        val buf = ByteArray(8192)
        var remaining = len
        while (remaining > 0) {
            val n = s.inputStream.read(buf, 0, minOf(buf.size.toLong(), remaining).toInt())
            if (n < 0) break
            out.write(buf, 0, n)
            remaining -= n
        }
        val text = out.toString("UTF-8").trim()
        return try { if (text.isEmpty()) JSONObject() else JSONObject(text) } catch (e: Exception) {
            throw HttpError(400, "JSON 형식이 아닙니다.")
        }
    }

    private fun asset(name: String, mime: String): Response {
        val bytes = ctx.assets.open(name).use { it.readBytes() }
        return newFixedLengthResponse(St(200, "OK"), mime, bytes.inputStream(), bytes.size.toLong())
    }

    private fun json(o: JSONObject, status: Int = 200): Response {
        val bytes = o.toString().toByteArray(Charsets.UTF_8)
        return newFixedLengthResponse(St(status, "OK"), "application/json; charset=utf-8", bytes.inputStream(), bytes.size.toLong())
    }

    private fun ok() = json(JSONObject().put("ok", true))

    private fun errorResponse(status: Int, msg: String): Response {
        val bytes = JSONObject().put("ok", false).put("error", msg).toString().toByteArray(Charsets.UTF_8)
        return newFixedLengthResponse(St(status, "Error"), "application/json; charset=utf-8", bytes.inputStream(), bytes.size.toLong())
    }

    companion object {
        private const val TAG = "AdminServer"
    }
}
