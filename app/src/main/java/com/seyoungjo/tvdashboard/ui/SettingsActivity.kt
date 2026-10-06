package com.seyoungjo.tvdashboard.ui

import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.preference.EditTextPreference
import androidx.preference.ListPreference
import androidx.preference.Preference
import androidx.preference.PreferenceFragmentCompat
import com.seyoungjo.tvdashboard.R
import com.seyoungjo.tvdashboard.data.AppEvent
import com.seyoungjo.tvdashboard.data.AppSettings
import com.seyoungjo.tvdashboard.data.ChangeBus
import com.seyoungjo.tvdashboard.data.ContentStore
import com.seyoungjo.tvdashboard.server.Auth
import com.seyoungjo.tvdashboard.server.NetInfo
import com.seyoungjo.tvdashboard.server.ServerService
import com.seyoungjo.tvdashboard.relay.RelaySettings
import com.seyoungjo.tvdashboard.relay.RelayWorker
import com.seyoungjo.tvdashboard.update.UpdateManager
import org.json.JSONObject

class SettingsActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (savedInstanceState == null) {
            supportFragmentManager.beginTransaction().replace(android.R.id.content, SettingsFragment()).commit()
        }
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
    }

    override fun onSupportNavigateUp(): Boolean {
        finish(); return true
    }
}

class SettingsFragment : PreferenceFragmentCompat() {

    /** tvrelay.json 고르기 (저장소 권한 없이 시스템 파일 선택기 사용) */
    private val pickRelay = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri == null) return@registerForActivityResult
        try {
            val text = requireContext().contentResolver.openInputStream(uri)!!.use { it.readBytes().toString(Charsets.UTF_8) }
            RelaySettings.apply(JSONObject(text.trim().removePrefix("\uFEFF")))
            RelayWorker.kick()
            toast("중계 설정을 불러왔습니다 (${RelaySettings.repo} · ${RelaySettings.tv}). 잠시 후 '중계 상태'를 확인하세요.")
        } catch (e: Exception) {
            toast("불러오기 실패: ${e.message}")
        }
        refresh()
    }

    override fun onCreatePreferences(savedInstanceState: Bundle?, rootKey: String?) {
        setPreferencesFromResource(R.xml.preferences, rootKey)

        numeric("port"); numeric("idle_seconds"); numeric("idle_msg_show_sec"); numeric("idle_msg_hide_sec")
        findPreference<EditTextPreference>("settings_pin")?.setOnBindEditTextListener {
            it.inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_VARIATION_PASSWORD
        }
        findPreference<EditTextPreference>("update_url")?.setOnBindEditTextListener {
            it.inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
        }

        findPreference<Preference>("port")?.setOnPreferenceChangeListener { _, v ->
            val p = v.toString().toIntOrNull()
            if (p == null || p !in 1024..65535) {
                toast("포트는 1024~65535 사이 숫자여야 합니다."); false
            } else {
                view?.post { ServerService.restart(requireContext()); view?.postDelayed({ refresh() }, 800) }
                true
            }
        }
        listOf("header_title", "idle_enabled", "idle_seconds", "idle_message", "idle_msg_show_sec", "idle_msg_hide_sec",
            "keep_screen_on", "auto_refresh").forEach { key ->
            findPreference<Preference>(key)?.setOnPreferenceChangeListener { _, _ ->
                view?.post { ChangeBus.post(AppEvent.SettingsChanged) }; true
            }
        }

        click("admin_password") {
            AlertDialog.Builder(requireContext())
                .setTitle("관리자 비밀번호 초기화")
                .setMessage("새 임의 비밀번호를 만들고 로그인 중인 관리자를 모두 로그아웃합니다. 계속할까요?")
                .setPositiveButton("초기화") { _, _ -> Auth.resetPassword(); refresh() }
                .setNegativeButton("취소", null).show()
        }
        click("api_token") {
            AlertDialog.Builder(requireContext())
                .setTitle("API 토큰")
                .setMessage("${Auth.apiToken}\n\n자동 업로드 프로그램에서\nAuthorization: Bearer <토큰>\n헤더로 사용합니다.\n관리 웹 > 설정 에서도 확인할 수 있습니다.")
                .setPositiveButton("확인", null)
                .setNeutralButton("새로 발급") { _, _ -> Auth.regenerateApiToken(); toast("새 토큰을 발급했습니다. 기존 토큰은 더 이상 사용할 수 없습니다.") }
                .show()
        }
        click("idle_preview") {
            startActivity(
                Intent(requireContext(), MainActivity::class.java)
                    .putExtra(MainActivity.EXTRA_PREVIEW_IDLE, true)
                    .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
            )
            requireActivity().finish()
        }
        click("overlay_permission") {
            open(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:${requireContext().packageName}")))
        }
        findPreference<ListPreference>("storage_mode")?.setOnPreferenceChangeListener { _, v ->
            if (v == "shared" && !ContentStore.sharedAllowed()) {
                AlertDialog.Builder(requireContext())
                    .setTitle("모든 파일 접근 권한 필요")
                    .setMessage("공용 폴더(/sdcard/자료)를 사용하려면 '모든 파일에 대한 접근' 권한을 허용해야 합니다.\n허용 전까지는 앱 전용 폴더를 계속 사용합니다.\n\n※ 기존 자료는 자동으로 옮겨지지 않습니다. 관리 웹에서 다시 업로드하세요.")
                    .setPositiveButton("권한 설정 열기") { _, _ -> openAllFilesAccess() }
                    .setNegativeButton("닫기", null).show()
            }
            view?.post { ChangeBus.post(AppEvent.Reload); refresh() }
            true
        }
        click("storage_info") { showUninstallNotice() }
        click("relay_import") { pickRelay.launch(arrayOf("application/json", "text/plain", "application/octet-stream", "*/*")) }
        click("relay_info") { refresh() }
        numeric("relay_interval")
        findPreference<Preference>("relay_enabled")?.setOnPreferenceChangeListener { _, _ ->
            view?.post { RelayWorker.kick(); refresh() }; true
        }
        findPreference<Preference>("relay_interval")?.setOnPreferenceChangeListener { _, _ ->
            view?.post { RelayWorker.kick() }; true
        }
        click("check_update") { UpdateUi.checkForUpdate(requireActivity()) }
        click("install_unknown") { UpdateUi.openUnknownSources(requireActivity()) }
        click("android_settings") { open(Intent(Settings.ACTION_SETTINGS)) }
        click("uninstall_notice") { showUninstallNotice() }
    }

    override fun onResume() {
        super.onResume()
        refresh()
    }

    private fun refresh() {
        val ctx = context ?: return
        val port = ServerService.runningPort
        val addrs = NetInfo.addresses()
        findPreference<Preference>("server_info")?.summary = when {
            port == 0 -> ServerService.lastError ?: "서버가 실행되고 있지 않습니다."
            addrs.isEmpty() -> "네트워크 연결 없음 (포트 $port)"
            else -> addrs.joinToString("\n") { "http://${it.ip}:$port" + if (it.tailscale) "  (Tailscale)" else "" }
        }
        val init = Auth.initialPassword
        findPreference<Preference>("admin_password")?.summary =
            if (init != null) "초기 비밀번호: $init\n(관리 웹에서 변경하면 더 이상 여기에 표시되지 않습니다. 누르면 초기화)"
            else "변경됨 (분실 시 눌러서 초기화)"
        findPreference<Preference>("overlay_permission")?.summary =
            if (Settings.canDrawOverlays(ctx)) "허용됨 — 재부팅 후 화면이 자동으로 열립니다."
            else "허용 안 됨 — 재부팅 후 서버만 실행되고 화면은 자동으로 열리지 않습니다. 눌러서 허용"
        val mode = ContentStore.effectiveMode()
        val pending = AppSettings.storageMode == "shared" && mode != "shared"
        findPreference<Preference>("storage_info")?.summary = ContentStore.root(ctx).path +
            (if (pending) "\n(공용 폴더 권한이 없어 앱 전용 폴더 사용 중)" else "") +
            (if (mode == "app") "\n⚠ 앱을 삭제하면 이 폴더의 자료도 삭제됩니다." else "\n앱을 삭제해도 자료는 남습니다.")
        findPreference<Preference>("relay_info")?.summary =
            "${RelayWorker.status}\n레포: ${RelaySettings.repo} · TV 이름: ${RelaySettings.tv}" +
                (if (RelayWorker.lastSync > 0) "\n마지막 확인: " + java.text.DateFormat.getTimeInstance().format(java.util.Date(RelayWorker.lastSync)) else "")
        findPreference<Preference>("check_update")?.summary =
            "현재 버전 ${UpdateManager.currentVersionName(ctx)} (${UpdateManager.currentVersionCode(ctx)})"
        findPreference<Preference>("install_unknown")?.summary =
            if (UpdateManager.canInstall(ctx)) "허용됨" else "허용 안 됨 — 업데이트 설치 전에 허용해야 합니다."
    }

    private fun showUninstallNotice() {
        val mode = ContentStore.effectiveMode()
        val msg = if (mode == "app") {
            "현재 자료 폴더: ${ContentStore.root(requireContext()).path}\n\n" +
                "• 앱 업데이트: 자료와 설정이 그대로 유지됩니다.\n" +
                "• 앱 삭제: 이 폴더(앱 전용 폴더)의 자료와 설정이 모두 삭제됩니다.\n\n" +
                "앱을 삭제해도 자료를 남기려면 '자료 저장 위치'를 공용 폴더로 바꾸세요."
        } else {
            "현재 자료 폴더: ${ContentStore.root(requireContext()).path}\n\n" +
                "• 앱 업데이트: 자료와 설정이 그대로 유지됩니다.\n" +
                "• 앱 삭제: 공용 폴더의 자료는 남습니다. (설정·비밀번호는 삭제됨)\n" +
                "  자료를 지우려면 관리 웹이나 파일 관리자에서 직접 삭제하세요."
        }
        AlertDialog.Builder(requireContext()).setTitle("앱 삭제 시 자료 안내").setMessage(msg)
            .setPositiveButton("확인", null).show()
    }

    private fun openAllFilesAccess() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) {
            toast("Android 11 이상에서만 지원합니다."); return
        }
        try {
            startActivity(Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION, Uri.parse("package:${requireContext().packageName}")))
        } catch (e: ActivityNotFoundException) {
            open(Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION))
        }
    }

    private fun numeric(key: String) {
        findPreference<EditTextPreference>(key)?.setOnBindEditTextListener { it.inputType = InputType.TYPE_CLASS_NUMBER }
    }

    private fun click(key: String, action: () -> Unit) {
        findPreference<Preference>(key)?.setOnPreferenceClickListener { action(); true }
    }

    private fun open(i: Intent) {
        try { startActivity(i) } catch (e: ActivityNotFoundException) {
            toast("이 기기에서는 해당 설정 화면을 열 수 없습니다.")
        }
    }

    private fun toast(s: String) = Toast.makeText(requireContext(), s, Toast.LENGTH_LONG).show()
}
