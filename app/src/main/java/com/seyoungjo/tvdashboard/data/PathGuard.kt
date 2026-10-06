package com.seyoungjo.tvdashboard.data

import java.io.File

/**
 * 자료 폴더(root) 밖으로 벗어나는 경로를 차단합니다.
 * 상대 경로는 "생산팀/data.json" 처럼 '/' 로 구분합니다.
 * '.' 으로 시작하는 이름(.tmp 등 내부용)과 '..' 은 허용하지 않습니다.
 */
class PathGuard(val root: File) {

    class InvalidPathException(message: String) : IllegalArgumentException(message)

    private val canonicalRoot: File get() = root.canonicalFile

    /** 정규화된 상대 경로 ("" = 루트). 잘못된 경로는 예외. */
    fun normalize(relative: String?): String {
        val raw = (relative ?: "").replace('\\', '/').trim()
        val segments = raw.split('/').filter { it.isNotEmpty() }
        for (s in segments) validateName(s)
        return segments.joinToString("/")
    }

    /** 상대 경로를 실제 파일로 변환. 루트 밖이면 예외. */
    fun resolve(relative: String?): File {
        val norm = normalize(relative)
        val rootC = canonicalRoot
        val target = if (norm.isEmpty()) rootC else File(rootC, norm)
        val canon = target.canonicalFile
        if (canon != rootC && !canon.path.startsWith(rootC.path + File.separator)) {
            throw InvalidPathException("자료 폴더 밖의 경로는 사용할 수 없습니다.")
        }
        return target
    }

    /** 실제 파일 → 상대 경로 */
    fun relativize(file: File): String {
        val rootC = canonicalRoot.path
        val p = file.canonicalPath
        if (p == rootC) return ""
        require(p.startsWith(rootC + File.separator)) { "outside root" }
        return p.substring(rootC.length + 1).replace(File.separatorChar, '/')
    }

    companion object {
        private val FORBIDDEN_CHARS = charArrayOf('/', '\\', '\u0000', ':', '*', '?', '"', '<', '>', '|')

        fun validateName(name: String) {
            if (name.isBlank()) throw InvalidPathException("이름이 비어 있습니다.")
            if (name == "." || name == "..") throw InvalidPathException("'..' 은 사용할 수 없습니다.")
            if (name.startsWith(".")) throw InvalidPathException("'.' 으로 시작하는 이름은 사용할 수 없습니다: $name")
            if (name.any { it in FORBIDDEN_CHARS || it.code < 0x20 }) {
                throw InvalidPathException("사용할 수 없는 문자가 포함되어 있습니다: $name")
            }
            if (name.toByteArray(Charsets.UTF_8).size > 255) throw InvalidPathException("이름이 너무 깁니다.")
        }

        fun isHidden(name: String) = name.startsWith(".") || name.startsWith("_")
    }
}
