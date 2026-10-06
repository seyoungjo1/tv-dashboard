package com.seyoungjo.tvdashboard.update

object Versions {
    /** "v1.2.3" → 1_002_003 (build.gradle.kts 의 versionCode 규칙과 동일) */
    fun codeFromName(name: String): Long? {
        val m = Regex("""^v?(\d+)\.(\d+)\.(\d+)""").find(name.trim()) ?: return null
        val (a, b, c) = m.destructured
        return a.toLong() * 1_000_000 + b.toLong() * 1_000 + c.toLong()
    }
}
