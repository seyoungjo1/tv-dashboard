package com.seyoungjo.tvdashboard.server

import android.content.Context
import android.os.StatFs
import android.util.Log
import com.seyoungjo.tvdashboard.BuildConfig
import com.seyoungjo.tvdashboard.data.AppEvent
import com.seyoungjo.tvdashboard.data.AppSettings
import com.seyoungjo.tvdashboard.data.ChangeBus
import com.seyoungjo.tvdashboard.data.ContentStore
import com.seyoungjo.tvdashboard.data.MenuScanner
import com.seyoungjo.tvdashboard.data.PathGuard
import com.seyoungjo.tvdashboard.update.UpdateManager
import fi.iki.elonen.NanoHTTPD
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.io.InputStream
import java.net.URLEncoder
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.util.UUID

/**
 * TV 안에서 동작하는 파일 관리 웹서버.
 *   GET  /                  관리 웹 페이지
 *   POST /api/login         {"password"} → {"token"}
 *   그 외 /api/...          Authorization: Bearer <세션 토큰 또는 API 토큰>
 * 모든 경로는 자료 폴더 안으로 제한됩니다.
 */
class AdminServer(private val ctx: Context, port: Int) : NanoHTTPD(port) {

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

    // ── 조회 ──────────────────────────────────────────────────────────────
    private fun status(): Response {
        val root = ContentStore.root(ctx)
        val st = StatFs(root.path)
        val addrs = JSONArray()
        NetInfo.addresses().forEach {
            addrs.put(JSONObject().put("ip", it.ip).put("tailscale", it.tailscale).put("iface", it.iface))
        }
        return json(
            JSONObject()
                .put("versionName", BuildConfig.VERSION_NAME)
                .put("versionCode", BuildConfig.VERSION_CODE)
                .put("package", ctx.packageName)
                .put("storageMode", ContentStore.effectiveMode())
                .put("storageModeSetting", AppSettings.storageMode)
                .put("root", root.path)
                .put("freeBytes", st.availableBytes)
                .put("totalBytes", st.totalBytes)
                .put("port", AppSettings.port)
                .put("addresses", addrs)
                .put("deletedOnUninstall", ContentStore.effectiveMode() == "app")
        )
    }

    private fun menu(): Response {
        val root = ContentStore.root(ctx)
        val arr = JSONArray()
        MenuScanner.scan(root).forEach { e ->
            arr.put(
                JSONObject().put("folder", e.folder).put("title", e.title)
                    .put("image", e.image?.let { PathGuard(root).relativize(it) } ?: JSONObject.NULL)
                    .put("index", e.indexFile ?: JSONObject.NULL)
            )
        }
        val videos = JSONArray()
        MenuScanner.idleVideos(root).forEach { videos.put(it.name) }
        return json(JSONObject().put("items", arr).put("idleVideos", videos))
    }

    private fun list(path: String?): Response {
        val g = ContentStore.guard(ctx)
        val rel = g.normalize(path)
        val dir = g.resolve(rel)
        if (!dir.isDirectory) throw HttpError(404, "폴더가 없습니다: $rel")
        val arr = JSONArray()
        (dir.listFiles() ?: emptyArray())
            .filter { !it.name.startsWith(".") }
            .sortedWith(compareBy<File>({ !it.isDirectory }) .thenComparator { a, b -> MenuScanner.naturalCompare(a.name, b.name) })
            .forEach {
                arr.put(
                    JSONObject().put("name", it.name)
                        .put("type", if (it.isDirectory) "dir" else "file")
                        .put("size", if (it.isFile) it.length() else 0)
                        .put("modified", it.lastModified())
                )
            }
        return json(JSONObject().put("path", rel).put("entries", arr))
    }

    private fun download(path: String?): Response {
        val g = ContentStore.guard(ctx)
        val f = g.resolve(requirePath(path))
        if (!f.isFile) throw HttpError(404, "파일이 없습니다.")
        val r = newFixedLengthResponse(St(200, "OK"), Mime.of(f.name), FileInputStream(f), f.length())
        val enc = URLEncoder.encode(f.name, "UTF-8").replace("+", "%20")
        r.addHeader("Content-Disposition", "attachment; filename*=UTF-8''$enc")
        return r
    }

    // ── 변경 ──────────────────────────────────────────────────────────────
    /**
     * 업로드: 본문을 .tmp 폴더에 먼저 저장 → 디스크 동기화 → 원자적 이동(rename)으로 교체.
     * 화면(WebView)은 항상 '이전 완성본' 또는 '새 완성본'만 읽게 됩니다.
     */
    private fun upload(s: IHTTPSession, path: String?, overwrite: Boolean): Response {
        val g = ContentStore.guard(ctx)
        val rel = requirePath(path)
        val target = g.resolve(rel)
        if (target.isDirectory) throw HttpError(409, "같은 이름의 폴더가 있습니다: $rel")
        if (target.exists() && !overwrite) throw HttpError(409, "파일이 이미 있습니다: $rel")
        val length = contentLength(s)
        ensureSpace(target.parentFile ?: g.root, length)

        val parent = target.parentFile!!
        if (!parent.exists() && !parent.mkdirs()) throw HttpError(500, "폴더를 만들 수 없습니다.")
        val tmp = File(ContentStore.tmpDir(ctx), "up-" + UUID.randomUUID())
        try {
            receiveTo(s, length, tmp)
            atomicReplace(tmp, target)
        } finally {
            if (tmp.exists()) tmp.delete()
        }
        Log.i(TAG, "uploaded $rel ($length bytes)")
        ChangeBus.post(AppEvent.Changed(rel))
        return json(JSONObject().put("ok", true).put("path", rel).put("size", target.length()))
    }

    private fun mkdir(path: String?): Response {
        val g = ContentStore.guard(ctx)
        val rel = requirePath(path)
        val d = g.resolve(rel)
        if (d.isFile) throw HttpError(409, "같은 이름의 파일이 있습니다.")
        if (!d.isDirectory && !d.mkdirs()) throw HttpError(500, "폴더를 만들 수 없습니다.")
        ChangeBus.post(AppEvent.Changed(rel))
        return json(JSONObject().put("ok", true).put("path", rel))
    }

    private fun rename(path: String?, to: String?): Response {
        val g = ContentStore.guard(ctx)
        val fromRel = requirePath(path)
        val toRel = requirePath(to)
        val src = g.resolve(fromRel)
        val dst = g.resolve(toRel)
        if (!src.exists()) throw HttpError(404, "원본이 없습니다.")
        if (dst.exists()) throw HttpError(409, "대상 이름이 이미 있습니다.")
        if (src.isDirectory && (toRel + "/").startsWith("$fromRel/")) throw HttpError(400, "폴더를 자기 안으로 옮길 수 없습니다.")
        dst.parentFile?.mkdirs()
        if (!src.renameTo(dst)) throw HttpError(500, "이름을 바꿀 수 없습니다.")
        ChangeBus.post(AppEvent.Changed(fromRel))
        ChangeBus.post(AppEvent.Changed(toRel))
        return json(JSONObject().put("ok", true).put("path", toRel))
    }

    private fun delete(path: String?, recursive: Boolean): Response {
        val g = ContentStore.guard(ctx)
        val rel = requirePath(path)
        val f = g.resolve(rel)
        if (!f.exists()) throw HttpError(404, "대상이 없습니다.")
        val okDel = if (f.isDirectory) {
            if (!recursive && (f.list()?.isNotEmpty() == true)) throw HttpError(409, "폴더가 비어 있지 않습니다. (recursive=1 필요)")
            f.deleteRecursively()
        } else f.delete()
        if (!okDel) throw HttpError(500, "삭제하지 못했습니다.")
        ChangeBus.post(AppEvent.Changed(rel))
        return ok()
    }

    // ── 설정 ──────────────────────────────────────────────────────────────
    private fun getSettings(): Response {
        val o = JSONObject()
        val p = AppSettings.prefs
        AppSettings.REMOTE_KEYS.forEach { (k, type) ->
            when (type) {
                Boolean::class -> o.put(k, p.getBoolean(k, false))
                else -> o.put(k, p.getString(k, "") ?: "")
            }
        }
        return json(o)
    }

    private fun putSettings(body: JSONObject): Response {
        val e = AppSettings.prefs.edit()
        AppSettings.REMOTE_KEYS.forEach { (k, type) ->
            if (!body.has(k)) return@forEach
            when (type) {
                Boolean::class -> e.putBoolean(k, body.getBoolean(k))
                Int::class -> {
                    val v = body.get(k).toString().trim().toIntOrNull() ?: throw HttpError(400, "$k 는 숫자여야 합니다.")
                    if (v < 0) throw HttpError(400, "$k 는 0 이상이어야 합니다.")
                    e.putString(k, v.toString())
                }
                else -> e.putString(k, body.getString(k))
            }
        }
        e.apply()
        ChangeBus.post(AppEvent.SettingsChanged)
        return getSettings()
    }

    // ── 앱 업데이트 APK 업로드 (비공개 저장소용 배포 경로) ─────────────────────
    private fun uploadApk(s: IHTTPSession): Response {
        val length = contentLength(s)
        val dir = UpdateManager.updateDir(ctx)
        ensureSpace(dir, length)
        val tmp = File(dir, "upload-" + UUID.randomUUID() + ".part")
        try {
            receiveTo(s, length, tmp)
            val meta = UpdateManager.inspectApk(ctx, tmp) // 패키지명·버전 검증, 실패 시 예외
            val dst = File(dir, "uploaded.apk")
            atomicReplace(tmp, dst)
            ChangeBus.post(AppEvent.UpdateUploaded(dst, meta.versionName))
            return json(
                JSONObject().put("ok", true).put("versionName", meta.versionName)
                    .put("versionCode", meta.versionCode)
                    .put("message", "TV 화면에 설치 확인 창이 표시됩니다. TV 에서 '설치'를 눌러야 업데이트됩니다.")
            )
        } catch (e: UpdateManager.UpdateException) {
            throw HttpError(400, e.message ?: "APK 검증 실패")
        } finally {
            if (tmp.exists()) tmp.delete()
        }
    }

    // ── 도우미 ────────────────────────────────────────────────────────────
    private fun param(s: IHTTPSession, name: String): String? = s.parameters[name]?.firstOrNull()

    private fun requirePath(p: String?): String {
        val n = PathGuard(File("/")).normalize(p)
        if (n.isEmpty()) throw HttpError(400, "path 가 필요합니다.")
        return n
    }

    private fun contentLength(s: IHTTPSession): Long {
        val len = s.headers["content-length"]?.toLongOrNull()
            ?: throw HttpError(411, "Content-Length 헤더가 필요합니다.")
        if (len < 0) throw HttpError(400, "잘못된 Content-Length")
        return len
    }

    private fun ensureSpace(dir: File, length: Long) {
        var d: File? = dir
        while (d != null && !d.exists()) d = d.parentFile
        val free = StatFs((d ?: ContentStore.root(ctx)).path).availableBytes
        if (length + 50L * 1024 * 1024 > free) throw HttpError(507, "TV 저장 공간이 부족합니다.")
    }

    private fun receiveTo(s: IHTTPSession, length: Long, out: File) {
        bodyRead.set(true)
        val input: InputStream = s.inputStream
        val buf = ByteArray(64 * 1024)
        var remaining = length
        FileOutputStream(out).use { fos ->
            while (remaining > 0) {
                val n = input.read(buf, 0, minOf(buf.size.toLong(), remaining).toInt())
                if (n < 0) throw HttpError(400, "업로드가 중간에 끊겼습니다.")
                fos.write(buf, 0, n)
                remaining -= n
            }
            fos.flush()
            fos.fd.sync()
        }
    }

    private fun atomicReplace(src: File, dst: File) {
        try {
            Files.move(src.toPath(), dst.toPath(), StandardCopyOption.ATOMIC_MOVE)
        } catch (e: AtomicMoveNotSupportedException) {
            Files.move(src.toPath(), dst.toPath(), StandardCopyOption.REPLACE_EXISTING)
        }
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
