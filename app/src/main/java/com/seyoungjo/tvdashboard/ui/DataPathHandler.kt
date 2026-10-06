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

    override fun handle(path: String): WebResourceResponse {
        return try {
            val guard = ContentStore.guard(ctx)
            var f = guard.resolve(path)
            if (f.isDirectory) f = java.io.File(f, "index.html")
            if (!f.isFile) return notFound()
            val mime = Mime.of(f.name)
            WebResourceResponse(
                mime, if (Mime.isText(mime)) "utf-8" else null, 200, "OK",
                mapOf(
                    "Cache-Control" to "no-store, no-cache, must-revalidate",
                    "Access-Control-Allow-Origin" to "*",
                ),
                FileInputStream(f)
            )
        } catch (e: Exception) {
            notFound()
        }
    }

    private fun notFound() = WebResourceResponse(
        "text/plain", "utf-8", 404, "Not Found", mapOf("Cache-Control" to "no-store"),
        ByteArrayInputStream("Not Found".toByteArray())
    )
}
