package com.seyoungjo.tvdashboard.server

import android.content.Context
import android.content.SharedPreferences
import android.util.Base64
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.concurrent.ConcurrentHashMap
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.PBEKeySpec

/**
 * 관리자 로그인 + API 토큰.
 *  - 최초 실행 시 임의의 초기 비밀번호를 만들고 TV 설정 화면에만 표시합니다
 *    (TV 앞에 있는 사람만 알 수 있음). 관리 웹에서 변경하면 더 이상 표시되지 않습니다.
 *  - 비밀번호는 PBKDF2 해시로만 저장합니다.
 *  - API 토큰은 자동 업로드 프로그램용(Authorization: Bearer <토큰>).
 */
object Auth {
    private lateinit var prefs: SharedPreferences
    private val random = SecureRandom()
    private val sessions = ConcurrentHashMap<String, Long>()
    private val failures = ConcurrentHashMap<String, Pair<Int, Long>>()

    private const val SESSION_MS = 12 * 60 * 60 * 1000L
    private const val MAX_FAILS = 5
    private const val LOCK_MS = 60_000L
    private const val ITER = 20_000
    private const val PW_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"

    fun init(context: Context) {
        prefs = context.getSharedPreferences("auth", Context.MODE_PRIVATE)
        if (prefs.getString("pw_hash", null) == null) resetPassword()
        if (prefs.getString("api_token", null) == null) regenerateApiToken()
    }

    // ── 비밀번호 ──────────────────────────────────────────────────────────
    /** 아직 변경되지 않은 초기 비밀번호 (변경 후에는 null) */
    val initialPassword: String? get() = prefs.getString("initial_pw", null)

    fun resetPassword(): String {
        val pw = (1..10).map { PW_CHARS[random.nextInt(PW_CHARS.length)] }.joinToString("")
        storePassword(pw)
        prefs.edit().putString("initial_pw", pw).apply()
        sessions.clear()
        return pw
    }

    fun changePassword(newPw: String) {
        require(newPw.length >= 8) { "비밀번호는 8자 이상이어야 합니다." }
        storePassword(newPw)
        prefs.edit().remove("initial_pw").apply()
    }

    private fun storePassword(pw: String) {
        val salt = ByteArray(16).also { random.nextBytes(it) }
        prefs.edit()
            .putString("pw_salt", b64(salt))
            .putString("pw_hash", b64(hash(pw, salt)))
            .apply()
    }

    fun verifyPassword(pw: String): Boolean {
        val salt = Base64.decode(prefs.getString("pw_salt", "") ?: "", Base64.NO_WRAP)
        val expected = Base64.decode(prefs.getString("pw_hash", "") ?: "", Base64.NO_WRAP)
        return MessageDigest.isEqual(hash(pw, salt), expected)
    }

    private fun hash(pw: String, salt: ByteArray): ByteArray {
        val spec = PBEKeySpec(pw.toCharArray(), salt, ITER, 256)
        return SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).encoded
    }

    // ── 로그인 시도 제한 (IP별 5회 실패 → 60초 잠금) ─────────────────────────
    fun lockedSeconds(ip: String): Long {
        val (count, until) = failures[ip] ?: return 0
        val left = until - System.currentTimeMillis()
        return if (count >= MAX_FAILS && left > 0) (left + 999) / 1000 else 0
    }

    fun recordFailure(ip: String) {
        val now = System.currentTimeMillis()
        val (count, until) = failures[ip] ?: (0 to 0L)
        val c = if (count >= MAX_FAILS && until < now) 1 else count + 1
        failures[ip] = c to (now + LOCK_MS)
    }

    fun recordSuccess(ip: String) { failures.remove(ip) }

    // ── 세션 ──────────────────────────────────────────────────────────────
    fun newSession(): String {
        val t = token(32)
        sessions[t] = System.currentTimeMillis() + SESSION_MS
        sessions.entries.removeIf { it.value < System.currentTimeMillis() }
        return t
    }

    fun endSession(t: String) { sessions.remove(t) }

    fun isSession(t: String): Boolean {
        val exp = sessions[t] ?: return false
        if (exp < System.currentTimeMillis()) { sessions.remove(t); return false }
        sessions[t] = System.currentTimeMillis() + SESSION_MS
        return true
    }

    // ── API 토큰 ──────────────────────────────────────────────────────────
    val apiToken: String get() = prefs.getString("api_token", "") ?: ""

    fun regenerateApiToken(): String {
        val t = token(24)
        prefs.edit().putString("api_token", t).apply()
        return t
    }

    fun isApiToken(t: String): Boolean {
        val cur = apiToken
        return cur.isNotEmpty() && MessageDigest.isEqual(cur.toByteArray(), t.toByteArray())
    }

    private fun token(bytes: Int): String {
        val b = ByteArray(bytes).also { random.nextBytes(it) }
        return b.joinToString("") { "%02x".format(it) }
    }

    private fun b64(b: ByteArray) = Base64.encodeToString(b, Base64.NO_WRAP)
}
