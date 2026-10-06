package com.seyoungjo.tvdashboard.ui

import android.annotation.SuppressLint
import android.app.Activity
import android.graphics.Bitmap
import android.graphics.Outline
import android.graphics.RenderEffect
import android.graphics.Shader
import android.graphics.SurfaceTexture
import android.media.MediaPlayer
import android.os.Build
import android.os.Handler
import android.util.Log
import android.view.Gravity
import android.view.Surface
import android.view.TextureView
import android.view.View
import android.view.ViewOutlineProvider
import android.webkit.JavascriptInterface
import android.webkit.RenderProcessGoneDetail
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.ImageView
import androidx.webkit.WebViewAssetLoader
import com.seyoungjo.tvdashboard.R
import com.seyoungjo.tvdashboard.data.AppSettings
import com.seyoungjo.tvdashboard.data.ContentStore
import com.seyoungjo.tvdashboard.data.PlayItem
import org.json.JSONObject
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * 화면보호기 — 자료/main 폴더가 있으면 대기 화면 대신 띄운다.
 *  · 화면(공지·매출·생산량 그래프·시계)은 앱에 내장된 assets/screensaver 페이지가 그린다 (main 의 JSON 4개를 읽음)
 *  · 오른쪽 동영상은 페이지가 알려 준 칸에 TV 기본 플레이어(MediaPlayer + TextureView)로 1.mp4 2.mp4 … 순서대로 재생
 *  · 재생 목록·영상별 표시 방식은 main/설정.json 의 playlist (PC 프로그램에서 정함, MenuScanner.mainPlaylist)
 *  · 확장: 작은 쪽을 칸에 맞춰 영상 전체가 보이고, 남는 곳은 블러(같은 영상을 작게 떠서 흐리게) 또는 단색
 *  · 크롭: 칸을 꽉 채우고 긴 쪽을 자른다 — 위쪽/가운데/아래쪽 맞춤 (가로가 넘치면 왼쪽/가운데/오른쪽)
 *  · 유튜브(쇼츠 포함): 화면보호기 페이지가 유튜브 공식 플레이어로 재생하고 끝나면 ytDone 으로 알려 준다
 *    (인터넷이 없거나 퍼가기가 막힌 영상은 건너뜀)
 */
class Screensaver(
    private val activity: Activity,
    private val layer: FrameLayout,
    private val assetLoader: WebViewAssetLoader,
    private val handler: Handler,
) {
    private val box: FrameLayout = layer.findViewById(R.id.ssVideoBox)
    private val blur: ImageView = layer.findViewById(R.id.ssBlur)
    private val tex: TextureView = layer.findViewById(R.id.ssVideo)
    private val dim: View = layer.findViewById(R.id.ssDim)

    private var web: WebView? = null
    private var surface: Surface? = null
    private var player: MediaPlayer? = null
    private var items: List<PlayItem> = emptyList()
    private var current: PlayItem? = null
    private var ytSeq = 0
    private var index = 0
    private var errors = 0
    private var radiusPx = 0f
    private var stagePx = 1f                             // 화면보호기 1080p 기준 1px 이 실제 몇 px 인지 (위아래 이동용)
    private var blurBmp: Bitmap? = null
    var active = false
        private set

    /** 자료 폴더 안의 실제 이름 (main / Main …) — 페이지가 그 이름으로 JSON 을 읽는다 */
    var folder = "main"


    private val blurTick = object : Runnable {
        override fun run() {
            if (!active) return
            val bmp = blurBmp
            val c = current
            if (c != null && !c.crop && c.blur && bmp != null && tex.isAvailable && player?.isPlaying == true) {
                try {
                    tex.getBitmap(bmp)
                    blur.setImageBitmap(bmp)
                    blur.invalidate()
                } catch (_: Exception) {
                }
            }
            handler.postDelayed(this, 250)
        }
    }

    init {
        // 시스템 바(아래 내비게이션 바 등)가 보이면 그만큼 비켜서 그린다 — 맨 아래 멘트가 잘리지 않게
        layer.setOnApplyWindowInsetsListener { v, insets ->
            if (Build.VERSION.SDK_INT >= 30) {
                val i = insets.getInsets(android.view.WindowInsets.Type.systemBars() or android.view.WindowInsets.Type.displayCutout())
                v.setPadding(i.left, i.top, i.right, i.bottom)
            } else {
                @Suppress("DEPRECATION")
                v.setPadding(insets.systemWindowInsetLeft, insets.systemWindowInsetTop, insets.systemWindowInsetRight, insets.systemWindowInsetBottom)
            }
            insets
        }
        box.outlineProvider = object : ViewOutlineProvider() {
            override fun getOutline(view: View, outline: Outline) = outline.setRoundRect(0, 0, view.width, view.height, radiusPx)
        }
        box.clipToOutline = true
        if (Build.VERSION.SDK_INT >= 31) {
            blur.setRenderEffect(RenderEffect.createBlurEffect(36f, 36f, Shader.TileMode.CLAMP))
        }
        tex.surfaceTextureListener = object : TextureView.SurfaceTextureListener {
            override fun onSurfaceTextureAvailable(st: SurfaceTexture, w: Int, h: Int) {
                surface = Surface(st)
                if (active && player == null) play()
            }
            override fun onSurfaceTextureSizeChanged(st: SurfaceTexture, w: Int, h: Int) {}
            override fun onSurfaceTextureDestroyed(st: SurfaceTexture): Boolean {
                releasePlayer()
                surface?.release()
                surface = null
                return true
            }
            override fun onSurfaceTextureUpdated(st: SurfaceTexture) {}
        }
    }

    /** main 폴더의 재생 목록(동영상·유튜브·영상별 설정)이 바뀌었을 때 */
    fun setPlaylist(list: List<PlayItem>) {
        val changed = list.map { it.key } != items.map { it.key }
        items = list
        if (active && changed) {
            index = 0
            errors = 0
            releasePlayer()
            play()
        }
    }

    fun show() {
        active = true
        layer.visibility = View.VISIBLE
        val wv = web ?: createWeb()
        wv.onResume()
        if (wv.url == null) wv.loadUrl(URL) else wv.evaluateJavascript("window.ssShow&&ssShow()", null)
        index = 0
        errors = 0
        if (box.width > 0) play()
        handler.removeCallbacks(blurTick)
        handler.post(blurTick)
    }

    fun hide() {
        active = false
        handler.removeCallbacks(blurTick)
        releasePlayer()
        ytSeq++
        web?.evaluateJavascript("window.ssYoutubeStop&&ssYoutubeStop()", null)
        layer.visibility = View.GONE
        web?.onPause()
    }

    /** main 폴더 내용이 바뀌었을 때 (숫자·그래프 다시 읽기) */
    fun refresh() {
        if (active) web?.evaluateJavascript("window.ssRefresh&&ssRefresh()", null)
    }

    fun destroy() {
        hide()
        web?.let { layer.removeView(it); it.destroy() }
        web = null
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun createWeb(): WebView {
        val wv = WebView(activity)
        wv.layoutParams = FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT)
        wv.setBackgroundColor(0xFFEAEEF3.toInt())
        wv.isFocusable = false
        with(wv.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = false
            cacheMode = WebSettings.LOAD_NO_CACHE
            mediaPlaybackRequiresUserGesture = false      // 유튜브 자동 재생 (소리 없이)
            useWideViewPort = true
            loadWithOverviewMode = true
            textZoom = 100
            layoutAlgorithm = WebSettings.LayoutAlgorithm.NORMAL   // 글자 자동 확대(text autosizing) 끔
            setSupportZoom(false)
        }
        wv.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? =
                assetLoader.shouldInterceptRequest(request.url)

            override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
                if (view === web) {
                    web = null
                    handler.post {
                        layer.removeView(view)
                        view.destroy()
                        if (active) show()
                    }
                }
                return true
            }
        }
        wv.webChromeClient = WebChromeClient()
        wv.addJavascriptInterface(Bridge(), "TVSS")
        layer.addView(wv, 0)
        web = wv
        return wv
    }

    /** 페이지 ↔ 앱 */
    private inner class Bridge {
        @JavascriptInterface
        fun config(): String = JSONObject()
            .put("message", AppSettings.idleMessage.trim())
            .put("blink", AppSettings.idleMsgHideSec > 0)
            .put("videos", items.size)
            .put("folder", folder)
            .put("title", AppSettings.headerTitle)
            .toString()

        /** 유튜브 한 편이 끝났거나(ok) 재생할 수 없을 때(!ok) → 다음 항목 */
        @JavascriptInterface
        fun ytDone(seq: Int, ok: Boolean) {
            handler.post {
                if (!active || seq != ytSeq) return@post
                if (ok) errors = 0 else errors++
                index++
                play()
            }
        }

        /** 동영상 칸 위치 (CSS px) — 페이지 폭 vw 기준이라 WebView 실제 픽셀로 환산 */
        @JavascriptInterface
        fun videoRect(x: Double, y: Double, w: Double, h: Double, vw: Double, vh: Double) {
            handler.post { placeBox(x, y, w, h, vw, vh) }
        }
    }

    private fun placeBox(x: Double, y: Double, w: Double, h: Double, vw: Double, vh: Double) {
        val wv = web ?: return
        if (vw <= 0 || wv.width <= 0) return
        val k = wv.width / vw
        val lp = FrameLayout.LayoutParams((w * k).roundToInt(), (h * k).roundToInt())
        lp.leftMargin = (x * k).roundToInt()
        lp.topMargin = (y * k).roundToInt()
        lp.gravity = Gravity.TOP or Gravity.START
        radiusPx = (22 * min(vw / 1920, vh / 1080) * k).toFloat()
        stagePx = (min(vw / 1920, vh / 1080) * k).toFloat()
        box.layoutParams = lp
        box.visibility = if (items.isEmpty() || current?.youtube != null) View.INVISIBLE else View.VISIBLE
        box.invalidateOutline()
        box.post {
            player?.let { fitVideo(it.videoWidth, it.videoHeight) }
            if (active && player == null) play()
        }
    }

    // ── 재생 ─────────────────────────────────────────────────────────
    private fun play() {
        val list = items
        if (!active || list.isEmpty()) {
            box.visibility = View.INVISIBLE
            return
        }
        if (errors >= list.size * 2) {                   // 전부 재생 실패(인터넷 끊김 등) → 1분 뒤 다시
            errors = 0
            handler.postDelayed({ if (active && player == null) play() }, 60_000)
            return
        }
        val item = list[index % list.size]
        current = item
        if (item.youtube != null) {                      // 유튜브: 페이지가 재생
            releasePlayer()
            box.visibility = View.INVISIBLE
            val o = JSONObject().put("seq", ++ytSeq).put("id", item.youtube).put("vertical", item.vertical)
                .put("crop", item.crop).put("align", item.align).put("fill", if (item.blur) "blur" else "color")
                .put("color", String.format("#%06X", item.color and 0xFFFFFF)).put("loop", list.size == 1)
                .put("custom", item.custom).put("base", if (item.cropBase) "crop" else "fit")
                .put("scale", item.scale).put("halign", item.hAlign).put("offsetX", item.offsetX)
                .put("valign", item.vAlign).put("offsetY", item.offsetY)
            web?.evaluateJavascript("window.ssYoutube&&ssYoutube($o)", null)
            return
        }
        val f = item.file ?: run { next(); return }
        val s = surface
        if (s == null || box.width <= 0) return          // 칸·화면이 준비되면 다시 불린다
        ytSeq++
        web?.evaluateJavascript("window.ssYoutubeStop&&ssYoutubeStop()", null)
        applyFill(item)
        box.visibility = View.VISIBLE
        releasePlayer()
        val mp = MediaPlayer()
        player = mp
        try {
            mp.setSurface(s)
            mp.setDataSource(f.path)
            mp.isLooping = list.size == 1
            val vol = if (AppSettings.prefs.getBoolean("idle_video_sound", false)) 1f else 0f
            mp.setVolume(vol, vol)
            mp.setOnVideoSizeChangedListener { _, w, h -> fitVideo(w, h) }
            mp.setOnPreparedListener {
                if (player !== it) return@setOnPreparedListener
                errors = 0
                fitVideo(it.videoWidth, it.videoHeight)
                it.start()
            }
            mp.setOnCompletionListener {
                if (player !== it) return@setOnCompletionListener
                index++
                play()
            }
            mp.setOnErrorListener { p, what, extra ->
                Log.w(TAG, "video error $what/$extra: ${f.name}")
                if (player === p) next()
                true
            }
            mp.prepareAsync()
        } catch (e: Exception) {
            Log.w(TAG, "video open failed: ${f.name}", e)
            next()
        }
    }

    private fun next() {
        releasePlayer()
        errors++
        index++
        handler.postDelayed({ if (active && player == null) play() }, 1000)
    }

    /** 확장일 때 남는 곳: 블러 또는 단색 */
    private fun applyFill(item: PlayItem) {
        val blurOn = !item.crop && item.blur
        blur.visibility = if (blurOn) View.VISIBLE else View.INVISIBLE
        dim.visibility = if (blurOn) View.VISIBLE else View.INVISIBLE
        if (!blurOn) blur.setImageDrawable(null)
        box.setBackgroundColor(if (!item.crop && !item.blur) item.color else 0xFF0D1620.toInt())
    }

    private fun releasePlayer() {
        val p = player ?: return
        player = null
        try { p.reset() } catch (_: Exception) {}
        try { p.release() } catch (_: Exception) {}
    }

    /** 확장: 원본 비율 그대로 칸 안에 최대 크기 / 크롭: 칸을 덮는 크기, 넘치는 쪽은 위·가운데·아래(왼·가운데·오른) 맞춤 */
    private fun fitVideo(vw: Int, vh: Int) {
        val bw = box.width
        val bh = box.height
        val item = current ?: return
        if (vw <= 0 || vh <= 0 || bw <= 0 || bh <= 0) return
        val cover = max(bw.toDouble() / vw, bh.toDouble() / vh)
        val contain = min(bw.toDouble() / vw, bh.toDouble() / vh)
        val s = when {
            item.custom -> (if (item.cropBase) cover else contain) * item.scale / 100.0   // 직접 조절: 기준 × 크기(%)
            item.crop -> cover
            else -> contain
        }
        val w = (vw * s).roundToInt()
        val h = (vh * s).roundToInt()
        if (item.custom) {                                 // 직접 조절: 기준선(위·가운데·아래 / 왼·가운데·오른)에서 px 만큼
            val ox = item.offsetX * stagePx
            val oy = item.offsetY * stagePx
            tex.layoutParams = FrameLayout.LayoutParams(w, h, Gravity.TOP or Gravity.START)
            tex.translationX = when (item.hAlign) { "left" -> ox; "right" -> bw - w - ox; else -> (bw - w) / 2f + ox }
            tex.translationY = when (item.vAlign) { "top" -> oy; "bottom" -> bh - h - oy; else -> (bh - h) / 2f + oy }
            ensureBlurBmp(vw, vh)
            return
        }
        val gravity = if (!item.crop) Gravity.CENTER else if (h > bh) {
            Gravity.CENTER_HORIZONTAL or when (item.align) { "top" -> Gravity.TOP; "bottom" -> Gravity.BOTTOM; else -> Gravity.CENTER_VERTICAL }
        } else {
            Gravity.CENTER_VERTICAL or when (item.align) { "top" -> Gravity.START; "bottom" -> Gravity.END; else -> Gravity.CENTER_HORIZONTAL }
        }
        tex.layoutParams = FrameLayout.LayoutParams(w, h, gravity)
        tex.translationX = 0f
        tex.translationY = 0f
        ensureBlurBmp(vw, vh)
    }

    private fun ensureBlurBmp(vw: Int, vh: Int) {
        // 블러용 작은 그림 (영상 비율, 긴 쪽 64px)
        val bwSmall = if (vw >= vh) 64 else max(1, 64 * vw / vh)
        val bhSmall = if (vw >= vh) max(1, 64 * vh / vw) else 64
        val old = blurBmp
        if (old == null || old.width != bwSmall || old.height != bhSmall) {
            blurBmp = Bitmap.createBitmap(bwSmall, bhSmall, Bitmap.Config.ARGB_8888)
        }
    }

    companion object {
        private const val TAG = "Screensaver"
        private const val URL = "https://" + ContentStore.WEB_HOST + "/assets/screensaver/index.html"
    }
}
