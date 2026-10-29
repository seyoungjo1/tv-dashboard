package com.seyoungjo.tvdashboard.relay

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayInputStream
import java.util.Base64
import java.util.zip.GZIPInputStream

class TreeIndexTest {
    private fun tree(vararg f: Triple<String, Long, Long>) = JSONArray().apply {
        put(JSONObject().put("p", "a").put("d", true).put("s", 0).put("t", 1))
        for ((p, s, t) in f) put(JSONObject().put("p", p).put("d", false).put("s", s).put("t", t).put("h", "h$s$t"))
    }

    @Test fun sameDiffAndFull() {
        val i1 = TreeIndex.update(null, tree(Triple("a/x.json", 10, 100), Triple("a/y.png", 20, 100)), 1000)
        assertEquals(1L, i1.getLong("gen"))
        val id = i1.getString("id")
        // 바뀐 게 없으면 장부 그대로
        assertSame(i1, TreeIndex.update(i1, tree(Triple("a/x.json", 10, 100), Triple("a/y.png", 20, 100)), 2000))
        assertTrue(TreeIndex.since(i1, id, 1).optBoolean("same"))
        // x 바뀜, y 지움, z 새로
        val i2 = TreeIndex.update(i1, tree(Triple("a/x.json", 11, 200), Triple("a/z.txt", 5, 200)), 3000)
        assertEquals(2L, i2.getLong("gen"))
        val d = TreeIndex.since(i2, id, 1)
        assertFalse(d.has("full")); assertFalse(d.optBoolean("same"))
        assertEquals(setOf("a/x.json", "a/z.txt"), d.getJSONObject("set").keys().asSequence().toSet())
        assertEquals("a/y.png", d.getJSONArray("del").getString(0))
        // 다시 y 가 생기면 del 에서 빠지고 set 에 들어간다 (1 → 3)
        val i3 = TreeIndex.update(i2, tree(Triple("a/x.json", 11, 200), Triple("a/z.txt", 5, 200), Triple("a/y.png", 30, 300)), 4000)
        val d3 = TreeIndex.since(i3, id, 1)
        assertEquals(0, d3.getJSONArray("del").length())
        assertEquals(30L, d3.getJSONObject("set").getJSONArray("a/y.png").getLong(1))
        // 모르는 장부 id(앱 자료 초기화) · 너무 오래된 gen → 전체
        assertTrue(TreeIndex.since(i3, "other", 3).has("full"))
        var idx = i3
        repeat(TreeIndex.LOG_MAX + 2) { k -> idx = TreeIndex.update(idx, tree(Triple("a/x.json", 100L + k, 9)), 5000L + k) }
        assertTrue(TreeIndex.since(idx, id, 2).has("full"))
        assertEquals(TreeIndex.LOG_MAX, idx.getJSONArray("log").length())
    }

    @Test fun bigFullIsGzipped() {
        val many = (1..600).map { Triple("a/file-$it.json", it.toLong(), 1000L) }.toTypedArray()
        val i = TreeIndex.update(null, tree(*many), 1)
        val r = TreeIndex.since(i, null, 0)
        assertTrue(r.has("fullz"))
        val text = GZIPInputStream(ByteArrayInputStream(Base64.getDecoder().decode(r.getString("fullz")))).readBytes().toString(Charsets.UTF_8)
        assertEquals(601, JSONObject(text).length())
    }
}
