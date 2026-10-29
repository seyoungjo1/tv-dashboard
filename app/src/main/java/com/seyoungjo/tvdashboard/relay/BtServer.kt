package com.seyoungjo.tvdashboard.relay

import android.Manifest
import android.app.Activity
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothServerSocket
import android.bluetooth.BluetoothSocket
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.util.Log
import androidx.core.content.ContextCompat
import com.seyoungjo.tvdashboard.data.AppSettings
import com.seyoungjo.tvdashboard.data.FileOps
import org.json.JSONObject
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.File
import java.io.IOException
import java.util.UUID

/**
 * 블루투스 받기 — TV 가 켜져 있는 동안 항상 RFCOMM(직렬) 서버를 열어 두고, 가까운 PC(관리자 프로그램 · 직원 HTML)가
 * 보내는 작업 꾸러미를 받아 GitHub 우편함과 **같은 규칙**(같은 키·직원 도구 권한)으로 처리한 뒤 결과를 돌려준다.
 * 인터넷·GitHub 없이 동작한다. 처음 한 번은 PC 와 짝짓기(페어링)가 필요하다 — '찾을 수 있게' 는 설정 화면/앱 시작 때 요청.
 */
object BtServer {
    private const val TAG = "BtServer"
    val SPP: UUID = UUID.fromString("00001101-0000-1000-8000-00805F9B34FB")
    const val SERVICE = "tv-dashboard"
    private const val IDLE_MS = 90_000L                     // 이만큼 아무것도 안 오면 끊는다

    @Volatile var status: String = "꺼짐"
        private set
    @Volatile var lastAt: Long = 0
        private set
    @Volatile var lastPeer: String = ""
        private set
    @Volatile var busy = false
        private set
    @Volatile var count = 0
        private set

    private val lock = Object()
    @Volatile private var thread: Thread? = null
    @Volatile private var server: BluetoothServerSocket? = null

    val enabled get() = AppSettings.prefs.getBoolean("bt_enabled", true)
    val alwaysVisible get() = AppSettings.prefs.getBoolean("bt_visible", true)

    fun adapter(ctx: Context): BluetoothAdapter? =
        (ctx.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager)?.adapter

    fun supported(ctx: Context) = adapter(ctx) != null

    fun permissions(): Array<String> =
        if (Build.VERSION.SDK_INT >= 31) arrayOf(Manifest.permission.BLUETOOTH_CONNECT, Manifest.permission.BLUETOOTH_ADVERTISE, Manifest.permission.BLUETOOTH_SCAN)
        else emptyArray()

    fun hasPermission(ctx: Context) = permissions().all { ContextCompat.checkSelfPermission(ctx, it) == PackageManager.PERMISSION_GRANTED }

    fun name(ctx: Context): String = try {
        if (hasPermission(ctx)) adapter(ctx)?.name ?: "" else ""
    } catch (e: SecurityException) { "" }

    /** 지금 다른 기기에서 찾을 수 있는 상태인가 */
    fun discoverable(ctx: Context): Boolean = try {
        hasPermission(ctx) && adapter(ctx)?.scanMode == BluetoothAdapter.SCAN_MODE_CONNECTABLE_DISCOVERABLE
    } catch (e: SecurityException) { false }

    /** '다른 기기에서 찾을 수 있게' 요청 (시스템 허용 창). 0 = 끌 때까지 계속 */
    fun requestDiscoverable(activity: Activity, seconds: Int = 0) {
        val i = Intent(BluetoothAdapter.ACTION_REQUEST_DISCOVERABLE).putExtra(BluetoothAdapter.EXTRA_DISCOVERABLE_DURATION, seconds)
        try { activity.startActivity(i) } catch (e: Exception) { Log.w(TAG, "discoverable request", e) }
    }

    @Volatile private var askedVisible = false
    @Volatile private var askedPermission = false

    /**
     * 앱(메인 화면)을 켤 때 한 번: 권한이 없으면 묻고, '항상 찾을 수 있게' 가 켜져 있으면 찾을 수 있게 요청한다.
     * 한 번 거부하면 다시 켤 때까지 묻지 않는다 (현황판을 가리지 않게).
     */
    fun autoSetup(activity: Activity) {
        if (!enabled || !supported(activity)) return
        if (!hasPermission(activity)) {
            if (askedPermission || permissions().isEmpty()) return
            askedPermission = true
            androidx.core.app.ActivityCompat.requestPermissions(activity, permissions(), PERMISSION_REQUEST)
            return
        }
        if (thread?.isAlive == true) kick()
        if (!alwaysVisible || askedVisible) return
        val ad = adapter(activity) ?: return
        if (!ad.isEnabled || discoverable(activity)) return
        askedVisible = true
        requestDiscoverable(activity, 0)
    }

    const val PERMISSION_REQUEST = 4471

    fun start(ctx: Context) {
        if (thread?.isAlive == true) return
        val app = ctx.applicationContext
        thread = Thread({ loop(app) }, "bt-server").apply { isDaemon = true; start() }
    }

    /** 설정이 바뀌면 바로 다시 (서버를 닫아 accept 를 깨운다) */
    fun kick() {
        synchronized(lock) { lock.notifyAll() }
        try { server?.close() } catch (_: IOException) {}
    }

    fun json(ctx: Context): JSONObject = JSONObject()
        .put("supported", supported(ctx)).put("enabled", enabled).put("permission", hasPermission(ctx))
        .put("on", try { adapter(ctx)?.isEnabled ?: false } catch (e: SecurityException) { false })
        .put("name", name(ctx)).put("status", status).put("lastAt", lastAt).put("lastPeer", lastPeer).put("count", count)

    private fun loop(ctx: Context) {
        while (true) {
            var wait = 30_000L
            try {
                val ad = adapter(ctx)
                when {
                    !enabled -> status = "꺼짐 (설정에서 '블루투스 받기' 를 켜세요)"
                    ad == null -> { status = "이 기기에는 블루투스가 없습니다"; wait = 120_000L }
                    !hasPermission(ctx) -> status = "권한 필요 — 앱 설정 화면의 '블루투스 받기 상태' 를 눌러 허용하세요"
                    !ad.isEnabled -> {
                        status = "블루투스가 꺼져 있습니다 — Android 설정에서 켜세요"
                        if (Build.VERSION.SDK_INT < 33) @Suppress("DEPRECATION") ad.enable()
                    }
                    else -> { serve(ctx, ad); wait = 3_000L }
                }
            } catch (e: SecurityException) {
                status = "권한 필요 — ${e.message}"
            } catch (e: Throwable) {
                status = "오류: ${e.message ?: e.javaClass.simpleName}"
                Log.w(TAG, "loop", e)
                wait = 10_000L
            }
            synchronized(lock) { try { lock.wait(wait) } catch (_: InterruptedException) {} }
        }
    }

    /** 서버를 열고 연결을 하나씩 받는다. 설정이 바뀌어 kick() 되면 닫히고 돌아간다 */
    private fun serve(ctx: Context, ad: BluetoothAdapter) {
        val wanted = AppSettings.prefs.getString("bt_name", "")?.trim().orEmpty()
        if (wanted.isNotEmpty() && ad.name != wanted) try { ad.name = wanted } catch (e: Exception) { Log.w(TAG, "setName", e) }
        val srv = ad.listenUsingRfcommWithServiceRecord(SERVICE, SPP)
        server = srv
        try {
            while (enabled) {
                status = "대기 중 — PC 에서 '${ad.name}' 와 짝짓기 후 보내면 됩니다"
                val sock = try { srv.accept() } catch (e: IOException) { break }
                handle(ctx, sock)
            }
        } finally {
            try { srv.close() } catch (_: IOException) {}
            server = null
        }
    }

    private fun handle(ctx: Context, sock: BluetoothSocket) {
        val peer = try { sock.remoteDevice?.name ?: sock.remoteDevice?.address ?: "?" } catch (e: SecurityException) { "?" }
        busy = true
        lastPeer = peer
        status = "받는 중 — $peer"
        val dir = File(ctx.cacheDir, "bt-" + UUID.randomUUID().toString().take(8)).apply { mkdirs() }
        val lastIo = java.util.concurrent.atomic.AtomicLong(System.currentTimeMillis())
        val watchdog = Thread({
            try {
                while (busy) {
                    Thread.sleep(2_000)
                    if (System.currentTimeMillis() - lastIo.get() > IDLE_MS) { Log.w(TAG, "idle, closing $peer"); try { sock.close() } catch (_: IOException) {}; break }
                }
            } catch (_: InterruptedException) {}
        }, "bt-watchdog").apply { isDaemon = true; start() }
        try {
            val input = DataInputStream(sock.inputStream.buffered(64 * 1024))
            val out = DataOutputStream(sock.outputStream.buffered(64 * 1024))
            exchange(ctx, input, out, dir, peer, allowPair = true) { lastIo.set(System.currentTimeMillis()) }
        } catch (e: Exception) {
            Log.w(TAG, "connection $peer failed: ${e.message}")
            status = "실패 — $peer: ${e.message}"
            try {
                val out = DataOutputStream(sock.outputStream)
                BtProtocol.writeMagic(out)
                BtProtocol.writeRecord(out, "e", JSONObject().put("error", e.message ?: e.javaClass.simpleName).toString().toByteArray(Charsets.UTF_8))
                BtProtocol.writeEnd(out)
            } catch (_: Exception) {}
        } finally {
            busy = false
            try { sock.close() } catch (_: IOException) {}
            dir.deleteRecursively()
        }
    }

    private val jobLock = Any()

    /**
     * 꾸러미 하나 받기 → 처리 → 결과 쓰기. 블루투스 연결과 TV 관리 서버의 POST /api/pkg(Tailscale·같은 망의 직원 앱)가 함께 쓴다.
     * allowPair: 연결 코드 짝짓기는 블루투스(TV 가까이)에서만 받는다.
     */
    fun exchange(ctx: Context, input: DataInputStream, out: DataOutputStream, dir: File, peer: String, allowPair: Boolean, tick: () -> Unit = {}) {
        BtProtocol.readMagic(input); tick()
        val head = BtProtocol.readHead(input) ?: throw BtProtocol.BadStream("머리 기록(h)이 없습니다")
        if (head.first != "h") throw BtProtocol.BadStream("첫 기록은 h 여야 합니다")
        val h = JSONObject(BtProtocol.readBody(input, head.second).toString(Charsets.UTF_8))
        val tv = h.optString("tv"); val kind = h.optString("kind"); val id = h.optString("id")
        var n = 0
        while (true) {
            val r = BtProtocol.readHead(input) ?: break
            if (++n > BtProtocol.MAX_RECORDS) throw BtProtocol.BadStream("기록이 너무 많습니다")
            BtProtocol.readBodyTo(input, r.second, File(dir, r.first), tick)
            status = "받는 중 — $peer ($n)"
        }
        tick()
        val result = try {
            synchronized(jobLock) {
                if (kind == "pair") { require(allowPair) { "연결 코드 짝짓기는 블루투스로만 할 수 있습니다" }; pair(h, dir) }
                else process(ctx, tv, kind, id, dir)
            }
        } catch (e: SecurityException) {
            null to (e.message ?: "암호키가 다릅니다")
        } catch (e: IllegalArgumentException) {
            null to (e.message ?: "잘못된 꾸러미")
        }
        BtProtocol.writeMagic(out)
        val src = result.first
        if (src == null) BtProtocol.writeRecord(out, "e", JSONObject().put("error", result.second).toString().toByteArray(Charsets.UTF_8))
        else for ((name, f) in src.resultFiles) { BtProtocol.writeRecord(out, name, f); tick() }
        BtProtocol.writeEnd(out)
        count++
        lastAt = System.currentTimeMillis()
        lastPeer = peer
        status = "마지막 받음 — $peer"
        Log.i(TAG, "done $peer $kind $id (${n} records)")
    }

    /** 연결 코드로 짝짓기 (GitHub 없이): h = {kind:"pair", pid}, m = 연결 정보(코드에서 만든 키로 암호화). 응답도 그 키로 */
    private fun pair(h: JSONObject, dir: File): Pair<LocalJobSource?, String> {
        val pid = h.optString("pid")
        require(Regex("^[0-9a-f]{16}$").matches(pid)) { "잘못된 연결 요청" }
        val m = File(dir, "m")
        require(m.isFile) { "연결 정보가 없습니다" }
        val key = Pairing.acceptLocal(pid, m.readBytes())
        val c = RelayCrypto(java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(key))
        val res = JSONObject().put("ok", true).put("tv", RelaySettings.tv).put("versionName", com.seyoungjo.tvdashboard.BuildConfig.VERSION_NAME)
        val out = File(dir, "res-m")
        out.writeBytes(c.seal(res.toString().toByteArray(Charsets.UTF_8), "pair/$pid/res"))
        val src = LocalJobSource(RelaySettings.tv, c, dir)
        src.resultFiles.add("m" to out)
        return src to ""
    }

    /** 받아 둔 꾸러미를 GitHub 우편함과 같은 코드로 처리. 돌려주는 값: (결과 파일을 가진 source, 오류) */
    private fun process(ctx: Context, tv: String, kind: String, id: String, dir: File): Pair<LocalJobSource?, String> {
        require(RelayClient.ID.matches(id)) { "작업 id 가 올바르지 않습니다" }
        require(tv == RelaySettings.tv) { "다른 TV('$tv') 로 보낸 꾸러미입니다 (이 TV: '${RelaySettings.tv}')" }
        val ops = FileOps(ctx)
        return if (kind == "job") {
            if (RelaySettings.key.isBlank()) return null to "이 TV 는 아직 PC 프로그램과 연결(암호키)되지 않았습니다"
            val src = LocalJobSource(tv, RelayCrypto(RelaySettings.key), dir)
            RelayWorker.process(ctx, src, ops, RelayClient.Job(id, "", "", kind = "job"))
            src to ""
        } else if (kind.startsWith("up/")) {
            val gid = kind.removePrefix("up/")
            val grant = GrantStore.get(gid) ?: return null to "폐기됐거나 모르는 업로드 도구입니다 (관리자에게 새 도구를 받으세요)"
            val src = LocalJobSource(tv, RelayCrypto(grant.key), dir)
            RelayWorker.processUpload(ctx, src, ops, RelayClient.Job(id, "", "", kind = kind, gid = gid))
            src to ""
        } else null to "알 수 없는 종류: $kind"
    }
}
