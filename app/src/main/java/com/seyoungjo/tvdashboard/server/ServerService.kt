package com.seyoungjo.tvdashboard.server

import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.wifi.WifiManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.seyoungjo.tvdashboard.R
import com.seyoungjo.tvdashboard.data.AppSettings
import com.seyoungjo.tvdashboard.relay.RelayWorker
import com.seyoungjo.tvdashboard.ui.MainActivity

/**
 * 파일 관리 웹서버를 포그라운드 서비스로 유지합니다.
 * 화면(액티비티)이 닫히거나 화면이 꺼져도 서버는 계속 동작합니다.
 * (TV 전원이 '대기/절전'으로 들어가 SoC·네트워크가 꺼지는 경우는 앱이 막을 수 없습니다 → 문서 참고)
 */
class ServerService : Service() {

    private var server: AdminServer? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createChannel()
        acquireLocks()
        RelayWorker.start(this)     // GitHub 원격 중계 (설정돼 있을 때만 동작)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        goForeground()
        if (intent?.action == ACTION_RESTART || server == null || server?.isAlive != true) {
            startServer()
        }
        return START_STICKY
    }

    private fun startServer() {
        server?.stop()
        val port = AppSettings.port
        try {
            val s = AdminServer(applicationContext, port)
            s.start(60_000, false)
            server = s
            runningPort = port
            lastError = null
            Log.i(TAG, "server started on $port")
        } catch (e: Exception) {
            server = null
            runningPort = 0
            lastError = "포트 $port 서버 시작 실패: ${e.message}"
            Log.e(TAG, "server start failed", e)
        }
        goForeground()
    }

    override fun onDestroy() {
        server?.stop()
        server = null
        runningPort = 0
        wakeLock?.takeIf { it.isHeld }?.release()
        wifiLock?.takeIf { it.isHeld }?.release()
        super.onDestroy()
    }

    @SuppressLint("WakelockTimeout")
    @Suppress("DEPRECATION")
    private fun acquireLocks() {
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "tvdashboard:server").apply {
            setReferenceCounted(false); acquire()
        }
        val wm = applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
        wifiLock = wm?.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "tvdashboard:server")?.apply {
            setReferenceCounted(false); acquire()
        }
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val nm = getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL, getString(R.string.server_channel), NotificationManager.IMPORTANCE_LOW)
            )
        }
    }

    private fun goForeground() {
        val pi = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val text = if (runningPort > 0) {
            val ips = NetInfo.addresses().joinToString("  ") { "http://${it.ip}:$runningPort" }
            ips.ifEmpty { "포트 $runningPort" }
        } else lastError ?: "시작 중"
        val n: Notification = NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_settings)
            .setContentTitle(getString(R.string.server_running))
            .setContentText(text)
            .setOngoing(true)
            .setContentIntent(pi)
            .build()
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(NOTI_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(NOTI_ID, n)
        }
    }

    companion object {
        private const val TAG = "ServerService"
        private const val CHANNEL = "server"
        private const val NOTI_ID = 1
        const val ACTION_RESTART = "restart"

        @Volatile var runningPort = 0
            private set
        @Volatile var lastError: String? = null
            private set

        fun start(ctx: Context) {
            try {
                ContextCompat.startForegroundService(ctx, Intent(ctx, ServerService::class.java))
            } catch (e: Exception) {
                lastError = "서비스 시작 실패: ${e.message}"
                Log.e(TAG, "start failed", e)
            }
        }

        fun restart(ctx: Context) {
            try {
                ContextCompat.startForegroundService(
                    ctx, Intent(ctx, ServerService::class.java).setAction(ACTION_RESTART)
                )
            } catch (e: Exception) {
                Log.e(TAG, "restart failed", e)
            }
        }
    }
}
