plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// ── 버전 규칙 ─────────────────────────────────────────────────────────────
// -PappVersion=1.2.3 (CI에서 태그 v1.2.3 으로부터 전달)
// versionCode = major*1_000_000 + minor*1_000 + patch  → 태그가 올라가면 항상 증가
val appVersion: String = (findProperty("appVersion") as String?)?.removePrefix("v") ?: "0.0.1"
val versionParts = Regex("""^(\d+)\.(\d+)\.(\d+)""").find(appVersion)?.groupValues
    ?: error("appVersion 은 1.2.3 형식이어야 합니다: $appVersion")
val computedVersionCode = versionParts[1].toInt() * 1_000_000 + versionParts[2].toInt() * 1_000 + versionParts[3].toInt()

// 업데이트 확인 기본 주소 (GitHub Releases 의 최신 update.json)
val githubRepo: String = System.getenv("GITHUB_REPOSITORY") ?: "seyoungjo1/tv-dashboard"
val defaultUpdateUrl = "https://github.com/$githubRepo/releases/latest/download/update.json"

// ── 서명 (GitHub Secrets → 환경변수) ──────────────────────────────────────
val keystoreFile = System.getenv("SIGNING_KEYSTORE_FILE")
val hasSigning = !keystoreFile.isNullOrBlank() && file(keystoreFile).exists()

android {
    namespace = "com.seyoungjo.tvdashboard"
    compileSdk = 34

    defaultConfig {
        // 패키지명은 업데이트를 위해 절대 변경하지 않습니다.
        applicationId = "com.seyoungjo.tvdashboard"
        minSdk = 26
        targetSdk = 34
        versionCode = computedVersionCode
        versionName = appVersion
        buildConfigField("String", "DEFAULT_UPDATE_URL", "\"$defaultUpdateUrl\"")
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    signingConfigs {
        if (hasSigning) {
            create("release") {
                storeFile = file(keystoreFile!!)
                storePassword = System.getenv("SIGNING_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("SIGNING_KEY_ALIAS")
                keyPassword = System.getenv("SIGNING_KEY_PASSWORD")
                enableV1Signing = true
                enableV2Signing = true
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            if (hasSigning) signingConfig = signingConfigs.getByName("release")
        }
        debug {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
        }
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }

    lint {
        abortOnError = false
        checkReleaseBuilds = false
    }

    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.recyclerview:recyclerview:1.3.2")
    implementation("androidx.webkit:webkit:1.11.0")
    implementation("androidx.preference:preference-ktx:1.2.1")
    implementation("org.nanohttpd:nanohttpd:2.3.1")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}
