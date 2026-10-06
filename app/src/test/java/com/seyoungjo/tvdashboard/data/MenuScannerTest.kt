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
        file("10_지원팀/index.html"); file("10_지원팀/a.png"); file("10_지원팀/b.jpg")
        file("2_생산팀/index.html"); file("2_생산팀/대표이미지.png"); file("2_생산팀/z.png")
        file("품질팀/index.htm")
        file("품질팀.webp")                       // 루트의 '폴더명.이미지'
        file("빈폴더/readme.txt")
        file("_숨김/index.html"); file(".tmp/x")
        file("대기화면.mp4")

        val m = MenuScanner.scan(root)
        assertEquals(listOf("2_생산팀", "10_지원팀", "빈폴더", "품질팀"), m.map { it.folder })
        assertEquals(listOf("생산팀", "지원팀", "빈폴더", "품질팀"), m.map { it.title })
        assertEquals("대표이미지.png", m[0].image!!.name)
        assertEquals("a.png", m[1].image!!.name)
        assertNull(m[2].image)
        assertNull(m[2].indexFile)
        assertEquals("품질팀.webp", m[3].image!!.name)
        assertEquals("index.htm", m[3].indexFile)
        assertEquals(listOf("대기화면.mp4"), MenuScanner.idleVideos(root).map { it.name })
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
