package com.seyoungjo.tvdashboard.data

import android.content.Context
import android.net.Uri
import android.os.Build
import android.os.Environment
import java.io.File

/**
 * 자료 폴더 위치.
 *  - app    : /sdcard/Android/data/<패키지>/files/자료  (권한 불필요, 앱 삭제 시 함께 삭제, 업데이트 시 유지)
 *  - shared : /sdcard/자료  ('모든 파일 접근' 권한 필요, 앱을 삭제해도 남음)
 */
object ContentStore {
    const val FOLDER_NAME = "자료"
    const val TMP_DIR = ".tmp"
    const val WEB_HOST = "appassets.androidplatform.net"
    const val WEB_PREFIX = "/data/"

    fun sharedAllowed(): Boolean =
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.R && Environment.isExternalStorageManager()

    /** 설정은 shared 인데 권한이 없으면 app 폴더를 사용 */
    fun effectiveMode(): String =
        if (AppSettings.storageMode == "shared" && sharedAllowed()) "shared" else "app"

    fun root(context: Context): File {
        val dir = if (effectiveMode() == "shared") {
            File(Environment.getExternalStorageDirectory(), FOLDER_NAME)
        } else {
            File(context.getExternalFilesDir(null) ?: context.filesDir, FOLDER_NAME)
        }
        if (!dir.exists()) dir.mkdirs()
        return dir
    }

    fun guard(context: Context) = PathGuard(root(context))

    fun tmpDir(context: Context): File = File(root(context), TMP_DIR).apply { mkdirs() }

    /** WebView 에서 여는 주소 (같은 출처라서 fetch('data.json') 이 동작) */
    fun webUrl(folder: String, file: String): String {
        val b = Uri.Builder().scheme("https").authority(WEB_HOST).appendPath("data")
        folder.split('/').filter { it.isNotEmpty() }.forEach { b.appendPath(it) }
        b.appendPath(file)
        return b.build().toString()
    }
}
