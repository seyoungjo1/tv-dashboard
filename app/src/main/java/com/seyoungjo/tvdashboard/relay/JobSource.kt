package com.seyoungjo.tvdashboard.relay

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.io.OutputStream
import java.security.MessageDigest

/**
 * 작업이 어디서 왔든(GitHub 우편함 · 블루투스) RelayWorker 가 같은 방식으로 처리하도록 하는 입구.
 *  · open       작업 목록(m)을 풀어 돌려준다 + 조각 이름 → 위치
 *  · readChunks 파일 조각들을 순서대로 풀어 out 에 쓴다
 *  · writeResult 결과(+내려받기 파일)를 그 작업의 키로 암호화해 둔다
 *  · deleteJob  작업을 지운다
 */
interface JobSource {
    val tv: String
    fun open(job: RelayClient.Job): Pair<JSONObject, Map<String, String>>
    fun readChunks(job: RelayClient.Job, files: Map<String, String>, names: JSONArray, out: OutputStream): Pair<Long, String>
    fun writeResult(id: String, result: JSONObject, attachments: List<Pair<JSONObject, File>> = emptyList(), key: RelayCrypto? = null)
    fun deleteJob(job: RelayClient.Job)
}

/**
 * 블루투스 등으로 받아 폴더에 둔 작업 — dir/m, dir/d0… (GitHub 과 같은 암호화 봉투·AAD).
 * 결과는 dir/res-m, dir/res-d0… 에 쓴다 (resultFiles 순서대로 보낸다).
 */
class LocalJobSource(override val tv: String, private val crypto: RelayCrypto, val dir: File) : JobSource {
    val resultFiles = ArrayList<Pair<String, File>>()

    private fun cryptoOf(job: RelayClient.Job) = job.key ?: crypto

    override fun open(job: RelayClient.Job): Pair<JSONObject, Map<String, String>> {
        val files = LinkedHashMap<String, String>()
        dir.listFiles()?.filter { it.isFile && !it.name.startsWith("res-") }?.sortedBy { it.name }?.forEach { files[it.name] = it.path }
        val m = files["m"] ?: throw SecurityException("작업에 목록(m)이 없습니다.")
        val plain = cryptoOf(job).open(File(m).readBytes(), RelayCrypto.aad(tv, job.kind, job.id, "m"))
        return JSONObject(plain.toString(Charsets.UTF_8)) to files
    }

    override fun readChunks(job: RelayClient.Job, files: Map<String, String>, names: JSONArray, out: OutputStream): Pair<Long, String> {
        val md = MessageDigest.getInstance("SHA-256")
        var total = 0L
        for (i in 0 until names.length()) {
            val name = names.getString(i)
            val path = files[name] ?: throw SecurityException("작업에 조각 $name 이 없습니다.")
            val plain = cryptoOf(job).open(File(path).readBytes(), RelayCrypto.aad(tv, job.kind, job.id, name))
            out.write(plain)
            md.update(plain)
            total += plain.size
        }
        return total to md.digest().joinToString("") { "%02x".format(it) }
    }

    override fun writeResult(id: String, result: JSONObject, attachments: List<Pair<JSONObject, File>>, key: RelayCrypto?) {
        val c = key ?: crypto
        var n = 0
        for ((entry, file) in attachments) {
            val names = JSONArray()
            val md = MessageDigest.getInstance("SHA-256")
            FileInputStream(file).use { input ->
                val buf = ByteArray(RelayClient.CHUNK)
                while (true) {
                    val len = readFully(input, buf)
                    if (len <= 0) break
                    val plain = if (len == buf.size) buf.copyOf() else buf.copyOf(len)
                    md.update(plain)
                    val name = "d${n++}"
                    val f = File(dir, "res-$name")
                    FileOutputStream(f).use { it.write(c.seal(plain, RelayCrypto.aad(tv, "res", id, name))) }
                    resultFiles.add(name to f)
                    names.put(name)
                    if (len < buf.size) break
                }
            }
            entry.put("chunks", names).put("size", file.length())
                .put("sha256", md.digest().joinToString("") { "%02x".format(it) })
        }
        val m = File(dir, "res-m")
        FileOutputStream(m).use { it.write(c.seal(result.toString().toByteArray(Charsets.UTF_8), RelayCrypto.aad(tv, "res", id, "m"))) }
        resultFiles.add(0, "m" to m)
    }

    override fun deleteJob(job: RelayClient.Job) {
        dir.listFiles()?.filter { !it.name.startsWith("res-") }?.forEach { it.delete() }
    }

    /** 결과까지 보낸 뒤 전부 지운다 */
    fun cleanup() {
        dir.deleteRecursively()
    }

    companion object {
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
