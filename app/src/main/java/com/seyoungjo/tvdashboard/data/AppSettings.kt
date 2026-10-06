package com.seyoungjo.tvdashboard.data

import android.content.Context
import android.content.SharedPreferences
import androidx.preference.PreferenceManager
import com.seyoungjo.tvdashboard.BuildConfig
import com.seyoungjo.tvdashboard.R

/** 설정값(기기 화면의 설정 + 관리 웹에서 함께 사용) */
object AppSettings {
    lateinit var prefs: SharedPreferences
        private set

    const val DEFAULT_TITLE = "오산공장 스마트 현황판"
    private const val OLD_DEFAULT_TITLE = "대상 오산공장 Dashboard"
    const val DEFAULT_MESSAGE = "화면을 터치하면 대시보드로 들어갑니다"
    private const val OLD_DEFAULT_MESSAGE = "오산공장 dashboard 터치시 접속됩니다"

    fun init(context: Context) {
        PreferenceManager.setDefaultValues(context, R.xml.preferences, false)
        prefs = PreferenceManager.getDefaultSharedPreferences(context)
        if (prefs.getString("update_url", null).isNullOrBlank()) {
            prefs.edit().putString("update_url", BuildConfig.DEFAULT_UPDATE_URL).apply()
        }
    }

    private fun int(key: String, def: Int, min: Int, max: Int): Int =
        (prefs.getString(key, null)?.trim()?.toIntOrNull() ?: def).coerceIn(min, max)

    val port get() = int("port", 8080, 1024, 65535)
    val tailscaleOnly get() = prefs.getBoolean("tailscale_only", false)
    val keepScreenOn get() = prefs.getBoolean("keep_screen_on", true)
    val autoStart get() = prefs.getBoolean("auto_start", true)
    val autoRefresh get() = prefs.getBoolean("auto_refresh", true)
    val storageMode: String get() = prefs.getString("storage_mode", "app") ?: "app"
    val settingsPin: String get() = prefs.getString("settings_pin", "")?.trim() ?: ""
    val updateUrl: String get() = prefs.getString("update_url", null)?.trim().orEmpty()
        .ifEmpty { BuildConfig.DEFAULT_UPDATE_URL }

    /** 상단 제목 — 메인 화면 상단바와 화면보호기가 같은 문구를 쓴다 */
    val headerTitle: String get() = prefs.getString("header_title", null)?.trim().orEmpty()
        .let { if (it == OLD_DEFAULT_TITLE) "" else it }                  // 예전 기본 제목은 새 기본값으로
        .ifEmpty { DEFAULT_TITLE }

    val idleEnabled get() = prefs.getBoolean("idle_enabled", true)
    val idleSeconds get() = int("idle_seconds", 300, 10, 24 * 3600)
    val idleMessage: String get() = (prefs.getString("idle_message", DEFAULT_MESSAGE) ?: "")
        .let { if (it == OLD_DEFAULT_MESSAGE) DEFAULT_MESSAGE else it }   // 예전 기본 멘트는 새 문구로
    val idleMsgShowSec get() = int("idle_msg_show_sec", 0, 0, 3600)
    val idleMsgHideSec get() = int("idle_msg_hide_sec", 0, 0, 3600)

    var lastFolder: String?
        get() = prefs.getString("last_folder", null)
        set(v) = prefs.edit().putString("last_folder", v).apply()

    /** 관리 웹에서 바꿀 수 있는 항목 (키 → 타입) */
    val REMOTE_KEYS = linkedMapOf(
        "header_title" to String::class,
        "idle_enabled" to Boolean::class,
        "idle_seconds" to Int::class,
        "idle_message" to String::class,
        "idle_msg_show_sec" to Int::class,
        "idle_msg_hide_sec" to Int::class,
        "idle_video_sound" to Boolean::class,
        "auto_refresh" to Boolean::class,
        "keep_screen_on" to Boolean::class,
        "update_url" to String::class,
        "settings_pin" to String::class,
    )

    /** 관리 웹 · 원격 PC 에 보여 주는 설정값 */
    fun remoteJson(): org.json.JSONObject {
        val o = org.json.JSONObject()
        REMOTE_KEYS.forEach { (k, type) ->
            when (type) {
                Boolean::class -> o.put(k, prefs.getBoolean(k, false))
                else -> o.put(k, prefs.getString(k, "") ?: "")
            }
        }
        return o
    }

    /** 원격에서 받은 설정 저장 (잘못된 값이면 IllegalArgumentException) */
    fun applyRemote(body: org.json.JSONObject) {
        val e = prefs.edit()
        REMOTE_KEYS.forEach { (k, type) ->
            if (!body.has(k)) return@forEach
            when (type) {
                Boolean::class -> e.putBoolean(k, body.getBoolean(k))
                Int::class -> {
                    val v = body.get(k).toString().trim().toIntOrNull()
                        ?: throw IllegalArgumentException("$k 는 숫자여야 합니다.")
                    require(v >= 0) { "$k 는 0 이상이어야 합니다." }
                    e.putString(k, v.toString())
                }
                else -> e.putString(k, body.getString(k))
            }
        }
        e.apply()
        ChangeBus.post(AppEvent.SettingsChanged)
    }
}
