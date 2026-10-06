package com.seyoungjo.tvdashboard.data

import android.content.Context
import android.os.StatFs
import com.seyoungjo.tvdashboard.BuildConfig
import com.seyoungjo.tvdashboard.server.NetInfo
import com.seyoungjo.tvdashboard.update.UpdateManager
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.io.InputStream
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest
import java.util.UUID

/**
 * 자료 폴더 조작 — 같은 망 관리 웹(AdminServer)과 원격 중계(RelayWorker)가 함께 쓴다.
 * 모든 경로는 PathGuard 로 자료 폴더 안으로 제한되고, 파일 쓰기는 항상
 * '.tmp 에 저장 → fsync → 원자적 이동' 순서라서 화면에 불완전한 파일이 보이지 않는다.
 */
class FileOps(private val ctx: Context) {

    class OpError(val status: Int, message: String) : Exception(message)

    private fun guard() = ContentStore.guard(ctx)

    fun requirePath(p: String?): String {
        val n = PathGuard(File("/")).normalize(p)
        if (n.isEmpty()) throw OpError(400, "path 가 필요합니다.")
        return n
    }

    fun newTmp(): File = File(ContentStore.tmpDir(ctx), "up-" + UUID.randomUUID())

    /** 업로드 전에 대상 경로를 검사한다 (본문을 읽기 전에 거절할 수 있도록). */
    fun checkPut(path: String?, overwrite: Boolean, length: Long): String {
        val g = guard()
        val rel = requirePath(path)
        val target = g.resolve(rel)
        if (target.isDirectory) throw OpError(409, "같은 이름의 폴더가 있습니다: $rel")
        if (target.exists() && !overwrite) throw OpError(409, "파일이 이미 있습니다: $rel")
        ensureSpace(target.parentFile ?: g.root, length)
        return rel
    }

    /** input 에서 length 바이트를 받아 path 에 원자적으로 저장 */
    fun put(path: String?, length: Long, input: InputStream, overwrite: Boolean = true): String {
        checkPut(path, overwrite, length)
        val tmp = newTmp()
        try {
            val sha = receive(input, length, tmp)
            return commitTmp(tmp, path, overwrite, null, sha)
        } finally {
            if (tmp.exists()) tmp.delete()
        }
    }

    /** 이미 다 받은 임시 파일을 path 로 원자적으로 옮긴다 (sha256 이 있으면 먼저 검증) */
    fun commitTmp(tmp: File, path: String?, overwrite: Boolean = true, sha256: String? = null, known: String? = null): String {
        val rel = checkPut(path, overwrite, 0)
        val actual = known ?: sha256(tmp)
        if (sha256 != null && !actual.equals(sha256, ignoreCase = true)) {
            throw OpError(400, "파일 검증(SHA-256)에 실패했습니다: $rel")
        }
        val target = guard().resolve(rel)
        val parent = target.parentFile!!
        if (!parent.exists() && !parent.mkdirs()) throw OpError(500, "폴더를 만들 수 없습니다.")
        atomicReplace(tmp, target)
        HashCache.record(ctx, target, actual)
        HashCache.flush(ctx)
        ChangeBus.post(AppEvent.Changed(rel))
        return rel
    }

    fun mkdir(path: String?): String {
        val rel = requirePath(path)
        val d = guard().resolve(rel)
        if (d.isFile) throw OpError(409, "같은 이름의 파일이 있습니다.")
        if (!d.isDirectory && !d.mkdirs()) throw OpError(500, "폴더를 만들 수 없습니다.")
        ChangeBus.post(AppEvent.Changed(rel))
        return rel
    }

    fun rename(path: String?, to: String?): String {
        val g = guard()
        val fromRel = requirePath(path)
        val toRel = requirePath(to)
        val src = g.resolve(fromRel)
        val dst = g.resolve(toRel)
        if (!src.exists()) throw OpError(404, "원본이 없습니다: $fromRel")
        if (dst.exists()) throw OpError(409, "대상 이름이 이미 있습니다: $toRel")
        if (src.isDirectory && (toRel + "/").startsWith("$fromRel/")) throw OpError(400, "폴더를 자기 안으로 옮길 수 없습니다.")
        dst.parentFile?.mkdirs()
        if (!src.renameTo(dst)) throw OpError(500, "이름을 바꿀 수 없습니다.")
        ChangeBus.post(AppEvent.Changed(fromRel))
        ChangeBus.post(AppEvent.Changed(toRel))
        return toRel
    }

    fun delete(path: String?, recursive: Boolean) {
        val rel = requirePath(path)
        val f = guard().resolve(rel)
        if (!f.exists()) throw OpError(404, "대상이 없습니다: $rel")
        val ok = if (f.isDirectory) {
            if (!recursive && (f.list()?.isNotEmpty() == true)) throw OpError(409, "폴더가 비어 있지 않습니다. (recursive=1 필요)")
            f.deleteRecursively()
        } else f.delete()
        if (!ok) throw OpError(500, "삭제하지 못했습니다: $rel")
        ChangeBus.post(AppEvent.Changed(rel))
    }

    /** 읽기용 파일 (없으면 null) */
    fun fileOrNull(path: String?): File? = guard().resolve(requirePath(path)).takeIf { it.isFile }

    /** 읽기용 파일 (자료 폴더 안, 존재하는 파일만) */
    fun file(path: String?): File {
        val f = guard().resolve(requirePath(path))
        if (!f.isFile) throw OpError(404, "파일이 없습니다.")
        return f
    }

    fun list(path: String?): JSONObject {
        val g = guard()
        val rel = g.normalize(path)
        val dir = g.resolve(rel)
        if (!dir.isDirectory) throw OpError(404, "폴더가 없습니다: $rel")
        val arr = JSONArray()
        (dir.listFiles() ?: emptyArray())
            .filter { !it.name.startsWith(".") }
            .sortedWith(compareBy<File> { !it.isDirectory }.thenComparator { a, b -> MenuScanner.naturalCompare(a.name, b.name) })
            .forEach {
                arr.put(
                    JSONObject().put("name", it.name)
                        .put("type", if (it.isDirectory) "dir" else "file")
                        .put("size", if (it.isFile) it.length() else 0)
                        .put("modified", it.lastModified())
                )
            }
        return JSONObject().put("path", rel).put("entries", arr)
    }

    /** 자료 폴더 전체 목록 (원격 PC 화면용): [{p:경로, d:폴더여부, s:크기, t:수정시각, h:버전(SHA-256)}] */
    fun tree(limit: Int = 20000): JSONArray {
        val g = guard()
        val root = g.root.canonicalFile
        val out = JSONArray()
        val seen = HashSet<String>()
        fun walk(dir: File, prefix: String) {
            val kids = (dir.listFiles() ?: return).filter { !it.name.startsWith(".") }
                .sortedWith(compareBy<File> { !it.isDirectory }.thenComparator { a, b -> MenuScanner.naturalCompare(a.name, b.name) })
            for (k in kids) {
                if (out.length() >= limit) return
                val p = if (prefix.isEmpty()) k.name else "$prefix/${k.name}"
                val o = JSONObject().put("p", p).put("d", k.isDirectory)
                    .put("s", if (k.isFile) k.length() else 0).put("t", k.lastModified())
                if (k.isFile) {
                    seen.add(HashCache.key(k))
                    HashCache.get(ctx, k)?.let { o.put("h", it) }
                }
                out.put(o)
                if (k.isDirectory && !java.nio.file.Files.isSymbolicLink(k.toPath())) walk(k, p)
            }
        }
        walk(root, "")
        HashCache.flush(ctx, if (out.length() < limit) seen else null)
        return out
    }

    /** 폴더 총용량(하위 폴더 포함, 없으면 0) */
    fun folderUsage(path: String): Long {
        val d = guard().resolve(requirePath(path))
        if (!d.isDirectory) return 0
        return d.walkTopDown().filter { it.isFile && !it.name.startsWith(".") }.sumOf { it.length() }
    }

    /** 파일 크기 (없으면 0) */
    fun sizeOf(path: String): Long {
        val f = guard().resolve(requirePath(path))
        return if (f.isFile) f.length() else 0
    }

    /** 폴더 안 파일 목록 [{p, s, t}] (직원 도구 결과용) */
    fun filesIn(path: String): JSONArray {
        val g = guard()
        val d = g.resolve(requirePath(path))
        val out = JSONArray()
        if (!d.isDirectory) return out
        var hashed = false
        d.walkTopDown().filter { it.isFile && !it.name.startsWith(".") }.sortedBy { it.path }.forEach {
            val o = JSONObject().put("p", g.relativize(it)).put("s", it.length()).put("t", it.lastModified())
            if (it.extension.equals("json", true)) {          // 직원 도구가 브라우저에 받아 둔 JSON 이 최신인지 비교하는 버전
                HashCache.get(ctx, it)?.let { h -> o.put("h", h); hashed = true }
            }
            out.put(o)
        }
        if (hashed) HashCache.flush(ctx)
        return out
    }

    /** 예제 대시보드(앱에 포함된 assets/sample)를 새 폴더에 복사 */
    fun sample(path: String?): String {
        val rel = requirePath(path)
        val dir = guard().resolve(rel)
        if (dir.exists()) throw OpError(409, "이미 있는 이름입니다: $rel")
        if (!dir.mkdirs()) throw OpError(500, "폴더를 만들 수 없습니다.")
        val title = MenuScanner.displayName(rel.substringAfterLast('/'))
        for (name in ctx.assets.list("sample") ?: emptyArray()) {
            var bytes = ctx.assets.open("sample/$name").use { it.readBytes() }
            if (name == "data.json") {
                bytes = JSONObject(bytes.toString(Charsets.UTF_8)).put("title", "$title 현황")
                    .toString(2).toByteArray(Charsets.UTF_8)
            }
            val tmp = newTmp()
            FileOutputStream(tmp).use { it.write(bytes); it.fd.sync() }
            atomicReplace(tmp, File(dir, name))
        }
        ChangeBus.post(AppEvent.Changed(rel))
        return rel
    }

    /** 업로드된 APK(임시 파일)를 검증해 설치 대기 상태로 둔다 → TV 화면에 설치 확인 창 */
    fun acceptApk(tmp: File): UpdateManager.ApkMeta {
        if (!BuildConfig.SELF_UPDATE) throw OpError(403, "Google Play 버전은 Play 스토어에서 업데이트됩니다.")
        val meta = try {
            UpdateManager.inspectApk(ctx, tmp)
        } catch (e: UpdateManager.UpdateException) {
            throw OpError(400, e.message ?: "APK 검증 실패")
        }
        val dst = File(UpdateManager.updateDir(ctx), "uploaded.apk")
        atomicReplace(tmp, dst)
        ChangeBus.post(AppEvent.UpdateUploaded(dst, meta.versionName))
        return meta
    }

    fun ensureSpace(dir: File, length: Long) {
        var d: File? = dir
        while (d != null && !d.exists()) d = d.parentFile
        val free = StatFs((d ?: ContentStore.root(ctx)).path).availableBytes
        if (length + 50L * 1024 * 1024 > free) throw OpError(507, "TV 저장 공간이 부족합니다.")
    }

    /** 상태 정보 (관리 웹 /api/status 와 원격 PC 화면이 함께 사용) */
    fun status(): JSONObject {
        val root = ContentStore.root(ctx)
        val st = StatFs(root.path)
        val addrs = JSONArray()
        NetInfo.addresses().forEach {
            addrs.put(JSONObject().put("ip", it.ip).put("tailscale", it.tailscale).put("iface", it.iface))
        }
        return JSONObject()
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
    }

    fun menu(): JSONObject {
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
        return JSONObject().put("items", arr).put("idleVideos", videos)
    }

    companion object {
        /** input 에서 정확히 length 바이트를 받아 out 에 쓰고 fsync. 돌려주는 값: SHA-256(hex) */
        fun receive(input: InputStream, length: Long, out: File): String {
            val md = MessageDigest.getInstance("SHA-256")
            val buf = ByteArray(64 * 1024)
            var remaining = length
            FileOutputStream(out).use { fos ->
                while (remaining > 0) {
                    val n = input.read(buf, 0, minOf(buf.size.toLong(), remaining).toInt())
                    if (n < 0) throw OpError(400, "업로드가 중간에 끊겼습니다.")
                    fos.write(buf, 0, n)
                    md.update(buf, 0, n)
                    remaining -= n
                }
                fos.flush()
                fos.fd.sync()
            }
            return md.digest().joinToString("") { "%02x".format(it) }
        }

        fun sha256(f: File): String {
            val md = MessageDigest.getInstance("SHA-256")
            f.inputStream().use { input ->
                val buf = ByteArray(64 * 1024)
                while (true) {
                    val n = input.read(buf)
                    if (n < 0) break
                    md.update(buf, 0, n)
                }
            }
            return md.digest().joinToString("") { "%02x".format(it) }
        }

        fun atomicReplace(src: File, dst: File) {
            try {
                Files.move(src.toPath(), dst.toPath(), StandardCopyOption.ATOMIC_MOVE)
            } catch (e: AtomicMoveNotSupportedException) {
                Files.move(src.toPath(), dst.toPath(), StandardCopyOption.REPLACE_EXISTING)
            }
        }
    }
}
