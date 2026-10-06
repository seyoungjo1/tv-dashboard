package com.seyoungjo.tvdashboard.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.file.Files

class MenuScannerTest {
    private val root: File = Files.createTempDirectory("menu").toFile()

    private fun file(rel: String, text: String = "x") = File(root, rel).apply { parentFile!!.mkdirs(); writeText(text) }

    @Test fun buildsMenuFromFolders() {
        file("10_지원팀/index.html"); file("10_지원팀/icon.png"); file("10_지원팀/chart.png")
        file("2_생산팀/index.html"); file("2_생산팀/ICON.webp")
        file("품질팀/index.htm"); file("품질팀/대표이미지.jpg")
        file("빈폴더/readme.txt"); file("빈폴더/photo.png")
        file("_숨김/index.html"); file(".tmp/x")
        file("대기화면.mp4")

        val m = MenuScanner.scan(root)
        assertEquals(listOf("2_생산팀", "10_지원팀", "빈폴더", "품질팀"), m.map { it.folder })
        assertEquals(listOf("생산팀", "지원팀", "빈폴더", "품질팀"), m.map { it.title })
        assertEquals("ICON.webp", m[0].image!!.name)
        assertEquals("icon.png", m[1].image!!.name)
        assertNull(m[2].image)          // icon.png 가 아니면 아이콘으로 쓰지 않음
        assertNull(m[2].indexFile)
        assertEquals("대표이미지.jpg", m[3].image!!.name)
        assertEquals("index.htm", m[3].indexFile)
        assertEquals(listOf("대기화면.mp4"), MenuScanner.idleVideos(root).map { it.name })
    }

    @Test fun customOrderAndMainFolder() {
        file("a팀/index.html"); file("b팀/index.html"); file("c팀/index.html"); file("d팀/index.html")
        file("main/sd.json"); file("main/2.mp4"); file("main/10.mp4"); file("main/1.mp4"); file("main/설정.json", "{\"videoFit\":\"crop\"}")
        file(MenuScanner.ORDER_FILE, "\uFEFFc팀\n\n없는팀\na팀\n")
        val m = MenuScanner.scan(root)
        assertEquals(listOf("c팀", "a팀", "b팀", "d팀"), m.map { it.folder })     // 적힌 순서 먼저, 나머지는 이름순 · main 은 메뉴 아님
        val main = MenuScanner.mainDir(root)
        assertEquals(listOf("1.mp4", "2.mp4", "10.mp4"), MenuScanner.mainVideos(main).map { it.name })
        assertTrue(MenuScanner.mainCrop(main))
    }

    @Test fun signatureChangesWhenFilesChange() {
        val idx = file("A/index.html")
        val s1 = MenuScanner.signature(MenuScanner.scan(root))
        idx.setLastModified(idx.lastModified() + 5000)
        val s2 = MenuScanner.signature(MenuScanner.scan(root))
        assertTrue(s1 != s2)
    }

    @Test fun displayNameRules() {
        assertEquals("생산팀", MenuScanner.displayName("01_생산팀"))
        assertEquals("생산팀", MenuScanner.displayName("3. 생산팀"))
        assertEquals("생산팀", MenuScanner.displayName("12-생산팀"))
        assertEquals("2024년 실적", MenuScanner.displayName("2024년 실적"))
        assertEquals("123", MenuScanner.displayName("123"))
    }
}
