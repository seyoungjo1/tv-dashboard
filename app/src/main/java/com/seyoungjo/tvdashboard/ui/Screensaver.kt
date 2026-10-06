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
import org.json.JSONObject
import java.io.File
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * 화면보호기 — 자료/main 폴더가 있으면 대기 화면 대신 띄운다.
 *  · 화면(공지·매출·생산량 그래프·시계)은 앱에 내장된 assets/screensaver 페이지가 그린다 (main 의 JSON 4개를 읽음)
 *  · 오른쪽 동영상은 페이지가 알려 준 칸에 TV 기본 플레이어(MediaPlayer + TextureView)로 1.mp4 2.mp4 … 순서대로 재생
 *  · 맞춤(기본): 영상 비율이 칸과 다르면 원본은 가운데에 온전히, 남는 위아래/양옆은 같은 영상을 작게 떠서 흐리게
 *    (영상을 두 번 재생하지 않는다 — 0.25초마다 작은 그림을 떠서 블러)
 *  · 크롭: 칸을 꽉 채우고 넘치는 부분은 잘라 낸다 (main/설정.json 의 videoFit = "crop", PC 프로그램에서 설정)
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

    private var web: WebView? = null
    private var surface: Surface? = null
    private var player: MediaPlayer? = null
    private var videos: List<File> = emptyList()
    private var index = 0
    private var errors = 0
    private var radiusPx = 0f
    private var blurBmp: Bitmap? = null
    var active = false
        private set

    /** 자료 폴더 안의 실제 이름 (main / Main …) — 페이지가 그 이름으로 JSON 을 읽는다 */
    var folder = "main"

    /** true = 크롭(꽉 채움), false = 맞춤(블러 채움) */
    var crop = false
        set(value) {
            if (field == value) return
            field = value
            player?.let { fitVideo(it.videoWidth, it.videoHeight) }
        }

    private val blurTick = object : Runnable {
        override fun run() {
            if (!active) return
            val bmp = blurBmp
            if (!crop && bmp != null && tex.isAvailable && player?.isPlaying == true) {
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

    /** main 폴더의 동영상 목록이 바뀌었을 때 */
    fun setVideos(list: List<File>) {
        val changed = list.map { it.path to it.lastModified() } != videos.map { it.path to it.lastModified() }
        videos = list
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
            useWideViewPort = true
            loadWithOverviewMode = true
            textZoom = 100
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
            .put("videos", videos.size)
            .put("folder", folder)
            .put("title", AppSettings.headerTitle)
            .toString()

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
        box.layoutParams = lp
        box.visibility = if (videos.isEmpty()) View.INVISIBLE else View.VISIBLE
        box.invalidateOutline()
        box.post {
            player?.let { fitVideo(it.videoWidth, it.videoHeight) }
            if (active && player == null) play()
        }
    }

    // ── 재생 ─────────────────────────────────────────────────────────
    private fun play() {
        val vids = videos
        val s = surface
        if (!active || vids.isEmpty()) {
            box.visibility = View.INVISIBLE
            return
        }
        if (s == null || box.width <= 0) return          // 칸·화면이 준비되면 다시 불린다
        box.visibility = View.VISIBLE
        releasePlayer()
        val f = vids[index % vids.size]
        val mp = MediaPlayer()
        player = mp
        try {
            mp.setSurface(s)
            mp.setDataSource(f.path)
            mp.isLooping = vids.size == 1
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
        if (errors < videos.size * 2) handler.postDelayed({ if (active && player == null) play() }, 1000)
    }

    private fun releasePlayer() {
        val p = player ?: return
        player = null
        try { p.reset() } catch (_: Exception) {}
        try { p.release() } catch (_: Exception) {}
    }

    /** 맞춤: 원본 비율 그대로 칸 안에 최대 크기 (남는 곳은 블러) / 크롭: 칸을 덮는 크기 (넘치는 곳은 잘림) */
    private fun fitVideo(vw: Int, vh: Int) {
        val bw = box.width
        val bh = box.height
        if (vw <= 0 || vh <= 0 || bw <= 0 || bh <= 0) return
        val s = if (crop) max(bw.toDouble() / vw, bh.toDouble() / vh) else min(bw.toDouble() / vw, bh.toDouble() / vh)
        blur.visibility = if (crop) View.INVISIBLE else View.VISIBLE
        val lp = FrameLayout.LayoutParams((vw * s).roundToInt(), (vh * s).roundToInt(), Gravity.CENTER)
        tex.layoutParams = lp
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
