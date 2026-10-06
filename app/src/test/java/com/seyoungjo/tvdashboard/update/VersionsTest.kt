package com.seyoungjo.tvdashboard.update

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class VersionsTest {
    @Test fun codeMatchesGradleRule() {
        assertEquals(1_000_000L, Versions.codeFromName("v1.0.0"))
        assertEquals(1_002_003L, Versions.codeFromName("1.2.3"))
        assertEquals(2_000_010L, Versions.codeFromName("2.0.10-beta"))
        assertNull(Versions.codeFromName("latest"))
    }

    @Test fun ordering() {
        assertTrue(Versions.codeFromName("1.10.0")!! > Versions.codeFromName("1.9.99")!!)
        assertTrue(Versions.codeFromName("2.0.0")!! > Versions.codeFromName("1.999.999")!!)
    }
}
