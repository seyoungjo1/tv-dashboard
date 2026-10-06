package com.seyoungjo.tvdashboard.relay

import android.util.Log
import com.seyoungjo.tvdashboard.data.AppSettings
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.security.SecureRandom

/**
 * TV 무설정 연결 (연결 코드).
 *
 *  1) TV 는 처음 실행 때 연결 코드(예: K7QM-4PXD, 40비트)를 만들어 화면·설정에 보여 준다.
 *  2) PC 프로그램에 그 코드를 입력하면, PC 는 연결 정보 JSON(레포·TV 이름·암호키·토큰)을
 *     코드에서 만든 키로 암호화해 공개 레포의 relay/pair/<id> 브랜치에 올린다.
 *       id  = PBKDF2(코드, "tvpair-id", 200000회)  앞 8바이트(hex)
 *       key = PBKDF2(코드, "tvpair-key", 200000회) 32바이트,  AAD = "pair/<id>/m"
 *  3) TV 는 토큰 없이 읽기만 한다 — github.com/<repo>.git/info/refs (브랜치 목록, API 호출 한도 없음)
 *     → raw.githubusercontent.com/<repo>/<커밋>/m (커밋 고정 주소라 캐시 문제 없음) → 복호화 → 설정 저장.
 *  4) 받은 토큰으로 pair 브랜치를 지운다 (PC 는 브랜치가 사라지는 것으로 연결 완료를 안다).
 * 코드를 모르면 JSON 을 풀 수 없고, PBKDF2 20만 회라 코드 추측(2^40)도 사실상 불가능하다.
 */
object Pairing {
    private const val TAG = "Pairing"
    private const val ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   // 헷갈리는 0 O 1 I 제외 (32자 = 5비트)

    private var cachedFor = ""
    private var cachedId = ""
    private var cachedKey = ByteArray(0)

    /** 표시용 코드 XXXX-XXXX (없으면 만든다) */
    val code: String
        get() {
            val p = AppSettings.prefs
            var c = p.getString("pair_code", null)
            if (c.isNullOrBlank()) {
                val rnd = SecureRandom()
                c = (1..8).map { ALPHABET[rnd.nextInt(ALPHABET.length)] }.joinToString("")
                p.edit().putString("pair_code", c).apply()
            }
            return c.substring(0, 4) + "-" + c.substring(4)
        }

    private fun derive() {
        val c = PairCrypto.normalize(code)
        if (c == cachedFor) return
        val (id, key) = PairCrypto.derive(c)
        cachedId = id
        cachedKey = key
        cachedFor = c
    }

    /** 연결 정보가 올라왔는지 한 번 확인. 연결되면 true */
    fun pollOnce(repo: String): Boolean {
        derive()
        val branch = "relay/pair/$cachedId"
        val refs = httpGet("https://github.com/$repo.git/info/refs?service=git-upload-pack", "git/2.45.0").toString(Charsets.ISO_8859_1)
        val commit = PairCrypto.findCommit(refs, branch) ?: return false
        val sealed = httpGet("https://raw.githubusercontent.com/$repo/$commit/m", "tv-dashboard")
        val cfg = PairCrypto.open(cachedId, cachedKey, sealed)
        RelaySettings.apply(cfg.put("enabled", true))
        Log.i(TAG, "paired: repo=${RelaySettings.repo} tv=${RelaySettings.tv}")
        try {
            GitHubApi(RelaySettings.repo, RelaySettings.token).deleteBranch(branch)
        } catch (e: Exception) {
            Log.w(TAG, "pair branch delete failed", e)
        }
        return true
    }

    private fun httpGet(url: String, ua: String): ByteArray {
        val c = URL(url).openConnection() as HttpURLConnection
        c.connectTimeout = 20_000
        c.readTimeout = 60_000
        c.setRequestProperty("User-Agent", ua)
        try {
            val code = c.responseCode
            if (code != 200) throw GitHubApi.ApiError(code, "GitHub 응답 $code ($url)")
            val out = ByteArrayOutputStream()
            c.inputStream.use { it.copyTo(out) }
            return out.toByteArray()
        } finally {
            c.disconnect()
        }
    }
}
