package com.seyoungjo.tvdashboard.relay

import com.seyoungjo.tvdashboard.data.PathGuard
import java.io.File

/**
 * 직원용 업로드 도구(폴더 전용)의 규칙 — HTML 안의 제한은 고칠 수 있으므로 **TV 가 여기서 강제**한다.
 *  · 작업은 put(올리기·교체)만
 *  · 경로는 지정 폴더 아래만 (하위 폴더 허용, '..'·숨김 이름 차단)
 *  · 허용 확장자만 (기본 png · js · json · html)
 *  · 같은 이름은 덮어쓰기. 용량은 도구(HTML)가 한 번에 30MB 로 제한한다.
 *  · 공지사항 도구(main 전용)처럼 files 가 정해진 도구는 그 파일만, read 가 켜진 도구만 get(읽기) 가능
 */
object GrantPolicy {
    class Denied(message: String) : Exception(message)

    data class Grant(
        val gid: String, val key: String, val folder: String, val maxBytes: Long,
        val types: Set<String>, val name: String,
        val files: Set<String> = emptySet(),          // 비어 있으면 폴더 안 아무 파일 (허용 형식만)
        val read: Boolean = false,                    // get(읽기) 허용
    )

    private val GUARD = PathGuard(File("/"))

    /** 올릴 경로를 검사하고 정규화된 경로를 돌려준다 */
    fun checkPath(g: Grant, path: String): String {
        val rel = try { GUARD.normalize(path) } catch (e: PathGuard.InvalidPathException) {
            throw Denied(e.message ?: "잘못된 경로")
        }
        if (!rel.startsWith(g.folder + "/")) throw Denied("'${g.folder}' 폴더에만 올릴 수 있습니다: $rel")
        if (g.files.isNotEmpty() && rel.removePrefix(g.folder + "/") !in g.files) {
            throw Denied("이 도구로는 ${g.files.sorted().joinToString(", ")} 만 다룰 수 있습니다: $rel")
        }
        val ext = rel.substringAfterLast('/').substringAfterLast('.', "").lowercase()
        if (ext !in g.types) throw Denied("올릴 수 없는 파일 형식입니다 (.${ext.ifEmpty { "?" }}). 허용: ${g.types.sorted().joinToString(", ") { ".$it" }}")
        return rel
    }

    /** 이 도구로 할 수 있는 작업인지 */
    fun checkOp(g: Grant, op: String) {
        when (op) {
            "put" -> {}
            "get" -> if (!g.read) throw Denied("이 도구로는 파일 올리기만 할 수 있습니다.")
            else -> throw Denied(if (g.read) "이 도구로는 읽기·저장만 할 수 있습니다." else "이 도구로는 파일 올리기만 할 수 있습니다.")
        }
    }
}
