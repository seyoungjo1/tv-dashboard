package com.seyoungjo.tvdashboard.update

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.util.Log
import android.widget.Toast
import androidx.core.content.IntentCompat

/** PackageInstaller 결과 → 사용자 승인 화면 표시 / 실패 안내 */
class InstallResultReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)
        val msg = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE)
        Log.i("InstallResult", "status=$status msg=$msg")
        when (status) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                val confirm = IntentCompat.getParcelableExtra(intent, Intent.EXTRA_INTENT, Intent::class.java)
                if (confirm != null) {
                    confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    try {
                        context.startActivity(confirm)
                    } catch (e: Exception) {
                        toast(context, "설치 화면을 열 수 없습니다: ${e.message}")
                    }
                }
            }
            PackageInstaller.STATUS_SUCCESS -> toast(context, "업데이트가 설치되었습니다.")
            PackageInstaller.STATUS_FAILURE_ABORTED -> toast(context, "업데이트를 취소했습니다. 기존 버전을 계속 사용합니다.")
            else -> toast(context, "업데이트 설치 실패: ${msg ?: status}\n기존 버전을 계속 사용합니다.")
        }
    }

    private fun toast(c: Context, s: String) = Toast.makeText(c.applicationContext, s, Toast.LENGTH_LONG).show()
}
