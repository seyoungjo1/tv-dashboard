package com.seyoungjo.tvdashboard.ui

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import com.seyoungjo.tvdashboard.data.AppSettings
import com.seyoungjo.tvdashboard.update.UpdateManager
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/** '업데이트 확인' → 버전·변경사항 표시 → 다운로드 → Android 설치 화면 */
object UpdateUi {
    private val main = Handler(Looper.getMainLooper())
    private var promptShowing = false

    fun checkForUpdate(a: Activity) {
        val (dialog, bar, label) = progressDialog(a, "업데이트 확인 중…")
        bar.isIndeterminate = true
        val url = AppSettings.updateUrl
        thread(name = "update-check") {
            val result = runCatching { UpdateManager.fetchInfo(url) }
            main.post {
                dialog.dismiss()
                if (a.isFinishing) return@post
                result.onFailure { e ->
                    alert(a, "업데이트 확인 실패", "${e.message}\n\n주소: $url\n\n기존 버전을 계속 사용합니다.")
                }.onSuccess { info ->
                    val cur = UpdateManager.currentVersionName(a)
                    if (!UpdateManager.isNewer(a, info)) {
                        alert(a, "최신 버전입니다", "현재 버전: $cur\n배포된 버전: ${info.versionName}")
                    } else {
                        AlertDialog.Builder(a)
                            .setTitle("새 버전 ${info.versionName}")
                            .setMessage("현재 버전: $cur\n\n변경사항\n${info.notes.ifBlank { "(내용 없음)" }}")
                            .setPositiveButton("다운로드 후 설치") { _, _ -> ensureInstallPermission(a) { download(a, info) } }
                            .setNegativeButton("나중에", null)
                            .show()
                    }
                }
                label.text = ""
            }
        }
    }

    private fun download(a: Activity, info: UpdateManager.UpdateInfo) {
        val cancel = AtomicBoolean(false)
        val (dialog, bar, label) = progressDialog(a, "다운로드 중… ${info.versionName}") { cancel.set(true) }
        bar.isIndeterminate = false
        bar.max = 1000
        thread(name = "update-download") {
            val result = runCatching {
                UpdateManager.download(a.applicationContext, info, { done, total ->
                    main.post {
                        if (total > 0) bar.progress = (done * 1000 / total).toInt() else bar.isIndeterminate = true
                        label.text = "%.1f MB".format(done / 1048576.0) + if (total > 0) " / %.1f MB".format(total / 1048576.0) else ""
                    }
                }, { cancel.get() })
            }
            main.post {
                dialog.dismiss()
                result.onFailure { e -> alert(a, "다운로드 실패", "${e.message}\n\n기존 버전을 계속 사용합니다.") }
                    .onSuccess { f -> startInstall(a, f) }
            }
        }
    }

    /** 관리 웹에서 업로드된 APK 설치 확인 */
    fun promptInstall(a: Activity, apk: File, versionName: String, reason: String) {
        if (promptShowing) return
        promptShowing = true
        AlertDialog.Builder(a)
            .setTitle("새 버전 $versionName 설치")
            .setMessage("$reason\n현재 버전: ${UpdateManager.currentVersionName(a)}\n\n지금 설치할까요? (자료와 설정은 유지됩니다)")
            .setPositiveButton("설치") { _, _ -> ensureInstallPermission(a) { startInstall(a, apk) } }
            .setNegativeButton("나중에", null)
            .setNeutralButton("삭제") { _, _ -> apk.delete() }
            .setOnDismissListener { promptShowing = false }
            .show()
    }

    private fun startInstall(a: Activity, apk: File) {
        try {
            UpdateManager.install(a.applicationContext, apk)
            Toast.makeText(a, "설치 화면에서 '업데이트(설치)'를 눌러 주세요.", Toast.LENGTH_LONG).show()
        } catch (e: Exception) {
            alert(a, "설치 실패", "${e.message}\n\n기존 버전을 계속 사용합니다.")
        }
    }

    fun ensureInstallPermission(a: Activity, then: () -> Unit) {
        if (UpdateManager.canInstall(a)) { then(); return }
        AlertDialog.Builder(a)
            .setTitle("설치 권한 필요")
            .setMessage("업데이트를 설치하려면 이 앱에 '출처를 알 수 없는 앱 설치' 권한을 허용해야 합니다.\n\n설정 화면에서 허용한 뒤 다시 시도하세요.\n(관리자 설정에서 앱 설치가 막혀 있으면 기기 관리자에게 문의하세요.)")
            .setPositiveButton("설정 열기") { _, _ -> openUnknownSources(a) }
            .setNegativeButton("취소", null)
            .show()
    }

    fun openUnknownSources(a: Activity) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        try {
            a.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${a.packageName}")))
        } catch (e: ActivityNotFoundException) {
            Toast.makeText(a, "이 기기에서는 해당 설정 화면을 열 수 없습니다. Android 설정 > 앱 > 특별한 앱 접근에서 허용하세요.", Toast.LENGTH_LONG).show()
        }
    }

    private fun progressDialog(
        a: Activity, title: String, onCancel: (() -> Unit)? = null
    ): Triple<AlertDialog, ProgressBar, TextView> {
        val pad = (24 * a.resources.displayMetrics.density).toInt()
        val bar = ProgressBar(a, null, android.R.attr.progressBarStyleHorizontal)
        val label = TextView(a)
        val box = LinearLayout(a).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad / 2, pad, 0)
            addView(bar)
            addView(label)
        }
        val b = AlertDialog.Builder(a).setTitle(title).setView(box).setCancelable(false)
        if (onCancel != null) b.setNegativeButton("취소") { _, _ -> onCancel() }
        val d = b.create()
        d.show()
        return Triple(d, bar, label)
    }

    fun alert(a: Activity, title: String, msg: String) {
        if (a.isFinishing) return
        AlertDialog.Builder(a).setTitle(title).setMessage(msg).setPositiveButton("확인", null).show()
    }
}
