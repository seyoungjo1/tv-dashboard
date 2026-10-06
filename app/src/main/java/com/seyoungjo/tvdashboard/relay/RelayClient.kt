package com.seyoungjo.tvdashboard.relay

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileInputStream
import java.io.OutputStream
import java.security.MessageDigest

/**
 * 중계 프로토콜 (TV 쪽) — PC 의 tvrelay/relay.py 와 짝.
 *
 * 브랜치 (모두 부모 없는 커밋 1개):
 *   relay/<tv>/job/<id>   PC → TV  작업      m = 암호화된 작업 목록, d0,d1… = 암호화된 파일 조각
 *   relay/<tv>/res/<id>   TV → PC  결과      m = 암호화된 결과,   d0…   = (내려받기 요청 시) 파일 조각
 *   relay/<tv>/state      TV → PC  상태      m = 암호화된 상태(파일 목록·설정·버전·시각)
 *   relay/<tv>/up/<gid>/<id>  직원 업로드 도구 → TV  (그 폴더 전용 키로 암호화, 결과도 같은 키로 res/<id>)
 * TV 는 작업을 반영한 뒤 job 브랜치를 지우고, PC 는 결과를 읽은 뒤 res 브랜치를 지운다 → 레포에는 아무것도 남지 않는다.
 * id = "<epoch ms>-<임의>" (시간순 정렬·오래된 결과 정리용).
 */
class RelayClient(
    private val api: GitHubApi,
    private val crypto: RelayCrypto,
    val tv: String,
) {
    /** kind = "job" (관리자) 또는 "up/<gid>" (직원 업로드 도구). key = 그 작업을 푸는 키 (null 이면 관리자 키) */
    data class Job(
        val id: String, val branch: String, val commit: String,
        val kind: String = "job", val gid: String? = null, val key: RelayCrypto? = null,
    )

    private var jobsEtag: String? = null
    private var upsEtag: String? = null

    private fun cryptoOf(job: Job) = job.key ?: crypto

    private fun prefix(kind: String) = "relay/$tv/$kind/"

    /** 처리할 작업 (오래된 것부터). 지난번과 같으면(304, 호출 한도 차감 없음) 빈 목록 */
    fun pendingJobs(): List<Job> {
        val r = api.matchingRefs(prefix("job"), jobsEtag) ?: return emptyList()
        jobsEtag = r.second
        return r.first.map { (branch, sha) -> Job(branch.substringAfterLast('/'), branch, sha) }
            .filter { ID.matches(it.id) }
            .sortedBy { it.id }
    }

    /** 직원 업로드 도구에서 온 작업 (relay/<tv>/up/<gid>/<id>). key 는 아직 비어 있다 — gid 로 찾아 채운다 */
    fun pendingUploads(): List<Job> {
        val r = api.matchingRefs(prefix("up"), upsEtag) ?: return emptyList()
        upsEtag = r.second
        return r.first.mapNotNull { (branch, sha) ->
            val parts = branch.removePrefix(prefix("up")).split('/')
            if (parts.size != 2 || !ID.matches(parts[1])) null
            else Job(parts[1], branch, sha, kind = "up/${parts[0]}", gid = parts[0])
        }.sortedBy { it.id }
    }

    /** 작업 하나 열기: (작업 목록, 조각 이름 → blob SHA) */
    fun open(job: Job): Pair<JSONObject, Map<String, String>> {
        val files = api.commitFiles(job.commit)
        val m = files["m"] ?: throw SecurityException("작업에 목록(m)이 없습니다.")
        val plain = cryptoOf(job).open(api.blob(m), RelayCrypto.aad(tv, job.kind, job.id, "m"))
        return JSONObject(plain.toString(Charsets.UTF_8)) to files
    }

    /** 작업의 파일 조각들을 순서대로 풀어 out 에 쓴다. 돌려주는 값: (바이트 수, SHA-256) */
    fun readChunks(job: Job, files: Map<String, String>, names: JSONArray, out: OutputStream): Pair<Long, String> {
        val md = MessageDigest.getInstance("SHA-256")
        var total = 0L
        for (i in 0 until names.length()) {
            val name = names.getString(i)
            val sha = files[name] ?: throw SecurityException("작업에 조각 $name 이 없습니다.")
            val plain = cryptoOf(job).open(api.blob(sha), RelayCrypto.aad(tv, job.kind, job.id, name))
            out.write(plain)
            md.update(plain)
            total += plain.size
        }
        return total to md.digest().joinToString("") { "%02x".format(it) }
    }

    fun deleteJob(job: Job) = api.deleteBranch(job.branch)

    /** 결과 올리기. attachments: 결과에 붙일 파일(내려받기 요청) — 조각 이름은 결과 JSON 의 chunks 에 들어간다 */
    fun writeResult(
        id: String, result: JSONObject, attachments: List<Pair<JSONObject, File>> = emptyList(), key: RelayCrypto? = null,
    ) {
        val crypto = key ?: this.crypto
        val files = LinkedHashMap<String, ByteArray>()
        var n = 0
        for ((entry, file) in attachments) {
            val names = JSONArray()
            val md = MessageDigest.getInstance("SHA-256")
            FileInputStream(file).use { input ->
                val buf = ByteArray(CHUNK)
                while (true) {
                    val len = readFully(input, buf)
                    if (len <= 0) break
                    val plain = if (len == buf.size) buf.copyOf() else buf.copyOf(len)
                    md.update(plain)
                    val name = "d${n++}"
                    files[name] = crypto.seal(plain, RelayCrypto.aad(tv, "res", id, name))
                    names.put(name)
                    if (len < buf.size) break
                }
            }
            entry.put("chunks", names).put("size", file.length())
                .put("sha256", md.digest().joinToString("") { "%02x".format(it) })
        }
        files["m"] = crypto.seal(result.toString().toByteArray(Charsets.UTF_8), RelayCrypto.aad(tv, "res", id, "m"))
        val commit = api.createOrphanCommit(files, "res")
        api.replaceBranch(prefix("res") + id, commit)
    }

    fun publishState(state: JSONObject) {
        val m = crypto.seal(state.toString().toByteArray(Charsets.UTF_8), RelayCrypto.aad(tv, "state", "state", "m"))
        val commit = api.createOrphanCommit(mapOf("m" to m), "state")
        api.replaceBranch("relay/$tv/state", commit)
    }

    /** PC 가 가져가지 않은 오래된 결과·작업 정리 */
    fun cleanup(maxAgeMs: Long, now: Long = System.currentTimeMillis()) {
        for (kind in listOf("res", "job", "up")) {
            val refs = api.matchingRefs(prefix(kind), null)?.first ?: continue
            for ((branch, _) in refs) {
                val id = branch.substringAfterLast('/')
                val t = id.substringBefore('-').toLongOrNull() ?: continue
                if (now - t > maxAgeMs) api.deleteBranch(branch)
            }
        }
    }

    companion object {
        const val CHUNK = 8 * 1024 * 1024
        val ID = Regex("""^\d{13}-[0-9a-f]{6,32}$""")

        private fun readFully(input: java.io.InputStream, buf: ByteArray): Int {
            var off = 0
            while (off < buf.size) {
                val n = input.read(buf, off, buf.size - off)
                if (n < 0) break
                off += n
            }
            return off
        }
    }
}
