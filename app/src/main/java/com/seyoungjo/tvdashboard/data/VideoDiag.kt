package com.seyoungjo.tvdashboard.data

/** 화면보호기 동영상 재생 상태 — 마지막 실패 이유를 TV 상태(PC 화면)와 화면보호기 페이지에 보여 준다 */
object VideoDiag {
    @Volatile var last: String = ""          // 비어 있으면 정상
    @Volatile var at: Long = 0L

    fun fail(name: String, why: String) {
        last = "$name — $why"
        at = System.currentTimeMillis()
    }

    fun ok() { last = ""; at = 0L }
}
