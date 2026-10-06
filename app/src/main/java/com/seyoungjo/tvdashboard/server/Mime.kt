package com.seyoungjo.tvdashboard.server

import java.net.URLConnection

object Mime {
    private val MAP = mapOf(
        "html" to "text/html", "htm" to "text/html", "js" to "text/javascript", "mjs" to "text/javascript",
        "css" to "text/css", "json" to "application/json", "txt" to "text/plain", "csv" to "text/csv",
        "xml" to "application/xml", "svg" to "image/svg+xml", "png" to "image/png", "jpg" to "image/jpeg",
        "jpeg" to "image/jpeg", "gif" to "image/gif", "webp" to "image/webp", "bmp" to "image/bmp",
        "ico" to "image/x-icon", "mp4" to "video/mp4", "m4v" to "video/mp4", "webm" to "video/webm",
        "mp3" to "audio/mpeg", "wav" to "audio/wav", "ogg" to "audio/ogg", "pdf" to "application/pdf",
        "woff" to "font/woff", "woff2" to "font/woff2", "ttf" to "font/ttf", "otf" to "font/otf",
        "wasm" to "application/wasm", "apk" to "application/vnd.android.package-archive",
    )

    fun of(name: String): String {
        val ext = name.substringAfterLast('.', "").lowercase()
        return MAP[ext] ?: URLConnection.guessContentTypeFromName(name) ?: "application/octet-stream"
    }

    fun isText(mime: String) = mime.startsWith("text/") || mime == "application/json" ||
        mime == "application/xml" || mime == "image/svg+xml"
}
