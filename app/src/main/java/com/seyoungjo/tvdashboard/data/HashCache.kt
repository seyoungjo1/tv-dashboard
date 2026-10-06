package com.seyoungjo.tvdashboard.data

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * 파일 버전(SHA-256) 캐시 — PC 프로그램이 "바뀐 파일만" 올릴 수 있도록 목록(tree)에 버전을 실어 보낸다.
 * 크기·수정시각이 기록과 같으면 저장된 값을 쓰고, 다르거나 없으면 다시 계산한다(USB 등으로 바뀐 파일도 맞게 잡힘).
 * 앱 전용 폴더의 hashes.json 에 보관 (자료 폴더에는 아무것도 만들지 않는다).
 */
object HashCache {
    /** 이보다 큰 파일은 목록을 만들 때 새로 계산하지 않는다 (올릴 때 기록된 값만 사용) */
    private const val MAX_SCAN = 64L * 1024 * 1024

    private class Entry(val size: Long, val time: Long, val sha: String)

    fun key(f: File): String = try { f.canonicalPath } catch (_: Exception) { f.absolutePath }

    private var file: File? = null
    private var map: HashMap<String, Entry>? = null
    private var dirty = false

    @Synchronized
    private fun load(ctx: Context): HashMap<String, Entry> {
        map?.let { return it }
        val f = File(ctx.filesDir, "hashes.json").also { file = it }
        val m = HashMap<String, Entry>()
        try {
            if (f.isFile) {
                val o = JSONObject(f.readText())
                for (k in o.keys()) {
                    val a = o.getJSONArray(k)
                    m[k] = Entry(a.getLong(0), a.getLong(1), a.getString(2))
                }
            }
        } catch (_: Exception) {
        }
        map = m
        return m
    }

    /** 방금 저장한 파일의 버전을 기록 */
    @Synchronized
    fun record(ctx: Context, f: File, sha: String) {
        load(ctx)[key(f)] = Entry(f.length(), f.lastModified(), sha.lowercase())
        dirty = true
    }

    /** 파일 버전 (모르면 계산, 너무 크면 null) */
    @Synchronized
    fun get(ctx: Context, f: File): String? {
        val m = load(ctx)
        val k = key(f)
        val e = m[k]
        if (e != null && e.size == f.length() && e.time == f.lastModified()) return e.sha
        if (f.length() > MAX_SCAN) return null
        return try {
            FileOps.sha256(f).also { m[k] = Entry(f.length(), f.lastModified(), it); dirty = true }
        } catch (_: Exception) {
            null
        }
    }

    /** 목록에 없는 파일의 기록을 지우고 바뀐 내용을 저장 */
    @Synchronized
    fun flush(ctx: Context, seen: Set<String>? = null) {
        val m = load(ctx)
        if (seen != null && m.keys.retainAll(seen)) dirty = true
        if (!dirty) return
        val o = JSONObject()
        for ((k, e) in m) o.put(k, JSONArray().put(e.size).put(e.time).put(e.sha))
        try {
            val f = file ?: return
            val tmp = File(f.path + ".tmp")
            tmp.writeText(o.toString())
            tmp.renameTo(f)
            dirty = false
        } catch (_: Exception) {
        }
    }
}
