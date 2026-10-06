package com.seyoungjo.tvdashboard.relay

import java.security.SecureRandom
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/**
 * 중계 레포(공개)에 올라가는 모든 내용의 암호화 — PC(tvrelay/crypto.py)와 같은 형식.
 *   봉투 = "TVR1"(4) + nonce(12) + AES-256-GCM(평문) + tag(16)
 *   AAD  = "<tv>/<kind>/<id>/<name>"  → 다른 작업·다른 조각으로 바꿔치기해도 풀리지 않는다.
 * 키(32바이트)는 PC 프로그램이 처음 실행될 때 만들어 tvrelay.json 에 보관하고, TV 는 그 파일을 한 번 불러온다.
 */
class RelayCrypto(keyB64: String) {
    private val key: SecretKeySpec

    init {
        val raw = decodeKey(keyB64)
        require(raw.size == 32) { "암호키 길이가 올바르지 않습니다." }
        key = SecretKeySpec(raw, "AES")
    }

    fun seal(plain: ByteArray, aad: String): ByteArray {
        val nonce = ByteArray(12).also { RNG.nextBytes(it) }
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.ENCRYPT_MODE, key, GCMParameterSpec(128, nonce))
        c.updateAAD(aad.toByteArray(Charsets.UTF_8))
        val ct = c.doFinal(plain)
        return MAGIC + nonce + ct
    }

    fun open(sealed: ByteArray, aad: String): ByteArray {
        if (sealed.size < 4 + 12 + 16 || !sealed.copyOfRange(0, 4).contentEquals(MAGIC)) {
            throw SecurityException("암호화 형식이 아닙니다.")
        }
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, sealed, 4, 12))
        c.updateAAD(aad.toByteArray(Charsets.UTF_8))
        return try {
            c.doFinal(sealed, 16, sealed.size - 16)
        } catch (e: Exception) {
            throw SecurityException("복호화 실패 — PC 와 TV 의 암호키가 다릅니다.")
        }
    }

    companion object {
        private val MAGIC = "TVR1".toByteArray(Charsets.US_ASCII)
        private val RNG = SecureRandom()

        fun decodeKey(s: String): ByteArray {
            val t = s.trim()
            return try { Base64.getUrlDecoder().decode(t.trimEnd('=')) } catch (e: IllegalArgumentException) {
                Base64.getDecoder().decode(t)
            }
        }

        fun aad(tv: String, kind: String, id: String, name: String) = "$tv/$kind/$id/$name"
    }
}
