package com.seyoungjo.tvdashboard.relay

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.File
import java.nio.file.Files

/** 블루투스 꾸러미: PC/HTML 이 보내는 형식 → 기록 읽기 → LocalJobSource 로 GitHub 과 같은 처리 → 결과 돌려보내기 */
class BtProtocolTest {
    private val key = java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(ByteArray(32) { it.toByte() })
    private val crypto = RelayCrypto(key)
    private val tv = "osan1"
    private val id = "1700000000000-abcdef012345"

    /** PC 쪽(bt.py)이 만드는 것과 같은 바이트열 */
    private fun clientPackage(kind: String, ops: JSONArray, chunks: Map<String, ByteArray>): ByteArray {
        val bo = ByteArrayOutputStream(); val out = DataOutputStream(bo)
        BtProtocol.writeMagic(out)
        BtProtocol.writeRecord(out, "h", JSONObject().put("v", 1).put("tv", tv).put("kind", kind).put("id", id).toString().toByteArray())
        val man = JSONObject().put("v", 1).put("id", id).put("ops", ops).toString().toByteArray()
        BtProtocol.writeRecord(out, "m", crypto.seal(man, RelayCrypto.aad(tv, kind, id, "m")))
        for ((name, data) in chunks) BtProtocol.writeRecord(out, name, crypto.seal(data, RelayCrypto.aad(tv, kind, id, name)))
        BtProtocol.writeEnd(out)
        return bo.toByteArray()
    }

    /** TV 쪽(BtServer.handle)이 하는 것: 기록을 폴더로 */
    private fun receive(bytes: ByteArray, dir: File): JSONObject {
        val input = DataInputStream(ByteArrayInputStream(bytes))
        BtProtocol.readMagic(input)
        val head = BtProtocol.readHead(input)!!
        assertEquals("h", head.first)
        val h = JSONObject(BtProtocol.readBody(input, head.second).toString(Charsets.UTF_8))
        while (true) {
            val r = BtProtocol.readHead(input) ?: break
            BtProtocol.readBodyTo(input, r.second, File(dir, r.first))
        }
        return h
    }

    @Test fun packageRoundTripThroughLocalJobSource() {
        val dir = Files.createTempDirectory("bt").toFile()
        val data = ByteArray(100_000) { (it % 251).toByte() }
        val ops = JSONArray().put(JSONObject().put("op", "put").put("path", "a/x.bin").put("chunks", JSONArray().put("d0")).put("size", data.size))
        val h = receive(clientPackage("job", ops, mapOf("d0" to data)), dir)
        assertEquals("job", h.getString("kind")); assertEquals(id, h.getString("id")); assertEquals(tv, h.getString("tv"))
        val src = LocalJobSource(tv, crypto, dir)
        val job = RelayClient.Job(id, "", "", kind = "job")
        val (manifest, files) = src.open(job)
        assertEquals("a/x.bin", manifest.getJSONArray("ops").getJSONObject(0).getString("path"))
        val out = ByteArrayOutputStream()
        val (n, sha) = src.readChunks(job, files, JSONArray().put("d0"), out)
        assertEquals(data.size.toLong(), n); assertTrue(out.toByteArray().contentEquals(data)); assertEquals(64, sha.length)
        // 결과 + 내려받기 파일 → res-m, res-d0 (PC 가 같은 AAD 로 푼다)
        val att = File(dir, "get-1").apply { writeBytes("hello".toByteArray()) }
        val entry = JSONObject().put("op", "get").put("path", "a/x.bin").put("ok", true)
        src.writeResult(id, JSONObject().put("ok", true).put("results", JSONArray().put(entry)), listOf(entry to att))
        assertEquals(listOf("m", "d0"), src.resultFiles.map { it.first })
        val res = JSONObject(crypto.open(src.resultFiles[0].second.readBytes(), RelayCrypto.aad(tv, "res", id, "m")).toString(Charsets.UTF_8))
        assertTrue(res.getBoolean("ok"))
        assertEquals("d0", res.getJSONArray("results").getJSONObject(0).getJSONArray("chunks").getString(0))
        assertEquals("hello", crypto.open(src.resultFiles[1].second.readBytes(), RelayCrypto.aad(tv, "res", id, "d0")).toString(Charsets.UTF_8))
        src.deleteJob(job)
        assertNull(dir.listFiles()?.firstOrNull { it.name == "m" })
        src.cleanup()
        assertTrue(!dir.exists())
    }

    @Test fun wrongKeyOrBadStreamIsRejected() {
        val dir = Files.createTempDirectory("bt").toFile()
        receive(clientPackage("up/abcd1234", JSONArray(), emptyMap()), dir)
        val other = RelayCrypto(java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(ByteArray(32) { 7 }))
        assertThrows(SecurityException::class.java) { LocalJobSource(tv, other, dir).open(RelayClient.Job(id, "", "", kind = "up/abcd1234")) }
        // 다른 종류(kind)로 받은 꾸러미는 AAD 가 달라 풀리지 않는다
        assertThrows(SecurityException::class.java) { LocalJobSource(tv, crypto, dir).open(RelayClient.Job(id, "", "", kind = "job")) }
        val bad = DataInputStream(ByteArrayInputStream("HELLO".toByteArray()))
        assertThrows(BtProtocol.BadStream::class.java) { BtProtocol.readMagic(bad) }
        val badName = ByteArrayOutputStream().also { val o = DataOutputStream(it); o.write(3); o.write("abc".toByteArray()); o.writeInt(1) }
        assertThrows(BtProtocol.BadStream::class.java) { BtProtocol.readHead(DataInputStream(ByteArrayInputStream(badName.toByteArray()))) }
    }
}
