package com.seyoungjo.tvdashboard.relay

import android.content.Context
import android.util.Log
import com.seyoungjo.tvdashboard.data.AppEvent
import com.seyoungjo.tvdashboard.data.AppSettings
import com.seyoungjo.tvdashboard.data.ChangeBus
import com.seyoungjo.tvdashboard.data.FileOps
import com.seyoungjo.tvdashboard.update.UpdateManager
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.util.UUID

/**
 * 원격 중계 루프 (ServerService 안에서 상주).
 * interval 초마다 GitHub 중계 레포의 relay/<tv>/job/… 를 확인 → 암호를 풀어 TV 자료 폴더에 반영 → 결과 올림 → 작업 브랜치 삭제.
 * 자료 폴더가 바뀌면(또는 5분마다) 파일 목록·상태를 relay/<tv>/state 로 올린다.
 * 인터넷이 끊기거나 GitHub 이 안 되면 조용히 다음 주기에 다시 시도한다 (TV 화면에는 영향 없음).
 */
object RelayWorker {
    private const val TAG = "RelayWorker"
    private const val HEARTBEAT_MS = 5 * 60_000L
    private const val CLEANUP_MS = 10 * 60_000L
    private const val RESULT_MAX_AGE_MS = 60 * 60_000L

    @Volatile var status: String = "꺼짐"
        private set
    @Volatile var lastSync: Long = 0
        private set

    private val lock = Object()
    @Volatile private var thread: Thread? = null
    @Volatile private var kicked = false
    private var client: RelayClient? = null
    private var clientKey = ""
    private var lastState = ""
    private var lastStateAt = 0L
    private var lastCleanup = 0L
    @Volatile private var stateDirty = true
    private val busListener: (AppEvent) -> Unit = { if (it is AppEvent.Changed || it is AppEvent.SettingsChanged) stateDirty = true }

    fun start(ctx: Context) {
        if (thread?.isAlive == true) return
        val app = ctx.applicationContext
        ChangeBus.add(busListener)
        thread = Thread({ loop(app) }, "relay").apply { isDaemon = true; start() }
    }

    /** 설정이 바뀌었을 때 바로 한 번 돌게 한다 */
    fun kick() {
        synchronized(lock) { kicked = true; lock.notifyAll() }
    }

    private fun loop(ctx: Context) {
        while (true) {
            var wait = 30_000L
            try {
                if (!RelaySettings.enabled) status = "꺼짐"
                else if (!RelaySettings.configured) {
                    // 아직 연결 전: PC 프로그램에 연결 코드를 넣으면 레포에서 연결 정보를 스스로 받아 온다
                    status = "연결 대기 — PC 프로그램에 연결 코드 ${Pairing.code} 입력"
                    if (Pairing.pollOnce(RelaySettings.repo)) {
                        status = "연결됨 — 첫 동기화 중"
                        wait = 500L
                    } else wait = 15_000L
                } else {
                    cycle(ctx)
                    wait = RelaySettings.intervalSec * 1000L
                }
            } catch (e: Throwable) {
                status = "오류: ${e.message ?: e.javaClass.simpleName}"
                Log.w(TAG, "cycle failed", e)
                client = null
                wait = maxOf(RelaySettings.intervalSec * 1000L, 30_000L)
            }
            synchronized(lock) {
                if (!kicked) try { lock.wait(wait) } catch (_: InterruptedException) {}
                kicked = false
            }
        }
    }

    private fun clientFor(): RelayClient {
        val sig = RelaySettings.repo + "|" + RelaySettings.tv + "|" + RelaySettings.key + "|" + RelaySettings.token
        if (client == null || sig != clientKey) {
            client = RelayClient(
                GitHubApi(RelaySettings.repo, RelaySettings.token), RelayCrypto(RelaySettings.key), RelaySettings.tv
            )
            clientKey = sig
            lastState = ""
        }
        return client!!
    }

    private fun cycle(ctx: Context) {
        val c = clientFor()
        val ops = FileOps(ctx)
        for (job in c.pendingJobs()) process(ctx, c, ops, job)
        for (up in c.pendingUploads()) processUpload(ctx, c, ops, up)
        val now = System.currentTimeMillis()
        if (stateDirty || now - lastStateAt > HEARTBEAT_MS) publishState(c, ops)
        if (now - lastCleanup > CLEANUP_MS) {
            lastCleanup = now
            c.cleanup(RESULT_MAX_AGE_MS)
        }
        lastSync = now
        status = "연결됨 (${RelaySettings.repo} · ${RelaySettings.tv})"
    }

    private fun publishState(c: RelayClient, ops: FileOps) {
        stateDirty = false
        val body = JSONObject()
            .put("status", ops.status())
            .put("menu", ops.menu())
            .put("settings", AppSettings.remoteJson())
            .put("tree", ops.tree())
            .put("grants", grantsJson(ops))
        val sig = body.toString()
        val now = System.currentTimeMillis()
        if (sig == lastState && now - lastStateAt < HEARTBEAT_MS) return
        c.publishState(JSONObject(sig).put("v", 1).put("time", now).put("interval", RelaySettings.intervalSec))
        lastState = sig
        lastStateAt = now
    }

    /** 관리자 화면용 업로드 도구 목록 (키는 넣지 않는다) */
    private fun grantsJson(ops: FileOps): JSONArray {
        val arr = JSONArray()
        for (g in GrantStore.all().values) {
            val used = try { ops.folderUsage(g.folder) } catch (e: Exception) { 0L }
            arr.put(JSONObject().put("gid", g.gid).put("folder", g.folder).put("name", g.name)
                .put("maxBytes", g.maxBytes).put("used", used).put("types", JSONArray(g.types.sorted())))
        }
        return arr
    }

    /**
     * 직원 업로드 도구에서 온 작업. 경로·형식 규칙(GrantPolicy)을 **전부 먼저** 검사하고, 하나라도 어긋나면 아무것도 쓰지 않는다.
     * 용량 제한은 도구(HTML)가 한 번에 30MB 로 막는다. 같은 이름 파일은 덮어쓴다.
     * 결과는 그 도구의 키로 암호화해서 돌려준다 (도구 화면이 읽는다).
     */
    private fun processUpload(ctx: Context, c: RelayClient, ops: FileOps, up: RelayClient.Job) {
        val grant = GrantStore.get(up.gid ?: "")
        if (grant == null) {                               // 폐기됐거나 모르는 도구 — 풀 수도 없으므로 지운다
            Log.w(TAG, "drop upload ${up.id}: unknown gid ${up.gid}")
            c.deleteJob(up)
            return
        }
        val key = RelayCrypto(grant.key)
        val job = up.copy(key = key)
        val (manifest, files) = try {
            c.open(job)
        } catch (e: SecurityException) {
            Log.w(TAG, "drop upload ${up.id}: ${e.message}")
            c.deleteJob(up)
            return
        }
        val list = manifest.optJSONArray("ops") ?: JSONArray()
        val results = JSONArray()
        var allOk = true
        try {
            val puts = ArrayList<Pair<String, Long>>()
            for (i in 0 until list.length()) {
                val op = list.getJSONObject(i)
                if (op.optString("op") != "put") throw GrantPolicy.Denied("이 도구로는 파일 올리기만 할 수 있습니다.")
                puts.add(GrantPolicy.checkPath(grant, op.getString("path")) to op.optLong("size", 0))
            }
            for (i in 0 until list.length()) {
                val op = list.getJSONObject(i)
                val r = JSONObject().put("op", "put").put("path", op.optString("path"))
                try {
                    runOp(ctx, c, ops, job, files, op.put("path", puts[i].first).put("overwrite", true), r, ArrayList())
                    r.put("ok", true)
                } catch (e: FileOps.OpError) {
                    allOk = false; r.put("ok", false).put("error", e.message)
                } catch (e: GitHubApi.ApiError) {
                    throw e
                } catch (e: Exception) {
                    allOk = false; r.put("ok", false).put("error", e.message ?: e.javaClass.simpleName)
                }
                results.put(r)
            }
        } catch (e: GrantPolicy.Denied) {
            allOk = false
            results.put(JSONObject().put("op", "put").put("ok", false).put("error", e.message))
        }
        val result = JSONObject().put("v", 1).put("id", job.id).put("ok", allOk).put("results", results)
            .put("folder", grant.folder).put("maxBytes", grant.maxBytes)
            .put("used", ops.folderUsage(grant.folder)).put("files", ops.filesIn(grant.folder))
            .put("time", System.currentTimeMillis())
        c.writeResult(job.id, result, key = key)
        c.deleteJob(up)
        stateDirty = true
        Log.i(TAG, "upload ${job.id} via ${grant.folder} ok=$allOk")
    }

    private fun process(ctx: Context, c: RelayClient, ops: FileOps, job: RelayClient.Job) {
        val (manifest, files) = try {
            c.open(job)
        } catch (e: SecurityException) {
            // 키가 다른(다른 PC 의) 작업 — 풀 수 없으므로 지운다
            Log.w(TAG, "drop job ${job.id}: ${e.message}")
            c.deleteJob(job)
            return
        }
        val results = JSONArray()
        val attachments = ArrayList<Pair<JSONObject, File>>()
        var allOk = true
        val list = manifest.optJSONArray("ops") ?: JSONArray()
        for (i in 0 until list.length()) {
            val op = list.getJSONObject(i)
            val r = JSONObject().put("op", op.optString("op")).put("path", op.optString("path"))
            try {
                runOp(ctx, c, ops, job, files, op, r, attachments)
                r.put("ok", true)
            } catch (e: FileOps.OpError) {
                allOk = false; r.put("ok", false).put("status", e.status).put("error", e.message)
            } catch (e: IllegalArgumentException) {
                allOk = false; r.put("ok", false).put("status", 400).put("error", e.message)
            } catch (e: SecurityException) {
                allOk = false; r.put("ok", false).put("status", 400).put("error", e.message)
            } catch (e: GitHubApi.ApiError) {
                throw e                                       // 네트워크 문제는 작업을 남겨 두고 다음 주기에 다시
            } catch (e: Exception) {
                allOk = false; r.put("ok", false).put("status", 500).put("error", "${e.javaClass.simpleName}: ${e.message}")
            }
            results.put(r)
        }
        val result = JSONObject().put("v", 1).put("id", job.id).put("ok", allOk).put("results", results)
            .put("time", System.currentTimeMillis())
        try {
            c.writeResult(job.id, result, attachments)
        } finally {
            attachments.forEach { it.second.takeIf { f -> f.name.startsWith("get-") }?.delete() }
        }
        c.deleteJob(job)
        stateDirty = true
        Log.i(TAG, "job ${job.id} done ok=$allOk (${list.length()} ops)")
    }

    private fun runOp(
        ctx: Context, c: RelayClient, ops: FileOps, job: RelayClient.Job, files: Map<String, String>,
        op: JSONObject, r: JSONObject, attachments: MutableList<Pair<JSONObject, File>>,
    ) {
        when (op.getString("op")) {
            "put" -> {
                val size = op.optLong("size", 0)
                ops.checkPut(op.getString("path"), op.optBoolean("overwrite", true), size)
                val tmp = ops.newTmp()
                try {
                    val (n, sha) = FileOutputStream(tmp).use { out ->
                        c.readChunks(job, files, op.optJSONArray("chunks") ?: JSONArray(), out).also { out.fd.sync() }
                    }
                    if (n != size || !sha.equals(op.optString("sha256"), true)) throw FileOps.OpError(400, "받은 파일이 손상되었습니다.")
                    r.put("path", ops.commitTmp(tmp, op.getString("path"), op.optBoolean("overwrite", true), sha))
                    r.put("size", n)
                } finally {
                    if (tmp.exists()) tmp.delete()
                }
            }
            "mkdir" -> r.put("path", ops.mkdir(op.getString("path")))
            "delete" -> ops.delete(op.getString("path"), op.optBoolean("recursive", false))
            "rename" -> r.put("path", ops.rename(op.getString("path"), op.getString("to")))
            "sample" -> r.put("path", ops.sample(op.getString("path")))
            "settings" -> {
                AppSettings.applyRemote(op.getJSONObject("values"))
                r.put("settings", AppSettings.remoteJson())
            }
            "reload" -> ChangeBus.post(AppEvent.Reload)
            "grant" -> {                                    // 직원 업로드 도구 등록 (관리자 PC 에서만)
                val g = GrantStore.put(op)
                ops.mkdir(g.folder)
                r.put("gid", g.gid).put("folder", g.folder).put("maxBytes", g.maxBytes)
            }
            "revoke" -> GrantStore.remove(op.getString("gid"))
            "ping" -> r.put("status", ops.status())
            "list" -> r.put("tree", ops.tree())
            "get" -> {
                val src = ops.file(op.getString("path"))
                // 보내는 동안 파일이 바뀌어도 섞이지 않도록 복사본에서 보낸다
                val copy = File(ctx.cacheDir, "get-" + UUID.randomUUID())
                src.copyTo(copy, overwrite = true)
                r.put("name", src.name)
                attachments.add(r to copy)
            }
            "apk" -> {
                val dir = UpdateManager.updateDir(ctx)
                val size = op.optLong("size", 0)
                ops.ensureSpace(dir, size)
                val tmp = File(dir, "relay-" + UUID.randomUUID() + ".part")
                try {
                    val (n, sha) = FileOutputStream(tmp).use { out ->
                        c.readChunks(job, files, op.optJSONArray("chunks") ?: JSONArray(), out).also { out.fd.sync() }
                    }
                    if (n != size || !sha.equals(op.optString("sha256"), true)) throw FileOps.OpError(400, "받은 APK 가 손상되었습니다.")
                    val meta = ops.acceptApk(tmp)
                    r.put("versionName", meta.versionName).put("versionCode", meta.versionCode)
                        .put("message", "TV 화면에 설치 확인 창이 표시됩니다. TV 에서 '설치'를 눌러야 업데이트됩니다.")
                } finally {
                    if (tmp.exists()) tmp.delete()
                }
            }
            else -> throw IllegalArgumentException("알 수 없는 작업: ${op.optString("op")}")
        }
    }
}
