package com.seyoungjo.tvdashboard.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.File
import java.nio.file.Files

class PathGuardTest {
    private val root: File = Files.createTempDirectory("guard").toFile()
    private val g = PathGuard(root)

    @Test fun normalizesSlashes() {
        assertEquals("생산팀/data.json", g.normalize("/생산팀//data.json/"))
        assertEquals("a/b", g.normalize("a\\b"))
        assertEquals("", g.normalize(""))
        assertEquals("", g.normalize(null))
    }

    @Test fun resolvesInsideRoot() {
        val f = g.resolve("생산팀/index.html")
        assertTrue(f.path.startsWith(root.path))
        assertEquals("생산팀/index.html", g.relativize(f))
    }

    @Test fun rejectsTraversalAndHidden() {
        for (bad in listOf("../x", "a/../../x", "..", ".tmp/x", "a/.hidden", "a/b:c", "a\u0000b")) {
            try {
                g.resolve(bad); fail("should reject $bad")
            } catch (e: PathGuard.InvalidPathException) { /* ok */ }
        }
    }

    @Test fun rejectsSymlinkEscape() {
        val outside = Files.createTempDirectory("outside").toFile()
        try {
            Files.createSymbolicLink(File(root, "link").toPath(), outside.toPath())
        } catch (e: Exception) { return } // 심볼릭 링크를 만들 수 없는 환경은 건너뜀
        try {
            g.resolve("link/secret.txt"); fail("symlink escape")
        } catch (e: PathGuard.InvalidPathException) { /* ok */ }
    }
}
