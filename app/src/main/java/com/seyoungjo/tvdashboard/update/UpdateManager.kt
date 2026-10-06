package com.seyoungjo.tvdashboard.update

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.os.Build
import androidx.core.content.pm.PackageInfoCompat
import org.json.JSONObject
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

/**
 * 앱 업데이트
 *  1) update.json 확인 (기본: GitHub Releases 최신 버전의 update.json)
 *  2) 새 버전이면 APK 다운로드 → 임시파일(.part) → 완료 후 이름 변경
 *  3) SHA-256 / 패키지명 / versionCode 검증
 *  4) PackageInstaller 로 Android 설치 화면을 띄움 → 사용자가 '설치'를 눌러야 업데이트
 * 어느 단계에서 실패해도 현재 설치된 앱은 그대로 유지됩니다.
 */
object UpdateManager {

    class UpdateException(message: String) : Exception(message)

    data class UpdateInfo(
        val versionName: String,
        val versionCode: Long?,
        val apkUrl: String,
        val sha256: String?,
        val notes: String,
    )

    data class ApkMeta(val packageName: String, val versionName: String, val versionCode: Long)

    fun updateDir(ctx: Context): File = File(ctx.filesDir, "updates").apply { mkdirs() }

    fun currentVersionCode(ctx: Context): Long =
        PackageInfoCompat.getLongVersionCode(ctx.packageManager.getPackageInfo(ctx.packageName, 0))

    fun currentVersionName(ctx: Context): String =
        ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName ?: "?"

    // ── 1) 확인 ───────────────────────────────────────────────────────────
    fun fetchInfo(manifestUrl: String): UpdateInfo {
        val text = httpGetText(manifestUrl)
        val o = try { JSONObject(text) } catch (e: Exception) {
            throw UpdateException("업데이트 정보 형식이 올바르지 않습니다.")
        }
        return parseInfo(o, manifestUrl)
    }

    /** 자체 update.json 형식과 GitHub API(releases/latest) 형식을 모두 지원 */
    fun parseInfo(o: JSONObject, baseUrl: String): UpdateInfo {
        if (o.has("tag_name")) {
            val assets = o.optJSONArray("assets")
            var apk: String? = null
            if (assets != null) for (i in 0 until assets.length()) {
                val a = assets.getJSONObject(i)
                if (a.optString("name").endsWith(".apk")) { apk = a.optString("browser_download_url"); break }
            }
            val name = o.getString("tag_name").removePrefix("v")
            return UpdateInfo(
                name, Versions.codeFromName(name),
                apk ?: throw UpdateException("릴리스에 APK 파일이 없습니다."),
                null, o.optString("body", "")
            )
        }
        val apkUrl = o.optString("apkUrl").ifEmpty { throw UpdateException("update.json 에 apkUrl 이 없습니다.") }
        val name = o.optString("versionName").ifEmpty { throw UpdateException("update.json 에 versionName 이 없습니다.") }
        return UpdateInfo(
            versionName = name,
            versionCode = if (o.has("versionCode")) o.getLong("versionCode") else Versions.codeFromName(name),
            apkUrl = URL(URL(baseUrl), apkUrl).toString(),
            sha256 = o.optString("sha256").ifEmpty { null },
            notes = o.optString("notes", ""),
        )
    }

    fun isNewer(ctx: Context, info: UpdateInfo): Boolean {
        val code = info.versionCode ?: return false
        return code > currentVersionCode(ctx)
    }

    // ── 2) 다운로드 ───────────────────────────────────────────────────────
    fun download(ctx: Context, info: UpdateInfo, progress: (Long, Long) -> Unit, cancelled: () -> Boolean): File {
        val dir = updateDir(ctx)
        val part = File(dir, "download.apk.part")
        val dst = File(dir, "download.apk")
        part.delete()
        val conn = open(info.apkUrl)
        try {
            if (conn.responseCode !in 200..299) throw UpdateException("다운로드 실패 (HTTP ${conn.responseCode})")
            val total = conn.contentLengthLong
            val md = MessageDigest.getInstance("SHA-256")
            conn.inputStream.use { input ->
                FileOutputStream(part).use { out ->
                    val buf = ByteArray(64 * 1024)
                    var done = 0L
                    while (true) {
                        if (cancelled()) throw UpdateException("다운로드를 취소했습니다.")
                        val n = input.read(buf)
                        if (n < 0) break
                        out.write(buf, 0, n)
                        md.update(buf, 0, n)
                        done += n
                        progress(done, total)
                    }
                    out.fd.sync()
                }
            }
            if (info.sha256 != null) {
                val actual = md.digest().joinToString("") { "%02x".format(it) }
                if (!actual.equals(info.sha256, ignoreCase = true)) throw UpdateException("파일 검증(SHA-256)에 실패했습니다.")
            }
            dst.delete()
            if (!part.renameTo(dst)) throw UpdateException("파일 저장에 실패했습니다.")
            return dst
        } catch (e: UpdateException) {
            part.delete(); throw e
        } catch (e: Exception) {
            part.delete(); throw UpdateException("다운로드 실패: ${e.message}")
        } finally {
            conn.disconnect()
        }
    }

    // ── 3) 검증 ───────────────────────────────────────────────────────────
    @Suppress("DEPRECATION")
    fun inspectApk(ctx: Context, apk: File): ApkMeta {
        val info = ctx.packageManager.getPackageArchiveInfo(apk.path, 0)
            ?: throw UpdateException("올바른 APK 파일이 아닙니다.")
        if (info.packageName != ctx.packageName) {
            throw UpdateException("다른 앱의 APK 입니다 (${info.packageName}). 이 앱(${ctx.packageName})용 APK 를 사용하세요.")
        }
        val code = PackageInfoCompat.getLongVersionCode(info)
        val cur = currentVersionCode(ctx)
        if (code <= cur) throw UpdateException("현재 버전(${currentVersionName(ctx)})보다 새 버전이 아닙니다 (${info.versionName}).")
        return ApkMeta(info.packageName, info.versionName ?: "?", code)
    }

    // ── 4) 설치 (사용자 승인 필요) ────────────────────────────────────────
    fun canInstall(ctx: Context): Boolean =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.O || ctx.packageManager.canRequestPackageInstalls()

    fun install(ctx: Context, apk: File) {
        inspectApk(ctx, apk)
        val installer = ctx.packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
        params.setAppPackageName(ctx.packageName)
        params.setSize(apk.length())
        val sessionId = installer.createSession(params)
        try {
            installer.openSession(sessionId).use { session ->
                FileInputStream(apk).use { input ->
                    session.openWrite("update.apk", 0, apk.length()).use { out ->
                        input.copyTo(out, 64 * 1024)
                        session.fsync(out)
                    }
                }
                val intent = Intent(ctx, InstallResultReceiver::class.java)
                val flags = PendingIntent.FLAG_UPDATE_CURRENT or
                    (if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) PendingIntent.FLAG_MUTABLE else 0)
                val pi = PendingIntent.getBroadcast(ctx, sessionId, intent, flags)
                session.commit(pi.intentSender)
            }
        } catch (e: Exception) {
            try { installer.abandonSession(sessionId) } catch (_: Exception) {}
            throw UpdateException("설치 준비 실패: ${e.message}")
        }
    }

    /** 이미 설치된 버전 이하의 APK 파일 정리 */
    fun cleanupOldApks(ctx: Context) {
        try {
            updateDir(ctx).listFiles()?.forEach { f ->
                if (f.name.endsWith(".part")) { f.delete(); return@forEach }
                val ok = try { inspectApk(ctx, f); true } catch (e: Exception) { false }
                if (!ok) f.delete()
            }
        } catch (_: Exception) {}
    }

    /** 관리 웹에서 업로드되어 설치 대기 중인 APK */
    fun pendingUploaded(ctx: Context): Pair<File, ApkMeta>? {
        val f = File(updateDir(ctx), "uploaded.apk")
        if (!f.exists()) return null
        return try { f to inspectApk(ctx, f) } catch (e: Exception) { f.delete(); null }
    }

    // ── HTTP ─────────────────────────────────────────────────────────────
    private fun open(url: String): HttpURLConnection {
        var current = URL(url)
        repeat(6) {
            val c = current.openConnection() as HttpURLConnection
            c.connectTimeout = 15_000
            c.readTimeout = 30_000
            c.instanceFollowRedirects = false
            c.setRequestProperty("User-Agent", "tv-dashboard-updater")
            c.setRequestProperty("Accept", "application/json, application/octet-stream, */*")
            val code = c.responseCode
            if (code in 300..399) {
                val loc = c.getHeaderField("Location") ?: throw UpdateException("잘못된 리다이렉트")
                c.disconnect()
                current = URL(current, loc)
                if (current.protocol != "https" && current.protocol != "http") throw UpdateException("지원하지 않는 주소")
                return@repeat
            }
            return c
        }
        throw UpdateException("리다이렉트가 너무 많습니다.")
    }

    private fun httpGetText(url: String): String {
        val c = try { open(url) } catch (e: UpdateException) { throw e } catch (e: Exception) {
            throw UpdateException("업데이트 서버에 연결할 수 없습니다: ${e.message}")
        }
        try {
            if (c.responseCode == 404) throw UpdateException("업데이트 정보를 찾을 수 없습니다 (404). 저장소가 비공개이거나 아직 릴리스가 없습니다.")
            if (c.responseCode !in 200..299) throw UpdateException("업데이트 확인 실패 (HTTP ${c.responseCode})")
            return c.inputStream.use { it.readBytes().toString(Charsets.UTF_8) }
        } finally {
            c.disconnect()
        }
    }
}
