package com.seyoungjo.tvdashboard.relay

import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.EOFException
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream

/**
 * 블루투스(RFCOMM 직렬) 위의 작업 꾸러미 형식 — PC(tvrelay/bt.py)·직원 HTML(uploader.html) 과 짝.
 * GitHub 우편함에 올리던 파일(m · d0…)을 그대로 한 줄로 이어 보낸다. 내용은 같은 키·같은 AAD 로 암호화되어 있다.
 *
 *   보내는 쪽 →  "TVBT1"  그리고 기록들:  nameLen(1) | name | len(4, big-endian) | payload … | nameLen 0 (끝)
 *     첫 기록 "h" = 평문 JSON {"v":1,"tv":"osan1","kind":"job" 또는 "up/<gid>","id":"<epoch>-<hex>"}  (GitHub 의 브랜치 이름 역할)
 *     그다음 "m" (암호화된 작업 목록), "d0","d1"… (암호화된 파일 조각)
 *   TV →         "TVBT1"  "m" (암호화된 결과), "d0"… (내려받기 조각) | nameLen 0
 *     처리 전에 거절하면 "e" = 평문 JSON {"error":"…"} 하나와 끝.
 */
object BtProtocol {
    val MAGIC = "TVBT1".toByteArray(Charsets.US_ASCII)
    const val MAX_RECORD = RelayClient.CHUNK + 64            // 암호화 봉투(28바이트)까지
    const val MAX_RECORDS = 4000
    val NAME = Regex("^(h|m|e|d\\d{1,4})$")

    class BadStream(message: String) : IOException(message)

    fun readMagic(input: DataInputStream) {
        val b = ByteArray(MAGIC.size)
        try { input.readFully(b) } catch (e: EOFException) { throw BadStream("연결이 끊겼습니다") }
        if (!b.contentEquals(MAGIC)) throw BadStream("블루투스 꾸러미 형식이 아닙니다")
    }

    fun writeMagic(out: OutputStream) = out.write(MAGIC)

    /** 기록 하나의 머리(이름·길이). 끝 표시면 null */
    fun readHead(input: DataInputStream): Pair<String, Int>? {
        val n = input.read()
        if (n < 0) throw BadStream("연결이 끊겼습니다")
        if (n == 0) return null
        val nb = ByteArray(n); input.readFully(nb)
        val name = nb.toString(Charsets.UTF_8)
        if (!NAME.matches(name)) throw BadStream("잘못된 기록 이름: $name")
        val len = input.readInt()
        if (len < 0 || len > MAX_RECORD) throw BadStream("기록이 너무 큽니다: $name $len")
        return name to len
    }

    fun readBody(input: DataInputStream, len: Int): ByteArray {
        val b = ByteArray(len); input.readFully(b); return b
    }

    /** 본문을 파일로 (큰 조각을 메모리에 들지 않게). onProgress 는 받은 바이트마다 */
    fun readBodyTo(input: DataInputStream, len: Int, file: File, onProgress: (() -> Unit)? = null) {
        val buf = ByteArray(32 * 1024)
        var left = len
        FileOutputStream(file).use { out ->
            while (left > 0) {
                val n = input.read(buf, 0, minOf(buf.size, left))
                if (n < 0) throw BadStream("연결이 끊겼습니다 (${file.name})")
                out.write(buf, 0, n); left -= n
                onProgress?.invoke()
            }
        }
    }

    fun writeRecord(out: DataOutputStream, name: String, payload: ByteArray) {
        val nb = name.toByteArray(Charsets.UTF_8)
        out.write(nb.size); out.write(nb); out.writeInt(payload.size); out.write(payload)
    }

    fun writeRecord(out: DataOutputStream, name: String, file: File) {
        val nb = name.toByteArray(Charsets.UTF_8)
        out.write(nb.size); out.write(nb); out.writeInt(file.length().toInt())
        file.inputStream().use { it.copyTo(out, 64 * 1024) }
    }

    fun writeEnd(out: DataOutputStream) { out.write(0); out.flush() }
}
