package com.seyoungjo.tvdashboard.ui

import android.annotation.SuppressLint
import android.app.Activity
import android.graphics.Bitmap
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
 *  · 사진: 페이지가 전환 효과(모핑·쉐이딩·닦아내기·원형·블라인드)로 띄우고 정한 초만큼 보여 준 뒤 ytDone.
 *    동영상 → 사진은 마지막 장면을 떠서(PixelCopy) 페이지에 넘겨 그 장면에서 사진으로 전환된다
 *  · 공지 간편 수정: 공지 줄 오른쪽의 수정 아이콘 → 위쪽 팝업에 숫자패드(3×4)로 공지 수정 비밀번호(6자리, TV 설정) →
 *    맞으면 공지 입력란 + 화면 키보드 → main/공지.txt 저장. 수정 중에는 화면을 눌러도 대시보드로 넘어가지 않는다
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
    private val mask = CornerMask(activity)
    private var stagePx = 1f                             // 화면보호기 1080p 기준 1px 이 실제 몇 px 인지 (위아래 이동용)
    private var blurBmp: Bitmap? = null
    private var webItem = false                          // 지금 페이지가 보여 주는 항목(사진 · 유튜브)인가
    private var pageW = 0.0                              // 페이지 폭(CSS px) — WebView 픽셀 ↔ CSS px 환산
    private var editBtns: List<DoubleArray> = emptyList() // 공지 수정 아이콘들의 위치 (CSS px: x, y, w, h)
    private var savedSoftInput = 0
    var active = false
        private set
    /** 공지 수정 중 — 터치·키는 화면보호기 페이지로 (대시보드로 넘어가지 않음) */
    var editing = false
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
        // 둥근 모서리: 윤곽 자르기(clipToOutline)는 경계가 계단처럼 거칠어서, 부드럽게(안티에일리어싱) 그린 덮개를 맨 위에 씌운다
        box.clipChildren = true
        box.addView(mask, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
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
        if (editing) setEditing(false)
        active = false
        handler.removeCallbacks(blurTick)
        releasePlayer()
        ytSeq++
        webItem = false
        box.animate().cancel(); box.alpha = 1f
        web?.evaluateJavascript("window.ssWebStop&&ssWebStop(0)", null)
        layer.visibility = View.GONE
        web?.onPause()
    }

    /** 아래 멘트를 잠시 바꾼다 (한 번 터치 → '한 번 더 눌러 주세요'), null 이면 원래 멘트로 */
    fun prompt(msg: String?) {
        if (active) web?.evaluateJavascript("window.ssPrompt&&ssPrompt(${JSONObject.quote(msg ?: "")})", null)
    }

    /** 수정 중이던 공지를 닫는다 (리모컨 뒤로 등) */
    fun cancelEdit() {
        pinOkUntil = 0
        web?.evaluateJavascript("window.ssNoticeCancel&&ssNoticeCancel()", null)
        setEditing(false)
    }

    /**
     * 이 점(앱 화면 좌표, root 기준)이 공지 수정 아이콘 위인가 — 그 터치는 화면보호기 페이지로 보낸다.
     * 앱 화면 안의 뷰들은 따로 확대/이동하지 않으므로 left/top 을 더해 WebView 안 좌표로, 다시 CSS px 로 바꾼다.
     */
    fun hitsEditButton(x: Float, y: Float, root: View): Boolean {
        val wv = web ?: return false
        if (editBtns.isEmpty() || !active || pageW <= 0 || wv.width <= 0) return false
        var ox = 0f
        var oy = 0f
        var v: View = wv
        while (v !== root) {
            ox += v.left + v.translationX
            oy += v.top + v.translationY
            v = v.parent as? View ?: return false
        }
        val k = wv.width / pageW
        val cx = (x - ox) / k
        val cy = (y - oy) / k
        val pad = 14                                        // 손가락이 살짝 빗나가도 아이콘으로
        return editBtns.any { r -> cx >= r[0] - pad && cx <= r[0] + r[2] + pad && cy >= r[1] - pad && cy <= r[1] + r[3] + pad }
    }

    /**
     * 수정 시작/끝: WebView 가 키(화면 키보드 · 외부 키보드)를 받게 한다.
     * 키보드가 떠도 화면을 줄이지 않는다(ADJUST_NOTHING) — 팝업이 위쪽에 있어 가리지 않고, 화면보호기 배치도 그대로
     */
    private fun setEditing(on: Boolean) {
        if (editing == on) return
        editing = on
        val wv = web
        val win = activity.window
        if (on) {
            savedSoftInput = win.attributes.softInputMode
            win.setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_ADJUST_NOTHING)
            wv?.isFocusable = true
            wv?.isFocusableInTouchMode = true
            wv?.requestFocus()
        } else {
            hideKeyboard()
            wv?.clearFocus()
            wv?.isFocusable = false
            wv?.isFocusableInTouchMode = false
            win.setSoftInputMode(savedSoftInput)
        }
    }

    // 공지 수정 비밀번호: 5번 틀리면 1분 동안 막는다
    private var pinFails = 0
    private var pinLockUntil = 0L
    @Volatile private var pinOkUntil = 0L                // 비밀번호가 맞은 뒤 저장할 수 있는 시각 (10분)

    private fun hideKeyboard() {
        val wv = web ?: return
        val imm = activity.getSystemService(android.content.Context.INPUT_METHOD_SERVICE) as? android.view.inputmethod.InputMethodManager
        imm?.hideSoftInputFromWindow(wv.windowToken, 0)
    }

    /** main 폴더 내용이 바뀌었을 때 (숫자·그래프 다시 읽기) */
    fun refresh() {
        applyDark()
        if (active) web?.evaluateJavascript("window.ssRefresh&&ssRefresh()", null)
    }

    private fun pageBg(): Int = if (AppSettings.darkMode) DARK_BG else 0xFFEAEEF3.toInt()

    /** 다크 모드가 바뀌면 페이지 바깥 바탕 · 동영상 칸 모서리 색도 같이 */
    private fun applyDark() {
        web?.setBackgroundColor(pageBg())
        mask.invalidate()
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
        wv.setBackgroundColor(pageBg())
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
            .put("dark", AppSettings.darkMode)
            .toString()

        /** 화면보호기의 달/해 버튼 → 다크 모드 저장 (페이지는 이미 바꿔 그림) */
        @JavascriptInterface
        fun setDark(on: Boolean) {
            AppSettings.darkMode = on
            handler.post { applyDark() }
        }

        /** 공지 수정 아이콘들의 위치 (CSS px) — JSON [[x, y, w, h], …] */
        @JavascriptInterface
        fun editRects(json: String, vw: Double) {
            val list = try {
                val a = org.json.JSONArray(json)
                (0 until a.length()).map { i -> a.getJSONArray(i).let { r -> DoubleArray(4) { r.getDouble(it) } } }
            } catch (_: Exception) { emptyList() }
            handler.post { editBtns = list; if (vw > 0) pageW = vw }
        }

        /** 공지 수정 시작/끝 */
        @JavascriptInterface
        fun noticeEdit(on: Boolean) {
            handler.post { if (active || !on) setEditing(on) }
        }

        /** 공지 입력란에 커서가 들어갔을 때 화면 키보드를 띄운다 */
        @JavascriptInterface
        fun showKeys() {
            handler.post {
                val wv = web ?: return@post
                val imm = activity.getSystemService(android.content.Context.INPUT_METHOD_SERVICE) as? android.view.inputmethod.InputMethodManager
                wv.requestFocus()
                imm?.showSoftInput(wv, 0)
            }
        }

        /** 공지 수정 비밀번호가 정해져 있는가 (없으면 페이지가 'TV 설정에서 먼저 정하세요' 안내) */
        @JavascriptInterface
        fun pinSet(): Boolean = AppSettings.noticePin.length == 6

        /** 비밀번호 확인 → "ok" · "wrong:<남은 횟수>" · "locked:<초>" · "unset" (비밀번호는 페이지에 넘기지 않는다) */
        @JavascriptInterface
        fun checkPin(pin: String): String {
            val want = AppSettings.noticePin
            if (want.length != 6) return "unset"
            val now = System.currentTimeMillis()
            synchronized(this) {
                if (now < pinLockUntil) return "locked:" + ((pinLockUntil - now) / 1000 + 1)
                if (java.security.MessageDigest.isEqual(pin.trim().toByteArray(), want.toByteArray())) {
                    pinFails = 0; pinOkUntil = now + 10 * 60_000; return "ok"
                }
                pinFails++
                if (pinFails >= 5) { pinFails = 0; pinLockUntil = now + 60_000; return "locked:60" }
                return "wrong:" + (5 - pinFails)
            }
        }

        /** 공지 저장 → main/공지.txt (끝나면 페이지의 ssNoticeSaved 로 알려 줌) */
        @JavascriptInterface
        fun saveNotice(text: String) {
            val app = activity.applicationContext
            val path = "$folder/공지.txt"
            if (System.currentTimeMillis() > pinOkUntil) {         // 비밀번호를 거치지 않았거나 너무 오래됨
                handler.post { web?.evaluateJavascript("window.ssNoticeSaved&&ssNoticeSaved(false,${JSONObject.quote("비밀번호를 다시 입력하세요.")})", null) }
                return
            }
            Thread {
                val err = try {
                    val data = text.replace("\r\n", "\n").toByteArray(Charsets.UTF_8)
                    com.seyoungjo.tvdashboard.data.FileOps(app).put(path, data.size.toLong(), data.inputStream(), true)
                    null
                } catch (e: Exception) {
                    Log.w(TAG, "notice save failed", e)
                    e.message ?: e.javaClass.simpleName
                }
                handler.post {
                    web?.evaluateJavascript("window.ssNoticeSaved&&ssNoticeSaved(${err == null},${JSONObject.quote(err ?: "")})", null)
                    if (err == null) { pinOkUntil = 0; setEditing(false) }
                }
            }.start()
        }

        /** 사진: 페이지가 앞 장면(동영상 마지막 장면)을 깔았다 → 이제 동영상 칸을 내려도 끊김 없음 */
        @JavascriptInterface
        fun prevShown(seq: Int) {
            handler.post { if (seq == ytSeq && webItem) { releasePlayer(); box.visibility = View.INVISIBLE } }
        }

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
            handler.post { if (vw > 0) pageW = vw; placeBox(x, y, w, h, vw, vh) }
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
        box.visibility = if (items.isEmpty() || webItem) View.INVISIBLE else View.VISIBLE
        mask.radius = radiusPx
        box.post {
            player?.let { fitVideo(it.videoWidth, it.videoHeight) }
            if (active && player == null && !webItem) play()     // 사진·유튜브는 페이지가 보여 주는 중 — 칸이 바뀌어도 다시 시작하지 않음
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
        fun opts(o: JSONObject) = o.put("crop", item.crop).put("align", item.align).put("fill", if (item.blur) "blur" else "color")
            .put("color", String.format("#%06X", item.color and 0xFFFFFF)).put("loop", list.size == 1)
            .put("custom", item.custom).put("base", if (item.cropBase) "crop" else "fit")
            .put("scale", item.scale).put("halign", item.hAlign).put("offsetX", item.offsetX)
            .put("valign", item.vAlign).put("offsetY", item.offsetY)
        if (item.youtube != null) {                      // 유튜브: 페이지가 재생
            releasePlayer()
            webItem = true
            box.visibility = View.INVISIBLE
            val o = opts(JSONObject().put("seq", ++ytSeq).put("id", item.youtube).put("vertical", item.vertical))
            web?.evaluateJavascript("window.ssYoutube&&ssYoutube($o)", null)
            return
        }
        val f = item.file ?: run { next(); return }
        if (item.image) {                                // 사진: 페이지가 전환 효과로 띄움
            if (pageW <= 0) return                       // 페이지가 아직 준비 전 — 칸 위치를 알려 오면(placeBox) 다시 불린다
            val seq = ++ytSeq
            val o = opts(JSONObject().put("seq", seq).put("name", f.name).put("dur", item.duration).put("effect", item.effect))
            val fromVideo = player != null && box.visibility == View.VISIBLE && box.width > 0
            webItem = true
            if (fromVideo) snapshotBox { prev ->         // 동영상 마지막 장면에서 사진으로 전환
                if (seq != ytSeq || !active) return@snapshotBox
                if (prev != null) o.put("prev", prev) else { releasePlayer(); box.visibility = View.INVISIBLE }
                web?.evaluateJavascript("window.ssImage&&ssImage($o)", null)
                handler.postDelayed({ if (seq == ytSeq && webItem && player != null) { releasePlayer(); box.visibility = View.INVISIBLE } }, 1500)
            } else {
                releasePlayer()
                box.visibility = View.INVISIBLE
                web?.evaluateJavascript("window.ssImage&&ssImage($o)", null)
            }
            return
        }
        val s = surface
        if (s == null || box.width <= 0) {               // 칸·영상 판(Surface)이 준비되면 다시 불린다 (placeBox · onSurfaceTextureAvailable)
            if (s == null && box.width > 0) {
                // 영상 판은 TextureView 가 크기를 갖고 화면에 그려질 때 생긴다 → 칸을 투명하게 띄워 판부터 만든다
                // (사진·유튜브 다음이면 칸이 숨겨져 있어 판이 없을 수 있음)
                if (tex.width <= 0 || tex.height <= 0) {
                    tex.layoutParams = FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT)
                    tex.translationX = 0f; tex.translationY = 0f
                }
                box.animate().cancel()
                box.alpha = 0f
                box.visibility = View.VISIBLE
            }
            return
        }
        ytSeq++
        val afterWeb = webItem                           // 사진·유튜브 다음: 동영상 칸을 서서히 나타나게
        webItem = false
        web?.evaluateJavascript("window.ssWebStop&&ssWebStop(${if (afterWeb) 900 else 0})", null)
        applyFill(item)
        box.animate().cancel()
        box.alpha = if (afterWeb) 0f else 1f
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
                if (box.alpha < 1f) box.animate().alpha(1f).setStartDelay(120).setDuration(550).start()
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

    /** 동영상 칸에 보이는 그대로(블러 채움 포함)를 떠서 JPEG data URL 로 (Android 8+, 실패하면 null) */
    private fun snapshotBox(done: (String?) -> Unit) {
        if (Build.VERSION.SDK_INT < 26) { done(null); return }
        try {
            val loc = IntArray(2)
            box.getLocationInWindow(loc)
            var sc = 1f
            var v: View? = box
            while (v != null) { sc *= v.scaleX; v = v.parent as? View }
            val w = (box.width * sc).roundToInt()
            val h = (box.height * sc).roundToInt()
            if (w <= 0 || h <= 0) { done(null); return }
            val k = min(1f, 960f / max(w, h))
            val bmp = Bitmap.createBitmap(max(1, (w * k).roundToInt()), max(1, (h * k).roundToInt()), Bitmap.Config.ARGB_8888)
            android.view.PixelCopy.request(activity.window, android.graphics.Rect(loc[0], loc[1], loc[0] + w, loc[1] + h), bmp, { r ->
                if (r != android.view.PixelCopy.SUCCESS) { bmp.recycle(); done(null); return@request }
                val out = java.io.ByteArrayOutputStream()
                bmp.compress(Bitmap.CompressFormat.JPEG, 82, out)
                bmp.recycle()
                done("data:image/jpeg;base64," + android.util.Base64.encodeToString(out.toByteArray(), android.util.Base64.NO_WRAP))
            }, handler)
        } catch (e: Exception) {
            Log.w(TAG, "snapshot failed", e)
            done(null)
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
            placeBlur(tex.translationX, tex.translationY, w, h)
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
        placeBlur((bw - w) / 2f, (bh - h) / 2f, w, h)       // 확장(가운데). 크롭은 블러를 쓰지 않음
        ensureBlurBmp(vw, vh)
    }

    /**
     * 남는 곳 블러의 자리: 영상(x, y, w, h)의 가운데를 중심으로 영상 비율 그대로 키워 칸의 가장 먼 끝까지 덮고도 남게.
     * 블러는 가장자리로 갈수록 흐려져 어두워지므로, 칸에 고정하면 영상을 옮겼을 때 어두운 가장자리만 보인다 →
     * 영상을 따라가게 해서 영상 가까운 곳은 밝게 이어지고 어두운 가장자리는 칸 밖으로 (화면보호기 페이지의 blurRect 와 같은 계산)
     */
    private fun placeBlur(x: Float, y: Float, w: Int, h: Int) {
        val bw = box.width
        val bh = box.height
        if (w <= 0 || h <= 0 || bw <= 0 || bh <= 0) return
        val ar = w.toFloat() / h
        val cx = x + w / 2f
        val cy = y + h / 2f
        val hw = max(cx, bw - cx)
        val hh = max(cy, bh - cy)
        val bigW = max(2 * hw, 2 * hh * ar) * 1.18f
        val bigH = bigW / ar
        blur.scaleType = ImageView.ScaleType.FIT_XY
        blur.layoutParams = FrameLayout.LayoutParams(bigW.roundToInt(), bigH.roundToInt(), Gravity.TOP or Gravity.START)
        blur.translationX = cx - bigW / 2
        blur.translationY = cy - bigH / 2
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

    /** 칸의 네 모서리 바깥을 화면보호기 배경색으로 부드럽게 덮는다 (위쪽·아래쪽은 배경 그라데이션에 맞춘 색) */
    private class CornerMask(ctx: android.content.Context) : View(ctx) {
        var radius = 0f
            set(v) { field = v; invalidate() }
        private val paint = android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG)
        private val path = android.graphics.Path()

        override fun onDraw(c: android.graphics.Canvas) {
            if (radius <= 0f) return
            val w = width.toFloat()
            val h = height.toFloat()
            path.reset()
            path.fillType = android.graphics.Path.FillType.EVEN_ODD
            path.addRect(0f, 0f, w, h, android.graphics.Path.Direction.CW)
            path.addRoundRect(0f, 0f, w, h, radius, radius, android.graphics.Path.Direction.CW)
            c.save(); c.clipRect(0f, 0f, w, h / 2)
            paint.color = if (AppSettings.darkMode) DARK_BG else 0xFFECF0F4.toInt(); c.drawPath(path, paint)
            c.restore(); c.save(); c.clipRect(0f, h / 2, w, h)
            paint.color = if (AppSettings.darkMode) DARK_BG else 0xFFE8ECF2.toInt(); c.drawPath(path, paint)
            c.restore()
        }
    }

    companion object {
        private const val TAG = "Screensaver"
        private const val URL = "https://" + ContentStore.WEB_HOST + "/assets/screensaver/index.html"
        /** 다크 모드 페이지 바탕색 (ss.css html.dark 와 같게) */
        private const val DARK_BG = 0xFF0E1319.toInt()
    }
}
