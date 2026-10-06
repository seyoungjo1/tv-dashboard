package com.seyoungjo.tvdashboard.relay

import com.seyoungjo.tvdashboard.data.AppSettings
import org.json.JSONObject

/**
 * 원격 중계 설정. PC 프로그램이 만든 tvrelay.json 을 그대로 불러온다:
 *   {"repo":"seyoungjo1/tv-dashboard-relay","tv":"osan","key":"…","token":"github_pat_…"}
 * 키·토큰은 TV 안(앱 전용 설정)에만 저장하고 관리 웹·화면에 다시 보여 주지 않는다.
 */
object RelaySettings {
    const val DEFAULT_REPO = "seyoungjo1/tv-dashboard-relay"
    private val p get() = AppSettings.prefs

    val enabled get() = p.getBoolean("relay_enabled", true)
    val repo: String get() = p.getString("relay_repo", null)?.trim().orEmpty().ifEmpty { DEFAULT_REPO }
    val tv: String get() = p.getString("relay_tv", null)?.trim().orEmpty().ifEmpty { "osan" }
    val key: String get() = p.getString("relay_key", "") ?: ""
    val token: String get() = p.getString("relay_token", "") ?: ""
    val intervalSec: Int get() = (p.getString("relay_interval", null)?.trim()?.toIntOrNull() ?: 10).coerceIn(5, 3600)
    val configured get() = key.isNotBlank() && token.isNotBlank()

    private val NAME = Regex("^[A-Za-z0-9][A-Za-z0-9._-]{0,38}$")
    private val REPO = Regex("^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")

    /** tvrelay.json 내용(또는 관리 웹에서 보낸 값) 저장. 잘못된 값이면 IllegalArgumentException */
    fun apply(o: JSONObject) {
        val e = p.edit()
        if (o.has("repo")) {
            val v = o.getString("repo").trim()
            require(REPO.matches(v)) { "repo 는 '계정/레포' 형식이어야 합니다." }
            e.putString("relay_repo", v)
        }
        if (o.has("tv")) {
            val v = o.getString("tv").trim()
            require(NAME.matches(v)) { "tv 이름은 영문·숫자·-·_ 만 쓸 수 있습니다." }
            e.putString("relay_tv", v)
        }
        if (o.has("key") && o.getString("key").isNotBlank()) {
            val v = o.getString("key").trim()
            RelayCrypto(v)                        // 길이 검사
            e.putString("relay_key", v)
        }
        if (o.has("token") && o.getString("token").isNotBlank()) e.putString("relay_token", o.getString("token").trim())
        if (o.has("enabled")) e.putBoolean("relay_enabled", o.getBoolean("enabled"))
        if (o.has("interval")) {
            val v = o.get("interval").toString().toIntOrNull() ?: throw IllegalArgumentException("interval 은 숫자여야 합니다.")
            e.putString("relay_interval", v.coerceIn(5, 3600).toString())
        }
        e.apply()
    }

    /** 원격 연결 초기화 (다시 연결 코드로 연결) */
    fun reset() {
        p.edit().remove("relay_key").remove("relay_token").remove("pair_code").apply()
    }

    fun publicJson(): JSONObject = JSONObject()
        .put("enabled", enabled).put("repo", repo).put("tv", tv).put("interval", intervalSec)
        .put("hasKey", key.isNotBlank()).put("hasToken", token.isNotBlank())
        .put("status", RelayWorker.status).put("lastSync", RelayWorker.lastSync)
        .put("pairCode", if (configured) JSONObject.NULL else Pairing.code)
}
