package com.seyoungjo.tvdashboard.ui

import android.content.Context
import android.webkit.WebResourceResponse
import androidx.webkit.WebViewAssetLoader
import com.seyoungjo.tvdashboard.data.ContentStore
import com.seyoungjo.tvdashboard.server.Mime
import java.io.ByteArrayInputStream
import java.io.FileInputStream

/**
 * https://appassets.androidplatform.net/data/<폴더>/<파일> → 자료 폴더의 실제 파일.
 * file:// 대신 https 가상 주소를 쓰므로 index.html 의 fetch('data.json') 등이
 * 같은 출처(same-origin)로 정상 동작합니다. 캐시하지 않아 교체된 파일이 바로 반영됩니다.
 */
class DataPathHandler(private val ctx: Context) : WebViewAssetLoader.PathHandler {

    override fun handle(path: String): WebResourceResponse = handle(path, null)

    /** range = 요청의 Range 헤더 ("bytes=시작-끝") — 페이지 <video> 가 동영상을 끊어 읽을 때 206 으로 답한다 */
    fun handle(path: String, range: String?): WebResourceResponse {
        return try {
            val guard = ContentStore.guard(ctx)
            var f = guard.resolve(path)
            if (f.isDirectory) f = java.io.File(f, "index.html")
            if (!f.isFile) return notFound()
            val mime = Mime.of(f.name)
            val headers = mutableMapOf(
                "Cache-Control" to "no-store, no-cache, must-revalidate",
                "Access-Control-Allow-Origin" to "*",
                "Accept-Ranges" to "bytes",
            )
            val len = f.length()
            val m = range?.let { Regex("bytes=(\\d*)-(\\d*)").find(it.trim()) }
            if (m != null && len > 0) {
                val a = m.groupValues[1].toLongOrNull()
                val b = m.groupValues[2].toLongOrNull()
                val start = a ?: maxOf(0L, len - (b ?: 0L))
                val end = (if (a == null) len - 1 else (b ?: (len - 1))).coerceAtMost(len - 1)
                if (start in 0..end) {
                    val ins = FileInputStream(f)
                    ins.channel.position(start)
                    headers["Content-Range"] = "bytes $start-$end/$len"
                    headers["Content-Length"] = (end - start + 1).toString()
                    return WebResourceResponse(mime, null, 206, "Partial Content", headers, LimitedStream(ins, end - start + 1))
                }
            }
            headers["Content-Length"] = len.toString()
            WebResourceResponse(mime, if (Mime.isText(mime)) "utf-8" else null, 200, "OK", headers, FileInputStream(f))
        } catch (e: Exception) {
            notFound()
        }
    }

    /** 파일의 일부만 읽어 주는 스트림 (Range 응답) */
    private class LimitedStream(private val src: FileInputStream, private var left: Long) : java.io.InputStream() {
        override fun read(): Int { if (left <= 0) return -1; val r = src.read(); if (r >= 0) left--; return r }
        override fun read(b: ByteArray, off: Int, len: Int): Int {
            if (left <= 0) return -1
            val r = src.read(b, off, minOf(len.toLong(), left).toInt())
            if (r > 0) left -= r
            return r
        }
        override fun close() = src.close()
    }

    private fun notFound() = WebResourceResponse(
        "text/plain", "utf-8", 404, "Not Found", mapOf("Cache-Control" to "no-store"),
        ByteArrayInputStream("Not Found".toByteArray())
    )
}
