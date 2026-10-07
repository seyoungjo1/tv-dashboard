package com.seyoungjo.tvdashboard.ui

import android.view.InputDevice
import android.view.MotionEvent

/**
 * 터치 진단: 최근 손가락 터치 몇 번의 모양(도구 · 입력 장치 · 압력 · 흔들림 · 시간)을 기억해 TV ⚙ 설정에 보여 준다.
 * 손터치가 안 먹을 때 원인(흔들림이 큰지, 터치판이 손가락을 어떤 장치로 보내는지)을 확인하는 용도
 */
object TouchDiag {
    private class G(val tool: Int, val source: Int, val device: String, val pressure: Float, val down: Long) {
        var maxMove = 0f
        var pointers = 1
        var ms = 0L
        var moved = false
        var x = 0f
        var y = 0f
    }

    private val list = ArrayDeque<G>()
    private var cur: G? = null

    @Synchronized
    fun add(ev: MotionEvent) {
        when (ev.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                val name = InputDevice.getDevice(ev.deviceId)?.name ?: "?"
                cur = G(ev.getToolType(0), ev.source, name, ev.pressure, ev.eventTime).also { it.x = ev.x; it.y = ev.y }
            }
            else -> cur?.let { g ->
                g.pointers = maxOf(g.pointers, ev.pointerCount)
                g.maxMove = maxOf(g.maxMove, Math.hypot((ev.x - g.x).toDouble(), (ev.y - g.y).toDouble()).toFloat())
                if (ev.actionMasked == MotionEvent.ACTION_UP || ev.actionMasked == MotionEvent.ACTION_CANCEL) {
                    g.ms = ev.eventTime - g.down
                    list.addFirst(g)
                    while (list.size > 6) list.removeLast()
                    cur = null
                }
            }
        }
    }

    /** 이번 터치는 끌기로 판단됨 (보정 범위를 넘게 움직임) */
    @Synchronized
    fun moved() { cur?.moved = true }

    @Synchronized
    fun summary(): String {
        if (list.isEmpty()) return "아직 터치 기록이 없습니다. 대시보드를 손가락으로 몇 번 누른 뒤 다시 여세요."
        return list.joinToString("\n") { g ->
            val tool = when (g.tool) {
                MotionEvent.TOOL_TYPE_FINGER -> "손가락"; MotionEvent.TOOL_TYPE_STYLUS -> "펜"
                MotionEvent.TOOL_TYPE_ERASER -> "지우개"; MotionEvent.TOOL_TYPE_MOUSE -> "마우스"; else -> "알 수 없음"
            }
            "$tool · 흔들림 ${g.maxMove.toInt()}px${if (g.moved) "(끌기)" else ""} · ${g.ms}ms · 손가락 ${g.pointers} · 압력 ${"%.2f".format(g.pressure)} · " +
                "source 0x${Integer.toHexString(g.source)} · ${g.device}"
        }
    }
}
