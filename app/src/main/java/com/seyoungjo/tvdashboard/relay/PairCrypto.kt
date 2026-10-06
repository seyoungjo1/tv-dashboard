package com.seyoungjo.tvdashboard.relay

import org.json.JSONObject
import java.util.Base64
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.PBEKeySpec

/** 연결 코드 → (pair id, 키) 계산과 연결 정보 복호화. PC 의 tvrelay/relay.py pair_secrets 와 같은 계산. */
object PairCrypto {
    private const val ITER = 200_000

    fun normalize(c: String) = c.uppercase().filter { it.isLetterOrDigit() }

    fun derive(code: String): Pair<String, ByteArray> {
        val c = normalize(code)
        val id = pbkdf2(c, "tvpair-id", 8).joinToString("") { "%02x".format(it) }
        return id to pbkdf2(c, "tvpair-key", 32)
    }

    fun open(id: String, key: ByteArray, sealed: ByteArray): JSONObject {
        val crypto = RelayCrypto(Base64.getUrlEncoder().withoutPadding().encodeToString(key))
        return JSONObject(crypto.open(sealed, "pair/$id/m").toString(Charsets.UTF_8))
    }

    /** git info/refs 응답에서 pair 브랜치의 커밋 SHA 찾기 */
    fun findCommit(refs: String, branch: String): String? =
        Regex("([0-9a-f]{40}) refs/heads/" + Regex.escape(branch) + "(?![\\w/.-])").find(refs)?.groupValues?.get(1)

    private fun pbkdf2(code: String, salt: String, len: Int): ByteArray =
        SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256")
            .generateSecret(PBEKeySpec(code.toCharArray(), salt.toByteArray(Charsets.UTF_8), ITER, len * 8)).encoded
}
