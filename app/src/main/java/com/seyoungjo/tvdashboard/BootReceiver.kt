package com.seyoungjo.tvdashboard

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Settings
import android.util.Log
import com.seyoungjo.tvdashboard.data.AppSettings
import com.seyoungjo.tvdashboard.server.ServerService
import com.seyoungjo.tvdashboard.ui.MainActivity

/**
 * 재부팅 / 앱 업데이트 직후 자동 실행.
 *  - 서버(포그라운드 서비스)는 항상 시작 가능 (BOOT_COMPLETED·MY_PACKAGE_REPLACED 예외 허용)
 *  - 화면(액티비티)은 Android 10+ 백그라운드 실행 제한 때문에
 *    '다른 앱 위에 표시' 권한이 있을 때만 자동으로 띄웁니다.
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val action = intent.action ?: return
        val boot = action == Intent.ACTION_BOOT_COMPLETED
        val updated = action == Intent.ACTION_MY_PACKAGE_REPLACED
        if (!boot && !updated) return
        if (boot && !AppSettings.autoStart) return
        Log.i("BootReceiver", "auto start: $action")
        ServerService.start(context)
        if (Settings.canDrawOverlays(context)) {
            try {
                context.startActivity(
                    Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                )
            } catch (e: Exception) {
                Log.w("BootReceiver", "activity start blocked", e)
            }
        }
    }
}
