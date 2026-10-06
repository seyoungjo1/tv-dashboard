package com.seyoungjo.tvdashboard.relay

import com.seyoungjo.tvdashboard.data.AppSettings
import org.json.JSONArray
import org.json.JSONObject

/** TV 에 등록된 직원용 업로드 도구 권한 (앱 전용 설정에 보관 — 키는 밖으로 내보내지 않는다) */
object GrantStore {
    private const val KEY = "relay_grants"
    /** 직원 도구로 올릴 수 있는 형식 (기본) */
    val DEFAULT_TYPES = listOf("png", "js", "json", "html", "htm")
    private val GID = Regex("^[0-9a-f]{8,32}$")

    @Synchronized
    fun all(): Map<String, GrantPolicy.Grant> {
        val o = try { JSONObject(AppSettings.prefs.getString(KEY, "{}") ?: "{}") } catch (e: Exception) { JSONObject() }
        val out = LinkedHashMap<String, GrantPolicy.Grant>()
        for (gid in o.keys()) {
            val g = o.getJSONObject(gid)
            val types = g.optJSONArray("types") ?: JSONArray()
            out[gid] = GrantPolicy.Grant(
                gid, g.getString("key"), g.getString("folder"), g.getLong("maxBytes"),
                (0 until types.length()).map { types.getString(it).lowercase().removePrefix(".") }.toSet(),
                g.optString("name", g.getString("folder")),
            )
        }
        return out
    }

    fun get(gid: String): GrantPolicy.Grant? = all()[gid]

    @Synchronized
    fun put(op: JSONObject): GrantPolicy.Grant {
        val gid = op.getString("gid")
        require(GID.matches(gid)) { "잘못된 도구 id" }
        val folder = com.seyoungjo.tvdashboard.data.PathGuard(java.io.File("/")).normalize(op.getString("folder"))
        require(folder.isNotEmpty()) { "폴더를 지정해야 합니다" }
        val key = op.getString("key")
        RelayCrypto(key)                                   // 키 길이 검사
        val maxBytes = op.optLong("maxBytes", 100L * 1024 * 1024)
        require(maxBytes in 1..(4L * 1024 * 1024 * 1024)) { "용량 한도가 올바르지 않습니다" }
        val types = op.optJSONArray("types") ?: JSONArray(DEFAULT_TYPES)
        val o = try { JSONObject(AppSettings.prefs.getString(KEY, "{}") ?: "{}") } catch (e: Exception) { JSONObject() }
        o.put(gid, JSONObject().put("key", key).put("folder", folder).put("maxBytes", maxBytes).put("types", types)
            .put("name", op.optString("name", folder)).put("created", System.currentTimeMillis()))
        AppSettings.prefs.edit().putString(KEY, o.toString()).apply()
        return get(gid)!!
    }

    @Synchronized
    fun remove(gid: String) {
        val o = try { JSONObject(AppSettings.prefs.getString(KEY, "{}") ?: "{}") } catch (e: Exception) { JSONObject() }
        o.remove(gid)
        AppSettings.prefs.edit().putString(KEY, o.toString()).apply()
    }
}
