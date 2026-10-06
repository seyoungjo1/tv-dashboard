package com.seyoungjo.tvdashboard.relay

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class GrantPolicyTest {
    private val folder = GrantPolicy.Grant("g1", "k", "원가", 1L shl 30, setOf("json", "html", "png"), "원가")
    private val notice = GrantPolicy.Grant("g2", "k", "main", 1L shl 30, setOf("txt"), "공지", files = setOf("공지.txt"), read = true)

    @Test fun folderToolMayReadOnlyJsonInItsFolder() {
        val rel = GrantPolicy.checkPath(folder, "원가/sd.json")
        assertEquals("원가/sd.json", rel)
        GrantPolicy.checkOp(folder, "get", rel)
        GrantPolicy.checkOp(folder, "put", rel)
        assertThrows(GrantPolicy.Denied::class.java) { GrantPolicy.checkOp(folder, "get", "원가/index.html") }
        assertThrows(GrantPolicy.Denied::class.java) { GrantPolicy.checkPath(folder, "생산/sd.json") }
        assertThrows(GrantPolicy.Denied::class.java) { GrantPolicy.checkPath(folder, "원가/../생산/sd.json") }
        assertThrows(GrantPolicy.Denied::class.java) { GrantPolicy.checkOp(folder, "delete", "원가/sd.json") }
    }

    @Test fun noticeToolKeepsItsRules() {
        val rel = GrantPolicy.checkPath(notice, "main/공지.txt")
        GrantPolicy.checkOp(notice, "get", rel)
        assertThrows(GrantPolicy.Denied::class.java) { GrantPolicy.checkPath(notice, "main/sd.json") }
    }
}
