plugins {
    id("com.android.application")
    kotlin("android")
}

val webViewAdapterSourceDir = providers.gradleProperty("nierWebViewAdapterSourceDir")
    .orElse(providers.environmentVariable("NIER_WEBVIEW_ADAPTER_SOURCE_DIR"))
    .orNull
    ?.trim()
    ?.takeIf(String::isNotEmpty)
val webViewAdapterClass = providers.gradleProperty("nierWebViewAdapterClass")
    .orElse(providers.environmentVariable("NIER_WEBVIEW_ADAPTER_CLASS"))
    .orNull
    ?.trim()
    ?.takeIf(String::isNotEmpty)

if ((webViewAdapterSourceDir == null) != (webViewAdapterClass == null)) {
    throw GradleException(
        "Set both nierWebViewAdapterSourceDir and nierWebViewAdapterClass " +
            "(or both NIER_WEBVIEW_ADAPTER_* environment variables)"
    )
}

if (webViewAdapterSourceDir != null && !file(webViewAdapterSourceDir).isDirectory) {
    throw GradleException("WebView adapter source directory does not exist: $webViewAdapterSourceDir")
}

val escapedWebViewAdapterClass = (webViewAdapterClass ?: "")
    .replace("\\", "\\\\")
    .replace("\"", "\\\"")

android {
    namespace = "icu.rina.nier.backend"
    compileSdk = 35
    buildToolsVersion = "35.0.0"
    ndkVersion = "27.2.12479018"

    defaultConfig {
        applicationId = "icu.rina.nier.backend"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
        buildConfigField("String", "NIER_WEBVIEW_ADAPTER_CLASS", "\"$escapedWebViewAdapterClass\"")
    }

    if (webViewAdapterSourceDir != null) {
        sourceSets.getByName("main").java.srcDir(webViewAdapterSourceDir)
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_1_8
        targetCompatibility = JavaVersion.VERSION_1_8
    }

    kotlinOptions {
        jvmTarget = "1.8"
    }

    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
        }
    }

}

dependencies {
    implementation("org.jetbrains.kotlin:kotlin-stdlib")
    compileOnly("de.robv.android.xposed:api:82")
}
