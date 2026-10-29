package com.seyoungjo.tvdashboard.relay

import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.util.Base64
import java.util.UUID
import java.util.zip.GZIPOutputStream

/**
 * 파일 목록의 '갱신시간 장부' — 블루투스(느린 길)로 목록 전체를 매번 보내지 않으려고 둔다.
 * TV 는 이 장부를 앱 전용 폴더의 bt-index.json 에 저장하고, PC(tvrelay/tvindex.py) 도 같은 모양을 out/tv/<TV>/index.json 에 둔다.
 *
 *   {"v":1, "id":"<장부 id>", "gen":<번호>, "at":<ms>,
 *    "files": {"경로": [폴더?1:0, 크기, 갱신시각(ms), "sha256"(없으면 "")]},
 *    "log": [{"g":번호, "set":{경로: [...]}, "del":[경로…]}, …]}      ← 최근 LOG_MAX 번의 바뀐 것만
 *
 * PC 는 자기가 가진 (id, gen) 을 보내고, TV 는 since() 로
 *   같으면 {"same":true} · 장부에 남은 범위면 바뀐 것만 {"set","del"} · 아니면 전체 {"full"} (크면 gzip 해서 "fullz")
 * 를 돌려준다. 파일이 바뀌지 않았으면 블루투스로 오가는 것은 수십 바이트뿐이다.
 */
object TreeIndex {
    const val LOG_MAX = 40
    const val GZIP_OVER = 8 * 1024

    /** FileOps.tree() 결과 → {경로: [d, s, t, h]} */
    fun entries(tree: JSONArray): JSONObject {
        val out = JSONObject()
        for (i in 0 until tree.length()) {
            val e = tree.getJSONObject(i)
            out.put(e.getString("p"), JSONArray().put(if (e.optBoolean("d")) 1 else 0).put(e.optLong("s")).put(e.optLong("t")).put(e.optString("h", "")))
        }
        return out
    }

    private fun same(a: JSONArray, b: JSONArray) = a.toString() == b.toString()

    /** 새 목록으로 장부를 갱신한다. 바뀐 게 없으면 old 그대로(gen 그대로) */
    fun update(old: JSONObject?, tree: JSONArray, now: Long): JSONObject {
        val files = entries(tree)
        if (old == null || old.optInt("v") != 1 || !old.has("files")) {
            return JSONObject().put("v", 1).put("id", UUID.randomUUID().toString().take(12)).put("gen", 1L)
                .put("at", now).put("files", files).put("log", JSONArray())
        }
        val prev = old.getJSONObject("files")
        val set = JSONObject()
        val del = JSONArray()
        for (p in files.keys()) {
            val n = files.getJSONArray(p)
            val o = prev.optJSONArray(p)
            if (o == null || !same(o, n)) set.put(p, n)
        }
        for (p in prev.keys()) if (!files.has(p)) del.put(p)
        if (set.length() == 0 && del.length() == 0) return old
        val gen = old.getLong("gen") + 1
        val log = old.optJSONArray("log") ?: JSONArray()
        val nl = JSONArray()
        val from = maxOf(0, log.length() + 1 - LOG_MAX)
        for (i in from until log.length()) nl.put(log.get(i))
        nl.put(JSONObject().put("g", gen).put("set", set).put("del", del))
        return JSONObject().put("v", 1).put("id", old.getString("id")).put("gen", gen).put("at", now)
            .put("files", files).put("log", nl)
    }

    /** PC 가 가진 (id, gen) 이후로 바뀐 것 */
    fun since(index: JSONObject, id: String?, gen: Long): JSONObject {
        val cur = index.getLong("gen")
        val out = JSONObject().put("id", index.getString("id")).put("gen", cur).put("at", index.optLong("at"))
        if (id == index.getString("id") && gen == cur) return out.put("same", true)
        val log = index.optJSONArray("log") ?: JSONArray()
        val oldest = if (log.length() > 0) log.getJSONObject(0).getLong("g") else Long.MAX_VALUE
        if (id == index.getString("id") && gen in (oldest - 1) until cur) {
            val set = LinkedHashMap<String, JSONArray>()
            val del = LinkedHashSet<String>()
            for (i in 0 until log.length()) {
                val l = log.getJSONObject(i)
                if (l.getLong("g") <= gen) continue
                val s = l.getJSONObject("set")
                for (p in s.keys()) { set[p] = s.getJSONArray(p); del.remove(p) }
                val d = l.getJSONArray("del")
                for (k in 0 until d.length()) { val p = d.getString(k); set.remove(p); del.add(p) }
            }
            val so = JSONObject(); set.forEach { (k, v) -> so.put(k, v) }
            return out.put("set", so).put("del", JSONArray(del.toList()))
        }
        val full = index.getJSONObject("files")
        val text = full.toString()
        return if (text.length > GZIP_OVER) out.put("fullz", gzipB64(text)) else out.put("full", full)
    }

    fun gzipB64(text: String): String {
        val bo = ByteArrayOutputStream()
        GZIPOutputStream(bo).use { it.write(text.toByteArray(Charsets.UTF_8)) }
        return Base64.getEncoder().encodeToString(bo.toByteArray())
    }
}
