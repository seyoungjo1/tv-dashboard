package com.seyoungjo.tvdashboard.ui

import android.webkit.WebView
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature

/**
 * 대시보드 웹 화면이 PC 와 같은 배치로 보이게.
 *
 * 앱은 TV 화면의 16:9 영역을 1920dp 로 맞추지만(fitDensity), 웹 엔진은 그 맞춤을 모르고 TV 의 원래 화면 밀도로
 * 페이지 배율(devicePixelRatio)을 정한다. 원래 밀도가 높은 TV(예: 1.5배)에서는 페이지가 보는 화면 폭이 1920dp 보다
 * 좁아져(예: 1796dp 칸 → 1197) 반응형 페이지가 '작은 화면'용 글자·배치로 바뀐다 → PC 보다 글자가 크다.
 *
 * → 배율이 앱 기준과 다르면 페이지의 viewport 폭을 웹 칸의 dp 폭으로 고정하고, 그만큼 축소해 칸에 꼭 맞춘다.
 *   PC 에서 같은 크기 창으로 연 것과 같은 폭·높이로 계산되므로 @media 규칙과 글자 크기가 PC 와 같아진다.
 *   배율이 같은 기기(대부분의 PC · 1배 TV)에서는 아무것도 바꾸지 않는다.
 */
object FitViewport {
    private fun script(density: Float) = """
(function () {
  if (window.__tvFit) return; window.__tvFit = 1;
  var D = $density, r = window.devicePixelRatio || 1;
  if (Math.abs(r - D) < 0.05) return;                          // 웹 배율이 앱과 같으면 그대로
  function apply() {
    var px = (window.outerWidth || 0) * r;                     // 웹 칸의 실제 폭(기기 px)
    if (!(px > 0)) return;
    var W = Math.round(px / D), s = (D / r).toFixed(4);
    var c = 'width=' + W + ', initial-scale=' + s + ', minimum-scale=' + s + ', maximum-scale=' + s + ', user-scalable=no';
    var ms = document.querySelectorAll('meta[name=viewport]'), m = ms.length ? ms[ms.length - 1] : null;
    if (!m) {
      if (!document.head && !document.documentElement) return;
      m = document.createElement('meta'); m.name = 'viewport';
      (document.head || document.documentElement).appendChild(m);
    }
    if (m.content !== c) m.content = c;
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', apply); else apply();
  addEventListener('load', apply);
  addEventListener('resize', function () { setTimeout(apply, 50); });   // 사이드바 접기·펴기로 칸 폭이 바뀔 때
})();
"""

    /** WebView 를 만들 때 한 번: 모든 페이지 시작 시 들어가도록 등록. 등록하지 못하는 기기면 false */
    fun install(wv: WebView, density: Float): Boolean {
        if (!WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)) return false
        return try {
            WebViewCompat.addDocumentStartJavaScript(wv, script(density), setOf("*"))
            true
        } catch (_: Exception) {
            false
        }
    }

    /** 문서 시작 스크립트를 못 쓰는 기기: 페이지가 다 뜬 뒤에라도 맞춘다 */
    fun applyLate(wv: WebView, density: Float) = wv.evaluateJavascript(script(density), null)
}
