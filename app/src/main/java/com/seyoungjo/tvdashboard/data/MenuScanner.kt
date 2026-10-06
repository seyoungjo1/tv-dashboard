package com.seyoungjo.tvdashboard.data

import java.io.File

/**
 * 메뉴 자동 생성 규칙 (단순·일관):
 *  1) 자료 폴더 바로 아래의 하위 폴더 1개 = 버튼 1개
 *     ('.' 또는 '_' 로 시작하는 폴더는 숨김)
 *  2) 버튼 이름 = 폴더명. 앞의 정렬용 번호("01_", "2-", "03. ")는 표시에서 제거
 *  3) 정렬 = 폴더명 기준 자연 정렬(숫자는 숫자 크기로)
 *  4) 대표 이미지 우선순위
 *     ① 폴더 안 '대표이미지.(png|jpg|jpeg|webp|gif|bmp)'
 *     ② 자료 폴더 루트의 '<폴더명>.(이미지 확장자)'
 *     ③ 폴더 안 첫 번째 이미지(이름순)
 *     ④ 없으면 이름 첫 글자 표시
 *  5) 버튼 선택 시 폴더의 index.html (없으면 index.htm) 표시
 */
data class MenuEntry(
    val folder: String,          // 실제 폴더명 (상대 경로)
    val title: String,           // 표시 이름
    val image: File?,            // 대표 이미지
    val indexFile: String?,      // "index.html" / "index.htm" / null
    val stamp: Long              // 변경 감지용
)

object MenuScanner {
    val IMAGE_EXT = setOf("png", "jpg", "jpeg", "webp", "gif", "bmp")
    val VIDEO_EXT = setOf("mp4", "m4v", "webm", "mkv", "3gp", "mov", "ts")
    const val COVER_NAME = "대표이미지"
    private val ORDER_PREFIX = Regex("""^\d+\s*[_.\-)\s]\s*""")

    fun displayName(folder: String): String {
        val stripped = folder.replaceFirst(ORDER_PREFIX, "").trim()
        return stripped.ifEmpty { folder }
    }

    fun scan(root: File): List<MenuEntry> {
        val dirs = root.listFiles()?.filter { it.isDirectory && !PathGuard.isHidden(it.name) } ?: return emptyList()
        val rootFiles = root.listFiles()?.filter { it.isFile } ?: emptyList()
        return dirs.sortedWith { a, b -> naturalCompare(a.name, b.name) }.map { dir ->
            val files = dir.listFiles()?.filter { it.isFile && !it.name.startsWith(".") } ?: emptyList()
            val index = listOf("index.html", "index.htm").firstOrNull { n -> files.any { it.name.equals(n, true) } }
                ?.let { n -> files.first { it.name.equals(n, true) }.name }
            val image = pickImage(dir.name, files, rootFiles)
            var stamp = dir.lastModified()
            image?.let { stamp = stamp * 31 + it.lastModified() + it.length() }
            index?.let { stamp = stamp * 31 + File(dir, it).lastModified() }
            MenuEntry(dir.name, displayName(dir.name), image, index, stamp)
        }
    }

    fun pickImage(folderName: String, files: List<File>, rootFiles: List<File>): File? {
        val images = files.filter { it.extension.lowercase() in IMAGE_EXT }
        images.firstOrNull { it.nameWithoutExtension == COVER_NAME }?.let { return it }
        rootFiles.firstOrNull { it.extension.lowercase() in IMAGE_EXT && it.nameWithoutExtension == folderName }
            ?.let { return it }
        return images.sortedWith { a, b -> naturalCompare(a.name, b.name) }.firstOrNull()
    }

    /** 루트에 있는 동영상(대기 화면용), 이름순 */
    fun idleVideos(root: File): List<File> =
        root.listFiles()?.filter { it.isFile && it.extension.lowercase() in VIDEO_EXT && !it.name.startsWith(".") }
            ?.sortedWith { a, b -> naturalCompare(a.name, b.name) } ?: emptyList()

    fun signature(entries: List<MenuEntry>): String =
        entries.joinToString("|") { "${it.folder}:${it.stamp}:${it.image?.path}:${it.indexFile}" }

    /** "2_a" < "10_a" 가 되도록 숫자 구간은 숫자로 비교 */
    fun naturalCompare(a: String, b: String): Int {
        var i = 0
        var j = 0
        while (i < a.length && j < b.length) {
            val ca = a[i]
            val cb = b[j]
            if (ca.isDigit() && cb.isDigit()) {
                var ei = i; while (ei < a.length && a[ei].isDigit()) ei++
                var ej = j; while (ej < b.length && b[ej].isDigit()) ej++
                val na = a.substring(i, ei).trimStart('0')
                val nb = b.substring(j, ej).trimStart('0')
                if (na.length != nb.length) return na.length - nb.length
                val c = na.compareTo(nb)
                if (c != 0) return c
                i = ei; j = ej
            } else {
                val c = ca.lowercaseChar().compareTo(cb.lowercaseChar())
                if (c != 0) return c
                i++; j++
            }
        }
        return (a.length - i) - (b.length - j)
    }
}
