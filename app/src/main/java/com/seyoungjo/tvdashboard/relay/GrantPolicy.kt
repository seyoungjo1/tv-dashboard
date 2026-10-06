package com.seyoungjo.tvdashboard.relay

import com.seyoungjo.tvdashboard.data.PathGuard
import java.io.File

/**
 * 직원용 업로드 도구(폴더 전용)의 규칙 — HTML 안의 제한은 고칠 수 있으므로 **TV 가 여기서 강제**한다.
 *  · 작업은 put(올리기·교체)만
 *  · 경로는 지정 폴더 아래만 (하위 폴더 허용, '..'·숨김 이름 차단)
 *  · 허용 확장자만 (기본 png · js · json · html)
 *  · 같은 이름은 덮어쓰기. 용량은 도구(HTML)가 한 번에 30MB 로 제한한다.
 */
object GrantPolicy {
    class Denied(message: String) : Exception(message)

    data class Grant(
        val gid: String, val key: String, val folder: String, val maxBytes: Long,
        val types: Set<String>, val name: String,
    )

    private val GUARD = PathGuard(File("/"))

    /** 올릴 경로를 검사하고 정규화된 경로를 돌려준다 */
    fun checkPath(g: Grant, path: String): String {
        val rel = try { GUARD.normalize(path) } catch (e: PathGuard.InvalidPathException) {
            throw Denied(e.message ?: "잘못된 경로")
        }
        if (!rel.startsWith(g.folder + "/")) throw Denied("'${g.folder}' 폴더에만 올릴 수 있습니다: $rel")
        val ext = rel.substringAfterLast('/').substringAfterLast('.', "").lowercase()
        if (ext !in g.types) throw Denied("올릴 수 없는 파일 형식입니다 (.${ext.ifEmpty { "?" }}). 허용: ${g.types.sorted().joinToString(", ") { ".$it" }}")
        return rel
    }
}
