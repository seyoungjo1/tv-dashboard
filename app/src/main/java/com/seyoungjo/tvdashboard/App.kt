package com.seyoungjo.tvdashboard

import android.app.Application
import com.seyoungjo.tvdashboard.data.AppSettings
import com.seyoungjo.tvdashboard.server.Auth
import com.seyoungjo.tvdashboard.update.UpdateManager

class App : Application() {
    override fun onCreate() {
        super.onCreate()
        AppSettings.init(this)
        Auth.init(this)
        UpdateManager.cleanupOldApks(this)
    }
}
