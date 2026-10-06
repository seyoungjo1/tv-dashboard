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

    const val DEFAULT_TITLE = "대상 오산공장 Dashboard"
    const val DEFAULT_MESSAGE = "오산공장 dashboard 터치시 접속됩니다"

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

    val headerTitle: String get() = prefs.getString("header_title", null)?.trim().orEmpty()
        .ifEmpty { DEFAULT_TITLE }

    val idleEnabled get() = prefs.getBoolean("idle_enabled", true)
    val idleSeconds get() = int("idle_seconds", 300, 10, 24 * 3600)
    val idleMessage: String get() = prefs.getString("idle_message", DEFAULT_MESSAGE) ?: ""
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
}
