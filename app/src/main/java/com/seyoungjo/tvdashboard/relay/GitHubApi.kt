package com.seyoungjo.tvdashboard.relay

import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.Base64

/**
 * GitHub Git Data API 의 필요한 부분만 (외부 라이브러리 없음).
 * 작업 하나 = 부모 없는 커밋 하나(orphan) + 브랜치 하나 → 브랜치를 지우면 레포에 이력이 남지 않는다.
 */
class GitHubApi(
    private val repo: String,
    private val token: String,
    private val base: String = "https://api.github.com",
) {
    class ApiError(val code: Int, message: String) : Exception(message)

    class Resp(val code: Int, val body: ByteArray, val etag: String?)

    /**
     * 요청. 읽기(GET)와 blob 올리기(내용 주소라 다시 보내도 같은 결과)는 연결이 끊기면(unexpected end of stream ·
     * 시간 초과 등 IOException) 잠깐 쉬고 다시 시도한다 — TV 와이파이가 잠깐 흔들려 파일 하나가 '실패'로 남지 않게
     */
    fun request(method: String, path: String, body: JSONObject? = null, raw: Boolean = false, etag: String? = null): Resp {
        val retry = method == "GET" || path == "git/blobs"
        var wait = 1500L
        var last: java.io.IOException? = null
        for (attempt in 1..(if (retry) 4 else 1)) {
            try {
                return once(method, path, body, raw, etag)
            } catch (e: java.io.IOException) {
                last = e
                if (attempt == 4 || !retry) throw e
                try { Thread.sleep(wait) } catch (_: InterruptedException) { throw e }
                wait *= 2
            }
        }
        throw last!!
    }

    private fun once(method: String, path: String, body: JSONObject?, raw: Boolean, etag: String?): Resp {
        val c = URL("$base/repos/$repo/$path").openConnection() as HttpURLConnection
        c.requestMethod = method
        c.connectTimeout = 20_000
        c.readTimeout = 120_000
        c.setRequestProperty("Authorization", "Bearer $token")
        c.setRequestProperty("Accept", if (raw) "application/vnd.github.raw+json" else "application/vnd.github+json")
        c.setRequestProperty("X-GitHub-Api-Version", "2022-11-28")
        c.setRequestProperty("User-Agent", "tv-dashboard-relay")
        if (etag != null) c.setRequestProperty("If-None-Match", etag)
        try {
            if (body != null) {
                val bytes = body.toString().toByteArray(Charsets.UTF_8)
                c.doOutput = true
                c.setRequestProperty("Content-Type", "application/json")
                c.setFixedLengthStreamingMode(bytes.size)
                c.outputStream.use { it.write(bytes) }
            }
            val code = c.responseCode
            val stream = if (code >= 400) c.errorStream else if (code == 304 || code == 204) null else c.inputStream
            val out = ByteArrayOutputStream()
            stream?.use { it.copyTo(out) }
            if (code >= 400 && code != 404 && code != 409 && code != 422) {
                val msg = try { JSONObject(out.toString("UTF-8")).optString("message") } catch (e: Exception) { "" }
                throw ApiError(code, when (code) {
                    401 -> "GitHub 토큰이 유효하지 않습니다 (401)."
                    403 -> "GitHub 권한이 없거나 호출 한도를 넘었습니다 (403). $msg"
                    else -> "GitHub 오류 $code $msg"
                })
            }
            return Resp(code, out.toByteArray(), c.getHeaderField("ETag"))
        } finally {
            c.disconnect()
        }
    }

    private fun json(r: Resp) = JSONObject(r.body.toString(Charsets.UTF_8))

    private fun expect(r: Resp, vararg ok: Int): Resp {
        if (r.code !in ok) {
            val msg = try { json(r).optString("message") } catch (e: Exception) { "" }
            throw ApiError(r.code, "GitHub 오류 ${r.code} $msg")
        }
        return r
    }

    /** prefix 로 시작하는 브랜치들 (ref 전체 이름 → 커밋 SHA). 바뀐 게 없으면(304) null */
    fun matchingRefs(prefix: String, etag: String?): Pair<List<Pair<String, String>>, String?>? {
        val r = request("GET", "git/matching-refs/heads/$prefix", etag = etag)
        if (r.code == 304) return null
        if (r.code == 404 || r.code == 409) return emptyList<Pair<String, String>>() to r.etag  // 409 = 빈 레포
        val arr = JSONArray(r.body.toString(Charsets.UTF_8))
        val out = (0 until arr.length()).map {
            val o = arr.getJSONObject(it)
            o.getString("ref").removePrefix("refs/heads/") to o.getJSONObject("object").getString("sha")
        }
        return out to r.etag
    }

    /** 브랜치의 커밋 SHA (없으면 null) */
    fun refSha(branch: String): String? {
        val r = request("GET", "git/ref/heads/$branch")
        if (r.code == 404 || r.code == 409) return null
        return json(expect(r, 200)).getJSONObject("object").getString("sha")
    }

    /** 커밋의 최상위 파일들: 이름 → blob SHA */
    fun commitFiles(commitSha: String): Map<String, String> {
        val tree = json(expect(request("GET", "git/commits/$commitSha"), 200)).getJSONObject("tree").getString("sha")
        val arr = json(expect(request("GET", "git/trees/$tree"), 200)).getJSONArray("tree")
        return (0 until arr.length()).map { arr.getJSONObject(it) }
            .filter { it.optString("type") == "blob" }
            .associate { it.getString("path") to it.getString("sha") }
    }

    fun blob(sha: String): ByteArray = expect(request("GET", "git/blobs/$sha", raw = true), 200).body

    fun createBlob(data: ByteArray): String {
        val body = JSONObject().put("content", Base64.getEncoder().encodeToString(data)).put("encoding", "base64")
        return json(expect(request("POST", "git/blobs", body), 201)).getString("sha")
    }

    /** 이름 → 내용 으로 부모 없는 커밋을 만든다 */
    fun createOrphanCommit(files: Map<String, ByteArray>, message: String): String {
        val tree = JSONArray()
        for ((name, data) in files) {
            tree.put(JSONObject().put("path", name).put("mode", "100644").put("type", "blob").put("sha", createBlob(data)))
        }
        val treeSha = json(expect(request("POST", "git/trees", JSONObject().put("tree", tree)), 201)).getString("sha")
        val commit = JSONObject().put("message", message).put("tree", treeSha).put("parents", JSONArray())
        return json(expect(request("POST", "git/commits", commit), 201)).getString("sha")
    }

    fun createBranch(branch: String, sha: String) {
        expect(request("POST", "git/refs", JSONObject().put("ref", "refs/heads/$branch").put("sha", sha)), 201)
    }

    fun deleteBranch(branch: String) {
        expect(request("DELETE", "git/refs/heads/$branch"), 204, 404, 422)
    }

    /** 브랜치를 새 커밋으로 (있으면 지우고 다시 만든다 — PATCH 없이 이식성 확보) */
    fun replaceBranch(branch: String, sha: String) {
        val r = request("POST", "git/refs", JSONObject().put("ref", "refs/heads/$branch").put("sha", sha))
        if (r.code == 201) return
        deleteBranch(branch)
        createBranch(branch, sha)
    }
}
