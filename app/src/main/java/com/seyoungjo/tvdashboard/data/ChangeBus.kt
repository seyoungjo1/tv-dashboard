package com.seyoungjo.tvdashboard.data

import android.os.Handler
import android.os.Looper
import java.io.File
import java.util.concurrent.CopyOnWriteArraySet

/** 서버(업로드 등) → 화면 으로 변경 사항을 알리는 앱 내부 이벤트 */
sealed class AppEvent {
    /** 자료 변경 (상대 경로, "" = 루트) */
    data class Changed(val path: String) : AppEvent()
    /** 화면 강제 새로고침 */
    object Reload : AppEvent()
    /** 설정 변경(관리 웹) */
    object SettingsChanged : AppEvent()
    /** 관리 웹에서 새 APK 가 업로드됨 */
    data class UpdateUploaded(val apk: File, val versionName: String) : AppEvent()
}

object ChangeBus {
    private val main = Handler(Looper.getMainLooper())
    private val listeners = CopyOnWriteArraySet<(AppEvent) -> Unit>()

    fun add(l: (AppEvent) -> Unit) { listeners.add(l) }
    fun remove(l: (AppEvent) -> Unit) { listeners.remove(l) }

    fun post(e: AppEvent) {
        main.post { listeners.forEach { it(e) } }
    }
}
