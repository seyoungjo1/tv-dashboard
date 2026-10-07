package com.seyoungjo.tvdashboard.ui

import android.annotation.SuppressLint
import android.content.Intent
import android.graphics.BitmapFactory
import android.graphics.Color
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.view.Gravity
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.webkit.RenderProcessGoneDetail
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.ImageButton
import android.widget.ImageView
import android.widget.TextView
import android.widget.Toast
import android.widget.VideoView
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import androidx.webkit.WebViewAssetLoader
import com.seyoungjo.tvdashboard.BuildConfig
import com.seyoungjo.tvdashboard.R
import com.seyoungjo.tvdashboard.data.AppEvent
import com.seyoungjo.tvdashboard.data.AppSettings
import com.seyoungjo.tvdashboard.data.ChangeBus
import com.seyoungjo.tvdashboard.data.ContentStore
import com.seyoungjo.tvdashboard.data.MenuEntry
import com.seyoungjo.tvdashboard.data.MenuScanner
import com.seyoungjo.tvdashboard.data.PlayItem
import com.seyoungjo.tvdashboard.relay.Pairing
import com.seyoungjo.tvdashboard.relay.RelaySettings
import com.seyoungjo.tvdashboard.server.NetInfo
import com.seyoungjo.tvdashboard.server.ServerService
import com.seyoungjo.tvdashboard.update.UpdateManager
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors

/**
 * 메인 화면: 왼쪽 = 정사각형 아이콘 메뉴, 오른쪽 = 선택한 폴더의 index.html (대시보드)
 */
class MainActivity : AppCompatActivity() {

    private lateinit var header: View
    private lateinit var headerTitle: TextView
    private lateinit var headerClock: TextView
    private lateinit var headerDate: TextView
    private lateinit var headerLogo: ImageView
    private lateinit var menuPanel: View
    private lateinit var menuList: RecyclerView
    private lateinit var webContainer: FrameLayout
    private lateinit var emptyView: View
    private lateinit var emptyText: TextView
    private lateinit var fullscreenButton: ImageButton
    private lateinit var settingsButton: View
    private lateinit var idleOverlay: View
    private lateinit var idleVideo: VideoView
    private lateinit var idleMessage: TextView
    private var webView: WebView? = null
    private lateinit var screensaver: Screensaver
    private var hasMain = false                       // 자료/main 폴더가 있으면 대기 화면 = 화면보호기

    private val adapter = MenuAdapter { openEntry(it, userAction = true) }
    private val handler = Handler(Looper.getMainLooper())
    private val io = Executors.newSingleThreadExecutor()
    private lateinit var assetLoader: WebViewAssetLoader

    private var entries: List<MenuEntry> = emptyList()
    private var signature: String? = null
    private var current: MenuEntry? = null
    private var fullscreen = false
    private var sidebarOpen = true
    private var resumed = false
    private var lastBack = 0L
    private var swallowGesture = false
    private var passGesture = false                       // 이번 터치는 화면보호기 페이지로 (공지 수정)
    private lateinit var reveal: View
    private var clearHistoryPending = false
    private var idleVideos: List<File> = emptyList()
    private var idleVideoIndex = 0
    private var idleVideoErrors = 0
    private var msgVisible = true
    private var previewIdleRequested = false

    private val busListener: (AppEvent) -> Unit = { onEvent(it) }
    private val idleRunnable = Runnable { showIdle() }
    private val reloadRunnable = Runnable { reloadCurrent() }
    private val menuRefreshRunnable = Runnable { refreshMenu() }
    private val dateFormat = SimpleDateFormat("yyyy.MM.dd", Locale.KOREA)
    private val clockFormat = SimpleDateFormat("HH:mm", Locale.KOREA)
    private val clockRunnable = object : Runnable {
        override fun run() {
            val now = Date()
            headerDate.text = dateFormat.format(now)
            headerClock.text = clockFormat.format(now)
            handler.postDelayed(this, 60_000L - System.currentTimeMillis() % 60_000L + 50)
        }
    }
    private val scanRunnable = object : Runnable {
        override fun run() {
            refreshMenu()
            handler.postDelayed(this, SCAN_MS)
        }
    }
    private val blinkRunnable = object : Runnable {
        override fun run() {
            if (idleOverlay.visibility != View.VISIBLE) return
            if (msgVisible) {
                idleMessage.visibility = View.INVISIBLE
                msgVisible = false
                val hide = AppSettings.idleMsgHideSec
                if (hide > 0) handler.postDelayed(this, hide * 1000L)
            } else {
                idleMessage.visibility = View.VISIBLE
                msgVisible = true
                val show = AppSettings.idleMsgShowSec
                if (show > 0) handler.postDelayed(this, show * 1000L)
            }
        }
    }

    /**
     * 4K(3840×2160) 기준 비율로 보이게: 화면의 16:9 영역이 1920dp 가 되도록 화면 밀도(densityDpi)를 낮춘다.
     * 예전에는 앱 전체를 scaleX/Y 로 줄였는데, 웹 화면(대시보드·화면보호기)은 부모가 변형되면
     * 손터치 좌표가 어긋나고(마우스는 정상) 오른쪽 일부를 그리지 않았다 → 변형 없이 밀도로 맞춘다.
     */
    override fun attachBaseContext(newBase: android.content.Context) {
        super.attachBaseContext(fitDensity(newBase))
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        keep16by9()
        reveal = findViewById(R.id.revealOverlay)
        header = findViewById(R.id.header)
        headerTitle = findViewById(R.id.headerTitle)
        headerClock = findViewById(R.id.headerClock)
        headerDate = findViewById(R.id.headerDate)
        headerLogo = findViewById(R.id.headerLogo)
        menuPanel = findViewById(R.id.menuPanel)
        menuList = findViewById(R.id.menuList)
        webContainer = findViewById(R.id.webContainer)
        emptyView = findViewById(R.id.emptyView)
        emptyText = findViewById(R.id.emptyText)
        fullscreenButton = findViewById(R.id.fullscreenButton)
        settingsButton = findViewById(R.id.settingsButton)
        idleOverlay = findViewById(R.id.idleOverlay)
        idleVideo = findViewById(R.id.idleVideo)
        idleMessage = findViewById(R.id.idleMessage)

        assetLoader = WebViewAssetLoader.Builder()
            .setDomain(ContentStore.WEB_HOST)
            .addPathHandler(ContentStore.WEB_PREFIX, DataPathHandler(applicationContext))
            // 앱 내장 폰트 등: https://appassets.androidplatform.net/assets/fonts/Pretendard-Bold.woff2
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(applicationContext))
            .build()
        screensaver = Screensaver(this, findViewById(R.id.ssLayer), assetLoader, handler)

        menuList.layoutManager = LinearLayoutManager(this)
        menuList.adapter = adapter
        menuList.itemAnimator = null

        createWebView()

        settingsButton.setOnClickListener { openSettings() }
        findViewById<View>(R.id.idleNowButton).setOnClickListener { showIdle() }   // 대기화면 바로보기 (기다리지 않고)
        findViewById<View>(R.id.sidebarToggle).setOnClickListener { setSidebar(!sidebarOpen) }
        setSidebar(AppSettings.prefs.getBoolean("sidebar_open", true), save = false)
        fullscreenButton.setOnClickListener { setFullscreen(!fullscreen) }

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() = onBack()
        })

        ServerService.start(this)
        ChangeBus.add(busListener)
        hideSystemBars()
        previewIdleRequested = intent?.getBooleanExtra(EXTRA_PREVIEW_IDLE, false) == true
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        if (intent.getBooleanExtra(EXTRA_PREVIEW_IDLE, false)) previewIdleRequested = true
    }

    override fun onResume() {
        super.onResume()
        resumed = true
        applyKeepScreenOn()
        applyHeader()
        hideSystemBars()
        handler.removeCallbacks(clockRunnable)
        clockRunnable.run()
        refreshMenu(force = true)
        handler.removeCallbacks(scanRunnable)
        handler.postDelayed(scanRunnable, SCAN_MS)
        if (previewIdleRequested) {
            previewIdleRequested = false
            handler.postDelayed({ showIdle() }, 600)
        } else {
            resetIdle()
        }
        checkPendingUploadedApk()
    }

    override fun onPause() {
        resumed = false
        handler.removeCallbacks(scanRunnable)
        handler.removeCallbacks(idleRunnable)
        handler.removeCallbacks(clockRunnable)
        if (idleOverlay.visibility == View.VISIBLE) hideIdle()
        super.onPause()
    }

    override fun onDestroy() {
        screensaver.destroy()
        ChangeBus.remove(busListener)
        handler.removeCallbacksAndMessages(null)
        webView?.destroy()
        webView = null
        io.shutdown()
        super.onDestroy()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) hideSystemBars()
    }

    // ── WebView ───────────────────────────────────────────────────────────
    @SuppressLint("SetJavaScriptEnabled")
    private fun createWebView() {
        webView?.let { old ->
            webContainer.removeView(old)
            old.destroy()
        }
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG)
        val wv = WebView(this)
        wv.layoutParams = FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT
        )
        wv.isFocusable = true
        wv.isFocusableInTouchMode = true
        wv.setBackgroundColor(ContextCompat.getColor(this, R.color.bg))
        with(wv.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = false
            mediaPlaybackRequiresUserGesture = false
            cacheMode = WebSettings.LOAD_NO_CACHE
            useWideViewPort = true
            loadWithOverviewMode = true
            textZoom = 100
            setSupportZoom(false)
            builtInZoomControls = false
            displayZoomControls = false
        }
        wv.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? =
                assetLoader.shouldInterceptRequest(request.url)

            override fun onPageFinished(view: WebView, url: String?) {
                TapClick.inject(view)
                if (clearHistoryPending) {
                    view.clearHistory()
                    clearHistoryPending = false
                }
            }

            override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
                // 장시간 표시 중 WebView 렌더러가 종료되면 새로 만들어 다시 표시
                if (view === webView) {
                    webView = null
                    handler.post {
                        webContainer.removeView(view)
                        view.destroy()
                        createWebView()
                        current?.let { openEntry(it, userAction = false) }
                    }
                }
                return true
            }
        }
        wv.webChromeClient = WebChromeClient()
        webContainer.addView(wv, 0)
        webView = wv
    }

    private fun openEntry(e: MenuEntry, userAction: Boolean) {
        current = e
        adapter.selectedFolder = e.folder
        AppSettings.lastFolder = e.folder
        val index = e.indexFile
        if (index == null) {
            webView?.visibility = View.INVISIBLE
            showMessage("「${e.title}」\n\n${getString(R.string.no_index)}\n관리 웹에서 index.html 을 업로드하면 자동으로 표시됩니다.")
            return
        }
        emptyView.visibility = View.GONE
        webView?.visibility = View.VISIBLE
        clearHistoryPending = true
        webView?.loadUrl(ContentStore.webUrl(e.folder, index))
        if (userAction) webView?.requestFocus()
    }

    private fun reloadCurrent() {
        val c = current ?: return
        if (c.indexFile == null) return
        webView?.reload()
    }

    private fun showMessage(text: String) {
        emptyText.text = text
        emptyView.visibility = View.VISIBLE
    }

    private fun showGuide() {
        webView?.visibility = View.INVISIBLE
        val port = AppSettings.port
        val addrs = NetInfo.addresses()
        val urls = if (addrs.isEmpty()) "  (네트워크 연결 없음)" else addrs.joinToString("\n") {
            "  http://${it.ip}:$port" + if (it.tailscale) "   ← Tailscale" else ""
        }
        val err = ServerService.lastError?.let { "\n\n⚠ $it" } ?: ""
        showMessage(
            "${getString(R.string.empty_title)}\n\n" +
                "관리자 PC 브라우저에서 아래 주소로 접속해 폴더를 만들고\n" +
                "index.html · 이미지 · JSON 을 업로드하세요.\n\n$urls\n\n" +
                "관리자 비밀번호: 이 화면 왼쪽 아래 ⚙ 설정 → '관리자 비밀번호'\n\n" +
                (if (!RelaySettings.configured) "다른 망의 PC 에서 관리: PC 프로그램(tvrun.bat)에 연결 코드  ${Pairing.code}  입력\n\n" else "") +
                "자료 폴더: ${ContentStore.root(this).path}$err"
        )
    }

    // ── 메뉴 ──────────────────────────────────────────────────────────────
    private fun refreshMenu(force: Boolean = false) {
        val app = applicationContext
        if (io.isShutdown) return
        io.execute {
            val root = ContentStore.root(app)
            val list = MenuScanner.scan(root)
            val videos = MenuScanner.idleVideos(root)
            val main = MenuScanner.mainDir(root)
            val playlist = MenuScanner.mainPlaylist(main)
            val sig = MenuScanner.signature(list)
            handler.post { applyMenu(list, sig, videos, main?.name, playlist, force) }
        }
    }

    private fun applyMenu(
        list: List<MenuEntry>, sig: String, videos: List<File>, mainName: String?, playlist: List<PlayItem>,
        force: Boolean,
    ) {
        if (isDestroyed) return
        idleVideos = videos
        val main = mainName != null
        hasMain = main
        if (mainName != null) screensaver.folder = mainName
        screensaver.setPlaylist(playlist)
        if (!main && screensaver.active && idleOverlay.visibility == View.VISIBLE) hideIdle()
        if (!force && sig == signature) return
        signature = sig
        entries = list
        adapter.submit(list)
        if (list.isEmpty()) {
            current = null
            adapter.selectedFolder = null
            showGuide()
            return
        }
        val cur = current
        val keep = cur?.let { c -> list.firstOrNull { it.folder == c.folder } }
        if (keep == null || cur.indexFile != keep.indexFile) {
            val target = keep ?: list.firstOrNull { it.folder == AppSettings.lastFolder } ?: list.first()
            openEntry(target, userAction = false)
        } else {
            current = keep
            adapter.selectedFolder = keep.folder
            if (keep.stamp != cur.stamp && AppSettings.autoRefresh) scheduleReload()
        }
        if (currentFocus == null) focusSelectedTile()
    }

    private fun focusSelectedTile() {
        if (entries.isEmpty()) { settingsButton.requestFocus(); return }
        val idx = entries.indexOfFirst { it.folder == current?.folder }.coerceAtLeast(0)
        menuList.scrollToPosition(idx)
        menuList.post { menuList.findViewHolderForAdapterPosition(idx)?.itemView?.requestFocus() }
    }

    private fun scheduleReload() {
        handler.removeCallbacks(reloadRunnable)
        handler.postDelayed(reloadRunnable, 800)
    }

    private fun onEvent(e: AppEvent) {
        when (e) {
            is AppEvent.Changed -> {
                handler.removeCallbacks(menuRefreshRunnable)
                handler.postDelayed(menuRefreshRunnable, 400)
                if (e.path.equals(LOGO_FILE, ignoreCase = true)) applyHeader()
                val top = e.path.substringBefore('/')
                if (MenuScanner.isMain(top) || e.path.equals(LOGO_FILE, ignoreCase = true)) screensaver.refresh()
                val c = current
                if (c != null && AppSettings.autoRefresh &&
                    (e.path == c.folder || e.path.startsWith(c.folder + "/"))
                ) scheduleReload()
            }
            AppEvent.Reload -> {
                refreshMenu(force = true)
                scheduleReload()
            }
            AppEvent.SettingsChanged -> {
                applyKeepScreenOn()
                applyHeader()
                if (idleOverlay.visibility == View.VISIBLE) {
                    idleMessage.text = AppSettings.idleMessage
                    screensaver.refresh()
                } else resetIdle()
            }
            is AppEvent.UpdateUploaded -> if (resumed) checkPendingUploadedApk()
        }
    }

    // ── 전체 화면 / 뒤로 ──────────────────────────────────────────────────
    /** 왼쪽 사이드바 숨기기/열기 (상단 ☰ 버튼, 상태는 기억) */
    private fun setSidebar(open: Boolean, save: Boolean = true) {
        sidebarOpen = open
        if (!fullscreen) menuPanel.visibility = if (open) View.VISIBLE else View.GONE
        findViewById<TextView>(R.id.sidebarToggle).text = if (open) "◁" else "▷"
        placeHandle()
        if (save) AppSettings.prefs.edit().putBoolean("sidebar_open", open).apply()
        if (open && !fullscreen) focusSelectedTile()
    }

    /**
     * 앱 화면을 항상 16:9 로, 그리고 TV(4K 3840×2160 = 1920×1080dp) 보다 작은 화면에서는 통째로 같은 비율로 줄인다.
     *  · 앱은 늘 TV 크기(1920×1080dp)로 배치하고, 화면의 16:9 영역에 맞춰 확대/축소만 한다
     *    → 상단바 글자 · 사이드바 · 아이콘 · 손잡이 · 대시보드 · 화면보호기가 휴대폰에서도 TV 와 같은 배치로 작게 보임
     *  · 비율이 다른 화면에서는 가운데 16:9 만 쓰고 남는 곳은 검게. 터치 위치는 Android 가 함께 환산한다
     *  · TV 처럼 1920×1080dp 이상이면 그대로(축소 없음) 꽉 채운다
     */
    /** 화면 안의 16:9 영역만 쓰고 나머지는 검게 (크기는 attachBaseContext 의 밀도로 맞춤 — 변형 없음) */
    private fun keep16by9() {
        val content = findViewById<FrameLayout>(android.R.id.content)
        content.setBackgroundColor(Color.BLACK)
        content.clipChildren = true
        val app = content.getChildAt(0) ?: return
        content.addOnLayoutChangeListener { _, l, t, r, b, _, _, _, _ ->
            val w = r - l
            val h = b - t
            if (w <= 0 || h <= 0) return@addOnLayoutChangeListener
            val (tw, th) = if (w * 9 > h * 16) Pair(h * 16 / 9, h) else Pair(w, w * 9 / 16)   // 화면 안의 16:9 영역
            val lp = app.layoutParams as FrameLayout.LayoutParams
            if (lp.width != tw || lp.height != th || lp.gravity != Gravity.CENTER || app.scaleX != 1f) {
                content.post {
                    app.layoutParams = FrameLayout.LayoutParams(tw, th, Gravity.CENTER)
                    app.scaleX = 1f
                    app.scaleY = 1f
                }
            }
        }
    }

    // ── 화면 전환 효과 ─────────────────────────────────────────────────────
    /**
     * 화면보호기 → 대시보드 (리모컨): 모핑 — 화면보호기가 살짝 작아지며 모서리가 둥글어지고 흐려지며 사라지고,
     * 뒤의 대시보드는 약간 크게 시작해 제자리로 줄어들며 나타난다. 끝나면 action(화면보호기 닫기).
     */
    private var morphing = false
    private fun morphTransition(action: () -> Unit) {
        val ss = idleOverlay
        val main = header.parent as View                 // 상단바 + 사이드바 + 대시보드
        if (morphing || ss.width <= 0) { if (!morphing) action(); return }
        morphing = true
        var radius = 0f
        ss.outlineProvider = object : android.view.ViewOutlineProvider() {
            override fun getOutline(v: View, o: android.graphics.Outline) = o.setRoundRect(0, 0, v.width, v.height, radius)
        }
        ss.clipToOutline = true
        main.scaleX = 1.06f; main.scaleY = 1.06f; main.alpha = 0f
        val anim = android.animation.ValueAnimator.ofFloat(0f, 1f)
        anim.duration = 650
        anim.interpolator = android.view.animation.PathInterpolator(0.3f, 0f, 0.2f, 1f)
        anim.addUpdateListener {
            val p = it.animatedValue as Float
            val sc = 1f - 0.12f * p
            ss.scaleX = sc; ss.scaleY = sc
            ss.alpha = 1f - p
            radius = 48f * resources.displayMetrics.density * p
            ss.invalidateOutline()
            if (android.os.Build.VERSION.SDK_INT >= 31) {
                val b = 0.1f + 40f * p
                ss.setRenderEffect(android.graphics.RenderEffect.createBlurEffect(b, b, android.graphics.Shader.TileMode.DECAL))
            }
            val m = 1.06f - 0.06f * p
            main.scaleX = m; main.scaleY = m
            main.alpha = minOf(1f, p * 1.4f)
        }
        anim.addListener(object : android.animation.AnimatorListenerAdapter() {
            override fun onAnimationEnd(animation: android.animation.Animator) {
                action()
                ss.scaleX = 1f; ss.scaleY = 1f; ss.alpha = 1f
                ss.clipToOutline = false
                if (android.os.Build.VERSION.SDK_INT >= 31) ss.setRenderEffect(null)
                main.scaleX = 1f; main.scaleY = 1f; main.alpha = 1f
                morphing = false
            }
        })
        anim.start()
    }

    /**
     * 화면보호기 → 대시보드: 누른 자리에서 동그라미가 퍼지며 화면을 덮고 → action(화면보호기 닫기) → 동그라미가 사라지며 대시보드가 보인다.
     * 좌표는 창 기준 — 앱 화면을 비율로 줄여 쓰는 경우(keep16by9)도 맞게 환산한다. 음수면 화면 가운데에서.
     */
    private fun circleTransition(wx: Float, wy: Float, action: () -> Unit) {
        val root = reveal.parent as View
        if (root.width <= 0 || !reveal.isAttachedToWindow) { action(); return }
        val (x, y) = toRoot(wx, wy)
        val radius = kotlin.math.hypot(maxOf(x, root.width - x), maxOf(y, root.height - y))
        reveal.animate().cancel()
        reveal.bringToFront()
        reveal.alpha = 1f
        reveal.visibility = View.VISIBLE
        val anim = android.view.ViewAnimationUtils.createCircularReveal(reveal, x.toInt(), y.toInt(), 0f, radius)
        anim.duration = 420
        anim.interpolator = android.view.animation.DecelerateInterpolator(1.6f)
        anim.addListener(object : android.animation.AnimatorListenerAdapter() {
            override fun onAnimationEnd(animation: android.animation.Animator) {
                action()
                reveal.animate().alpha(0f).setStartDelay(260).setDuration(300)
                    .withEndAction { reveal.visibility = View.INVISIBLE; reveal.alpha = 1f }.start()
            }
        })
        anim.start()
    }

    /** 창 좌표 → 앱 화면(1920×1080 기준, keep16by9 로 축소될 수 있음) 좌표. 음수면 화면 가운데 */
    private fun toRoot(wx: Float, wy: Float): Pair<Float, Float> {
        val root = reveal.parent as View
        if (wx < 0 || wy < 0) return root.width / 2f to root.height / 2f
        val c = IntArray(2)
        (root.parent as View).getLocationInWindow(c)                     // 앱 화면을 담은 칸(축소 전 좌표계)
        return ((wx - c[0] - root.left - root.pivotX) / root.scaleX + root.pivotX) to
            ((wy - c[1] - root.top - root.pivotY) / root.scaleY + root.pivotY)
    }

    /** 화면보호기에서 한 번 터치했을 때: 누른 자리에 물결(동그라미 두 겹이 퍼지며 사라짐) */
    private fun touchRipple(wx: Float, wy: Float) {
        val root = reveal.parent as? FrameLayout ?: return
        if (root.width <= 0) return
        val (x, y) = toRoot(wx, wy)
        val d = resources.displayMetrics.density
        val v = object : View(this) {
            var p = 0f
            val fill = android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG).apply { color = 0xFF2F80ED.toInt() }
            val ring = android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG).apply {
                style = android.graphics.Paint.Style.STROKE; color = 0xFF2F80ED.toInt()
            }
            override fun onDraw(c: android.graphics.Canvas) {
                val e = 1f - (1f - p) * (1f - p)                      // 빠르게 퍼지다 천천히
                fill.alpha = (90 * (1f - p)).toInt()
                c.drawCircle(x, y, 70f * d * e, fill)
                ring.strokeWidth = 5f * d * (1f - p) + 1f
                ring.alpha = (230 * (1f - p)).toInt()
                c.drawCircle(x, y, 130f * d * e, ring)
                val q = ((p - 0.18f) / 0.82f).coerceIn(0f, 1f)          // 두 번째 동그라미는 조금 늦게
                if (q > 0f) {
                    ring.alpha = (170 * (1f - q)).toInt()
                    ring.strokeWidth = 3f * d * (1f - q) + 1f
                    c.drawCircle(x, y, 190f * d * (1f - (1f - q) * (1f - q)), ring)
                }
            }
        }
        root.addView(v, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        val anim = android.animation.ValueAnimator.ofFloat(0f, 1f)
        anim.duration = 700
        anim.addUpdateListener { v.p = it.animatedValue as Float; v.invalidate() }
        anim.addListener(object : android.animation.AnimatorListenerAdapter() {
            override fun onAnimationEnd(animation: android.animation.Animator) { root.removeView(v) }
        })
        anim.start()
    }

    // 화면보호기는 두 번 터치해야 나간다: 한 번 누르면 물결 + '한 번 더 눌러 주세요', 5초 안에 다시 누르면 대시보드로
    private var tapArmedAt = 0L
    private val disarmTapRunnable = Runnable { disarmTap() }
    private fun disarmTap() {
        handler.removeCallbacks(disarmTapRunnable)
        if (tapArmedAt == 0L) return
        tapArmedAt = 0L
        if (hasMain) screensaver.prompt(null)
        else if (idleOverlay.visibility == View.VISIBLE) {
            val msg = AppSettings.idleMessage.trim()
            idleMessage.text = msg
            msgVisible = true
            idleMessage.visibility = if (msg.isEmpty()) View.GONE else View.VISIBLE
            val show = AppSettings.idleMsgShowSec
            if (msg.isNotEmpty() && show > 0) handler.postDelayed(blinkRunnable, show * 1000L)
        }
    }
    private fun armTap() {
        tapArmedAt = android.os.SystemClock.uptimeMillis()
        handler.removeCallbacks(disarmTapRunnable)
        handler.postDelayed(disarmTapRunnable, TAP_WINDOW_MS)
        if (hasMain) screensaver.prompt(TAP_AGAIN)
        else {
            handler.removeCallbacks(blinkRunnable)
            idleMessage.text = TAP_AGAIN
            msgVisible = true
            idleMessage.visibility = View.VISIBLE
        }
    }

    /** 손잡이는 대시보드 위에 겹쳐 있으므로 사이드바가 보이면 그 오른쪽, 아니면 화면 왼쪽 끝에 붙인다 */
    private fun placeHandle() {
        val h = findViewById<View>(R.id.sidebarToggle)
        val lp = h.layoutParams as FrameLayout.LayoutParams
        lp.marginStart = if (!fullscreen && sidebarOpen) resources.getDimensionPixelSize(R.dimen.sidebar_width) else 0
        h.layoutParams = lp
    }

    private fun setFullscreen(on: Boolean) {
        fullscreen = on
        menuPanel.visibility = if (on || !sidebarOpen) View.GONE else View.VISIBLE
        placeHandle()
        header.visibility = if (on) View.GONE else View.VISIBLE
        fullscreenButton.setImageResource(if (on) R.drawable.ic_menu else R.drawable.ic_fullscreen)
        fullscreenButton.contentDescription = getString(if (on) R.string.exit_fullscreen else R.string.fullscreen)
        if (!on) focusSelectedTile()
    }

    private fun onBack() {
        val wv = webView
        when {
            idleOverlay.visibility == View.VISIBLE -> hideIdle()
            fullscreen -> setFullscreen(false)
            wv != null && wv.canGoBack() -> wv.goBack()
            !sidebarOpen -> setSidebar(true)
            !menuList.hasFocus() && entries.isNotEmpty() -> focusSelectedTile()
            else -> {
                val now = System.currentTimeMillis()
                if (now - lastBack < 2000) finish()
                else {
                    lastBack = now
                    Toast.makeText(this, R.string.press_back_again, Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    // ── 대기 화면 (루트 동영상 + 멘트) ────────────────────────────────────
    override fun dispatchTouchEvent(ev: MotionEvent): Boolean {
        if (ev.actionMasked == MotionEvent.ACTION_DOWN) {
            passGesture = false
            if (idleOverlay.visibility == View.VISIBLE && hasMain && !morphing) {
                // 화면보호기의 공지 수정 아이콘 · 수정 중인 화면: 대시보드로 넘어가지 않고 화면보호기 페이지가 받는다
                val (rx, ry) = toRoot(ev.x, ev.y)
                if (screensaver.editing || screensaver.hitsEditButton(rx, ry, reveal.parent as View)) {
                    disarmTap()
                    swallowGesture = false
                    passGesture = true
                    return steadyDispatch(ev)
                }
            }
            if (idleOverlay.visibility == View.VISIBLE) {
                swallowGesture = true
                val armed = tapArmedAt != 0L && android.os.SystemClock.uptimeMillis() - tapArmedAt <= TAP_WINDOW_MS
                if (armed) {
                    disarmTap()
                    circleTransition(ev.x, ev.y) { hideIdle() }   // 두 번째 터치: 누른 자리에서 동그라미가 퍼지며 대시보드로
                } else if (!morphing) {
                    touchRipple(ev.x, ev.y)                        // 첫 터치: 물결 + '한 번 더 눌러 주세요'
                    armTap()
                }
                return true
            }
            resetIdle()
        }
        if (passGesture) {
            if (ev.actionMasked == MotionEvent.ACTION_UP || ev.actionMasked == MotionEvent.ACTION_CANCEL) passGesture = false
            return steadyDispatch(ev)
        }
        if (swallowGesture) {
            if (ev.actionMasked == MotionEvent.ACTION_UP || ev.actionMasked == MotionEvent.ACTION_CANCEL) {
                swallowGesture = false
            }
            return true
        }
        return steadyDispatch(ev)
    }

    // ── 손가락 한 번 누름 → 웹 화면 클릭 ──
    // 이 TV 터치판에서는 손가락 터치가 웹 화면에 들어가도(스크롤은 됨) 웹 화면이 그것을 클릭으로 판정하지 못한다
    // (마우스는 정상, 앱 버튼인 사이드바도 정상). → 손가락을 떼면 TapClick 이 그 자리에 클릭을 넣는다.
    // 끌기·스크롤(많이 움직임) · 길게 누름 · 두 손가락은 그대로 둔다
    private var tapDown = false
    private var tapX = 0f
    private var tapY = 0f
    private var tapT = 0L

    private fun steadyDispatch(ev: MotionEvent): Boolean {
        val mouse = ev.isFromSource(android.view.InputDevice.SOURCE_MOUSE) || ev.getToolType(0) == MotionEvent.TOOL_TYPE_MOUSE
        if (!mouse) {
            TouchDiag.add(ev)
            val slop = maxOf(window.decorView.width, window.decorView.height) * 0.012f
            val moved = Math.hypot((ev.x - tapX).toDouble(), (ev.y - tapY).toDouble()) > slop
            when (ev.actionMasked) {
                MotionEvent.ACTION_DOWN -> { tapDown = true; tapX = ev.x; tapY = ev.y; tapT = ev.eventTime }
                MotionEvent.ACTION_POINTER_DOWN, MotionEvent.ACTION_CANCEL -> tapDown = false
                MotionEvent.ACTION_MOVE -> if (tapDown && moved) { tapDown = false; TouchDiag.moved() }
                MotionEvent.ACTION_UP -> if (tapDown) {
                    tapDown = false
                    if (!moved && ev.eventTime - tapT < 500) {
                        val x = ev.x; val y = ev.y
                        handler.post { clickWeb(x, y) }
                    }
                }
            }
        }
        return super.dispatchTouchEvent(ev)
    }

    /** 창 좌표 (x, y) 아래의 웹 화면(화면보호기 · 대시보드)에 클릭 */
    private fun clickWeb(x: Float, y: Float) {
        if (idleOverlay.visibility == View.VISIBLE) TapClick.click(screensaver.page, x, y)
        else TapClick.click(webView, x, y)
    }

    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        val volume = event.keyCode == KeyEvent.KEYCODE_VOLUME_UP || event.keyCode == KeyEvent.KEYCODE_VOLUME_DOWN ||
            event.keyCode == KeyEvent.KEYCODE_VOLUME_MUTE
        if (idleOverlay.visibility == View.VISIBLE && screensaver.editing) {
            // 공지 수정 중: 외부 키보드 입력은 화면보호기 페이지로. 뒤로(리모컨) = 수정 취소
            if (event.keyCode == KeyEvent.KEYCODE_BACK) {
                if (event.action == KeyEvent.ACTION_UP) screensaver.cancelEdit()
                return true
            }
            return super.dispatchKeyEvent(event)
        }
        if (!volume && idleOverlay.visibility == View.VISIBLE) {
            if (event.action == KeyEvent.ACTION_UP) morphTransition { hideIdle() }   // 리모컨: 모핑으로 대시보드에
            return true
        }
        if (event.action == KeyEvent.ACTION_DOWN) resetIdle()
        return super.dispatchKeyEvent(event)
    }

    override fun dispatchGenericMotionEvent(ev: MotionEvent): Boolean {
        resetIdle()
        return super.dispatchGenericMotionEvent(ev)
    }

    private fun resetIdle() {
        handler.removeCallbacks(idleRunnable)
        if (resumed && AppSettings.idleEnabled && idleOverlay.visibility != View.VISIBLE) {
            handler.postDelayed(idleRunnable, AppSettings.idleSeconds * 1000L)
        }
    }

    private fun showIdle() {
        if (!resumed) return
        handler.removeCallbacks(idleRunnable)
        handler.removeCallbacks(disarmTapRunnable)
        tapArmedAt = 0L
        idleOverlay.visibility = View.VISIBLE
        idleOverlay.bringToFront()
        if (hasMain) {                                 // 화면보호기 (공지·실적 그래프·동영상, 멘트는 페이지 맨 아래)
            handler.removeCallbacks(blinkRunnable)
            try { idleVideo.stopPlayback() } catch (_: Exception) {}
            idleVideo.visibility = View.GONE
            idleMessage.visibility = View.GONE
            screensaver.show()
            return
        }
        val msg = AppSettings.idleMessage.trim()
        idleMessage.text = msg
        msgVisible = true
        idleMessage.visibility = if (msg.isEmpty()) View.GONE else View.VISIBLE
        handler.removeCallbacks(blinkRunnable)
        val show = AppSettings.idleMsgShowSec
        if (msg.isNotEmpty() && show > 0) handler.postDelayed(blinkRunnable, show * 1000L)
        idleVideoIndex = 0
        idleVideoErrors = 0
        playIdleVideo()
    }

    private fun playIdleVideo() {
        val vids = idleVideos
        if (vids.isEmpty() || idleOverlay.visibility != View.VISIBLE) {
            idleVideo.visibility = View.GONE
            return
        }
        idleVideo.visibility = View.VISIBLE
        val f = vids[idleVideoIndex % vids.size]
        idleVideo.setOnPreparedListener { mp ->
            mp.isLooping = vids.size == 1
            val vol = if (AppSettings.prefs.getBoolean("idle_video_sound", false)) 1f else 0f
            mp.setVolume(vol, vol)
            idleVideo.start()
        }
        idleVideo.setOnCompletionListener {
            idleVideoIndex++
            playIdleVideo()
        }
        idleVideo.setOnErrorListener { _, _, _ ->
            idleVideoErrors++
            idleVideoIndex++
            if (idleVideoErrors < vids.size * 2) handler.postDelayed({ playIdleVideo() }, 1000)
            else idleVideo.visibility = View.GONE
            true
        }
        idleVideo.setVideoPath(f.path)
    }

    private fun hideIdle() {
        handler.removeCallbacks(disarmTapRunnable)
        tapArmedAt = 0L
        handler.removeCallbacks(blinkRunnable)
        screensaver.hide()
        try { idleVideo.stopPlayback() } catch (_: Exception) {}
        idleVideo.visibility = View.GONE
        idleOverlay.visibility = View.GONE
        resetIdle()
        if (!fullscreen) focusSelectedTile()
    }

    // ── 설정 / 업데이트 ──────────────────────────────────────────────────
    private fun openSettings() {
        val pin = AppSettings.settingsPin
        if (pin.isEmpty()) {
            startActivity(Intent(this, SettingsActivity::class.java))
            return
        }
        val input = EditText(this).apply {
            inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_VARIATION_PASSWORD
        }
        AlertDialog.Builder(this)
            .setTitle(R.string.pin_title)
            .setView(input)
            .setPositiveButton(R.string.ok) { _, _ ->
                if (input.text.toString() == pin) startActivity(Intent(this, SettingsActivity::class.java))
                else Toast.makeText(this, R.string.pin_wrong, Toast.LENGTH_SHORT).show()
            }
            .setNegativeButton(R.string.cancel, null)
            .show()
    }

    private fun checkPendingUploadedApk() {
        val app = applicationContext
        if (io.isShutdown) return
        io.execute {
            val p = UpdateManager.pendingUploaded(app)
            handler.post {
                if (p != null && resumed && !isFinishing) {
                    UpdateUi.promptInstall(this, p.first, p.second.versionName, "관리 웹에서 업로드된 새 버전입니다.")
                }
            }
        }
    }

    /** 상단 제목(설정) + 로고(자료 폴더 루트의 logo.png 가 있으면 그것, 없으면 기본 로고) */
    private fun applyHeader() {
        headerTitle.text = AppSettings.headerTitle
        val logo = File(ContentStore.root(this), LOGO_FILE)
        val bmp = if (logo.isFile) try { BitmapFactory.decodeFile(logo.path) } catch (e: Throwable) { null } else null
        if (bmp != null) headerLogo.setImageBitmap(bmp) else headerLogo.setImageResource(R.drawable.logo_daesang_mark)
    }

    private fun applyKeepScreenOn() {
        if (AppSettings.keepScreenOn) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    private fun hideSystemBars() {
        WindowCompat.setDecorFitsSystemWindows(window, false)
        val c = WindowInsetsControllerCompat(window, window.decorView)
        c.hide(WindowInsetsCompat.Type.systemBars())
        c.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        window.decorView.setBackgroundColor(Color.BLACK)
    }

    companion object {
        /** 화면의 16:9 영역이 1920dp 보다 작으면(밀도가 높은 기기) 밀도를 낮춰 1920dp 로 — 4K 기준 비율 그대로, 변형 없이 */
        fun fitDensity(base: android.content.Context): android.content.Context {
            val dm = base.resources.displayMetrics
            val w = maxOf(dm.widthPixels, dm.heightPixels)
            val h = minOf(dm.widthPixels, dm.heightPixels)
            if (w <= 0 || h <= 0) return base
            val tw = if (w * 9 > h * 16) h * 16 / 9 else w
            val want = tw * android.util.DisplayMetrics.DENSITY_DEFAULT / 1920
            val conf = android.content.res.Configuration(base.resources.configuration)
            if (want <= 0 || want >= conf.densityDpi) return base
            conf.densityDpi = want
            return base.createConfigurationContext(conf)
        }

        const val EXTRA_PREVIEW_IDLE = "preview_idle"
        private const val LOGO_FILE = "logo.png"
        private const val SCAN_MS = 15_000L
        private const val TAP_WINDOW_MS = 5_000L
        private const val TAP_AGAIN = "대시보드로 들어가시려면 한 번 더 눌러 주세요"
    }
}
