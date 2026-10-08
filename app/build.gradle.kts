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
    // Google Play 요구 수준(최신 Android 대상)에 맞춘다. 동작 변화는 그 Android 버전 기기에서만 생긴다 (75TR3DQ = Android 14)
    compileSdk = 36

    defaultConfig {
        // 패키지명은 업데이트를 위해 절대 변경하지 않습니다.
        applicationId = "com.seyoungjo.tvdashboard"
        minSdk = 26
        targetSdk = 36
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

    // ── 배포 경로 ─────────────────────────────────────────────────────────
    //  direct : GitHub Releases APK 직접 설치 — 앱 안에서 스스로 업데이트(PackageInstaller), 공용 폴더 선택 가능
    //  play   : Google Play 배포 (AAB) — Play 정책상 제한 권한(REQUEST_INSTALL_PACKAGES · MANAGE_EXTERNAL_STORAGE)을 빼고
    //           업데이트는 Play 스토어가 맡는다. 패키지명·서명이 같아 두 빌드는 서로 덮어쓰기 설치가 된다.
    flavorDimensions += "store"
    productFlavors {
        create("direct") {
            dimension = "store"
            isDefault = true
            buildConfigField("boolean", "SELF_UPDATE", "true")
        }
        create("play") {
            dimension = "store"
            buildConfigField("boolean", "SELF_UPDATE", "false")
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
        xmlReport = true
        htmlReport = true
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

// 내장 화면보호기의 버전 표시: pc/tvrelay/VERSION 을 assets/screensaver/version.txt 로 넣는다 (커밋하지 않는 생성 파일).
// TV 는 PC 가 보낸 _screensaver/version.txt 와 비교해 더 새 쪽을 쓴다
val ssVersionDir = layout.buildDirectory.dir("generated/ssversion")
val genSsVersion = tasks.register("genSsVersion") {
    val src = rootProject.file("pc/tvrelay/VERSION")
    inputs.file(src)
    outputs.dir(ssVersionDir)
    doLast {
        val out = ssVersionDir.get().file("screensaver/version.txt").asFile
        out.parentFile.mkdirs()
        out.writeText(src.readText().trim())
    }
}
android.sourceSets.getByName("main").assets.srcDir(ssVersionDir)
tasks.named("preBuild") { dependsOn(genSsVersion) }
