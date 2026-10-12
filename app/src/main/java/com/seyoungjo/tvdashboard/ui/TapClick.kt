package com.seyoungjo.tvdashboard.ui

import android.webkit.WebView

/**
 * 손가락 '한 번 누름' 을 웹 화면의 클릭으로.
 *
 * 이 TV 터치판에서는 손가락 터치가 WebView 까지 들어가도(스크롤은 됨) WebView 가 그것을 클릭으로 판정하지 못한다
 * (마우스는 그 판정을 거치지 않아 정상, 앱 버튼인 사이드바는 누름-뗌만으로 눌려 정상).
 * → 손가락을 떼면 페이지 안에서 그 자리에 클릭(mousedown · mouseup · click)을 만든다.
 *   WebView 가 스스로 클릭을 만든 경우(정상 기기)는 그 클릭을 보고 건너뛰어 두 번 눌리지 않는다.
 */
object TapClick {
    /** 페이지가 뜰 때마다 넣는 보조 스크립트 (대시보드 · 화면보호기 공통) */
    private const val JS = """
(function () {
  if (window.__tvTap) return;
  var last = 0;
  addEventListener('click', function () { last = Date.now(); }, true);   // WebView 가 스스로 만든 클릭
  window.__tvTap = function (x, y) {
    var at = Date.now();
    setTimeout(function () {
      if (last >= at - 450) return;                                        // 이미 클릭이 났으면 건너뜀
      var el = document.elementFromPoint(x, y);
      if (!el) return;
      var o = { bubbles: true, cancelable: true, clientX: x, clientY: y, view: window, button: 0, buttons: 1 };
      var p = { pointerType: 'touch', isPrimary: true, pointerId: 1 };
      try { el.dispatchEvent(new PointerEvent('pointerdown', Object.assign({}, o, p))); } catch (e) {}
      el.dispatchEvent(new MouseEvent('mousedown', o));
      try { var f = el.closest('input,textarea,select,button,a,[tabindex]'); if (f && f.focus) f.focus(); } catch (e) {}
      o.buttons = 0;
      try { el.dispatchEvent(new PointerEvent('pointerup', Object.assign({}, o, p))); } catch (e) {}
      el.dispatchEvent(new MouseEvent('mouseup', o));
      el.dispatchEvent(new MouseEvent('click', o));
    }, 350);
  };
  // 웹 칸 안의 비율(0~1)로 받은 자리 → 페이지 좌표. 페이지 배율·축소·스크롤과 상관없이 손가락이 닿은 자리
  window.__tvTapF = function (fx, fy) {
    var v = window.visualViewport;
    var x = v ? v.offsetLeft + fx * v.width : fx * innerWidth, y = v ? v.offsetTop + fy * v.height : fy * innerHeight;
    window.__tvTap(Math.round(x), Math.round(y));
  };
})();
"""

    fun inject(wv: WebView) = wv.evaluateJavascript(JS, null)

    /** 창 좌표 (x, y) 가 이 WebView 안이면 그 자리(CSS px)에 클릭을 넣고 true */
    fun click(wv: WebView?, x: Float, y: Float): Boolean {
        wv ?: return false
        if (!wv.isShown || wv.width <= 0) return false
        val loc = IntArray(2)
        wv.getLocationInWindow(loc)
        val lx = x - loc[0]
        val ly = y - loc[1]
        if (lx < 0 || ly < 0 || lx > wv.width || ly > wv.height) return false
        // 칸 안의 비율로 넘긴다 — 예전처럼 배율·스크롤로 좌표를 계산하면 스크롤된 페이지나 배율이 다른 TV 에서 엉뚱한 곳이 눌린다
        val fx = lx / wv.width
        val fy = ly / wv.height.coerceAtLeast(1)
        wv.evaluateJavascript("window.__tvTapF&&__tvTapF($fx,$fy)", null)
        return true
    }
}
