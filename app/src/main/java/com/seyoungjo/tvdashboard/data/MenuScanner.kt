package com.seyoungjo.tvdashboard.data

import java.io.File

/**
 * 메뉴 자동 생성 규칙 (단순·일관):
 *  1) 자료 폴더 바로 아래의 하위 폴더 1개 = 버튼 1개
 *     ('.' 또는 '_' 로 시작하는 폴더는 숨김)
 *  2) 버튼 이름 = 폴더명. 앞의 정렬용 번호("01_", "2-", "03. ")는 표시에서 제거
 *  3) 정렬 = 자료 폴더의 '메뉴순서.txt'(한 줄에 폴더 이름 하나, PC 프로그램에서 끌어서 정함)에 적힌 순서가 먼저,
 *     나머지는 폴더명 기준 자연 정렬(숫자는 숫자 크기로)
 *  4) 아이콘 = 폴더 안 'icon.png' (icon.jpg / icon.jpeg / icon.webp 도 허용)
 *     예전 이름 '대표이미지.png' 도 인식. 없으면 이름 첫 글자 색상 타일
 *  5) 버튼 선택 시 폴더의 index.html (없으면 index.htm) 표시
 *  6) 'main' 폴더는 메뉴가 아니라 화면보호기 (실적 JSON 4개 + 1.mp4 2.mp4 … )
 */
/** 화면보호기 재생 항목: main 의 동영상 파일 또는 유튜브 영상, 영상별 표시 방식 */
data class PlayItem(
    val file: File?,
    val youtube: String? = null,      // 유튜브 영상 id
    val vertical: Boolean = false,    // 쇼츠(세로 9:16)
    val crop: Boolean = false,        // true = 크롭(긴 쪽을 자름) / false = 확장(작은 쪽을 맞춤, 남는 곳 채움)
    val align: String = "center",     // 크롭 위치: top · center · bottom (가로가 넘치면 왼쪽 · 가운데 · 오른쪽)
    val blur: Boolean = true,         // 확장일 때 남는 곳: 블러 / 단색
    val color: Int = 0xFF000000.toInt(),
) {
    val key: String get() = (file?.let { it.path + ":" + it.lastModified() } ?: "yt:$youtube") + ":$crop:$align:$blur:$color"
}

data class MenuEntry(
    val folder: String,          // 실제 폴더명 (상대 경로)
    val title: String,           // 표시 이름
    val image: File?,            // 대표 이미지
    val indexFile: String?,      // "index.html" / "index.htm" / null
    val stamp: Long              // 변경 감지용
)

object MenuScanner {
    val VIDEO_EXT = setOf("mp4", "m4v", "webm", "mkv", "3gp", "mov", "ts")
    val ICON_EXT = setOf("png", "jpg", "jpeg", "webp")
    val ICON_NAMES = listOf("icon", "대표이미지")
    const val MAIN_FOLDER = "main"
    const val ORDER_FILE = "메뉴순서.txt"
    private val ORDER_PREFIX = Regex("""^\d+\s*[_.\-)\s]\s*""")

    fun displayName(folder: String): String {
        val stripped = folder.replaceFirst(ORDER_PREFIX, "").trim()
        return stripped.ifEmpty { folder }
    }

    fun scan(root: File): List<MenuEntry> {
        val dirs = root.listFiles()?.filter { it.isDirectory && !PathGuard.isHidden(it.name) && !isMain(it.name) } ?: return emptyList()
        val order = readOrder(root)
        return dirs.sortedWith { a, b ->
            val ia = order[a.name] ?: Int.MAX_VALUE
            val ib = order[b.name] ?: Int.MAX_VALUE
            if (ia != ib) ia.compareTo(ib) else naturalCompare(a.name, b.name)
        }.map { dir ->
            val files = dir.listFiles()?.filter { it.isFile && !it.name.startsWith(".") } ?: emptyList()
            val index = listOf("index.html", "index.htm").firstOrNull { n -> files.any { it.name.equals(n, true) } }
                ?.let { n -> files.first { it.name.equals(n, true) }.name }
            val image = pickImage(files)
            var stamp = dir.lastModified()
            image?.let { stamp = stamp * 31 + it.lastModified() + it.length() }
            index?.let { stamp = stamp * 31 + File(dir, it).lastModified() }
            MenuEntry(dir.name, displayName(dir.name), image, index, stamp)
        }
    }

    fun pickImage(files: List<File>): File? {
        val images = files.filter { it.extension.lowercase() in ICON_EXT }
        for (base in ICON_NAMES) {
            images.firstOrNull { it.nameWithoutExtension.equals(base, ignoreCase = true) }?.let { return it }
        }
        return null
    }

    fun isMain(name: String) = name.equals(MAIN_FOLDER, ignoreCase = true)

    /** 메뉴순서.txt → 폴더 이름 → 순번 (없거나 못 읽으면 빈 값) */
    fun readOrder(root: File): Map<String, Int> = try {
        val f = File(root, ORDER_FILE)
        if (!f.isFile || f.length() > 64 * 1024) emptyMap()
        else f.readText(Charsets.UTF_8).removePrefix("\uFEFF").lines().map { it.trim() }.filter { it.isNotEmpty() }
            .withIndex().associate { (i, n) -> n to i }
    } catch (e: Exception) {
        emptyMap()
    }

    /** 화면보호기 폴더 (자료/main) — 없으면 null */
    fun mainDir(root: File): File? = root.listFiles()?.firstOrNull { it.isDirectory && isMain(it.name) }

    /** 화면보호기 동영상: main 안의 동영상, 이름 오름차순 (1.mp4 2.mp4 … 10.mp4) */
    fun mainVideos(dir: File?): List<File> =
        dir?.listFiles()?.filter { it.isFile && it.extension.lowercase() in VIDEO_EXT && !it.name.startsWith(".") }
            ?.sortedWith { a, b -> naturalCompare(a.name, b.name) } ?: emptyList()

    /**
     * 화면보호기 재생 목록 (main/설정.json 의 "playlist", PC 프로그램에서 정함).
     *  [{ "src": "1.mp4" 또는 유튜브 주소, "fit": "crop"|"fit", "align": "center"|"top"|"bottom",
     *     "fill": "blur"|"color", "color": "#000000" }]
     * 목록에 없는 main 의 동영상은 그 뒤에 이름 오름차순으로 붙는다 (자동 업로드 .bat 으로 올린 것 등).
     */
    fun mainPlaylist(dir: File?): List<PlayItem> {
        val files = mainVideos(dir)
        val conf = try {
            val f = dir?.let { File(it, "설정.json") }
            if (f != null && f.isFile) org.json.JSONObject(f.readText(Charsets.UTF_8).removePrefix("\uFEFF")) else org.json.JSONObject()
        } catch (e: Exception) {
            org.json.JSONObject()
        }
        val defCrop = conf.optString("videoFit") == "crop"                       // 예전 설정(전체 크롭/맞춤)
        fun opts(o: org.json.JSONObject?, base: PlayItem): PlayItem = base.copy(
            crop = o?.optString("fit")?.let { if (it.isEmpty()) defCrop else it == "crop" } ?: defCrop,
            align = o?.optString("align")?.takeIf { it in setOf("top", "bottom", "center") } ?: "center",
            blur = o?.optString("fill") != "color",
            color = o?.optString("color")?.let { parseColor(it) } ?: 0xFF000000.toInt(),
        )
        val out = ArrayList<PlayItem>()
        val used = HashSet<String>()
        val arr = conf.optJSONArray("playlist")
        if (arr != null) for (k in 0 until arr.length()) {
            val o = arr.optJSONObject(k) ?: continue
            val src = o.optString("src").trim()
            val yt = youtubeId(src)
            if (yt != null) {
                out.add(opts(o, PlayItem(file = null, youtube = yt, vertical = src.contains("/shorts/") || o.optBoolean("vertical"))))
            } else {
                val f = files.firstOrNull { it.name == src } ?: continue
                if (used.add(f.name)) out.add(opts(o, PlayItem(file = f)))
            }
        }
        for (f in files) if (f.name !in used) out.add(opts(null, PlayItem(file = f)))
        return out
    }

    private val YT = Regex("""(?:youtu\.be/|youtube\.com/(?:shorts/|embed/|live/|watch\?(?:.*&)?v=))([A-Za-z0-9_-]{11})""")

    /** 유튜브 주소 → 영상 id (쇼츠 · youtu.be · watch?v= · embed) */
    fun youtubeId(src: String): String? = YT.find(src)?.groupValues?.get(1)

    private fun parseColor(s: String): Int? {
        val h = s.trim().removePrefix("#")
        if (!Regex("^[0-9a-fA-F]{6}$").matches(h)) return null
        return (0xFF000000 or h.toLong(16)).toInt()
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
