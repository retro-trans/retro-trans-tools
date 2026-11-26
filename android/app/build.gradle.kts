plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.compose)
}
android {
    namespace = "org.retrotrans.tools"
    compileSdk = 36
    buildToolsVersion = "36.0.0"
    defaultConfig {
        applicationId = "org.retrotrans.tools"
        minSdk = 26
        targetSdk = 36
        versionCode = 524
        versionName = "0.5.24-preview"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
    }
    System.getenv("RETRO_TRANS_PREVIEW_KEYSTORE")?.let { previewKey ->
        signingConfigs.getByName("debug") {
            storeFile = file(previewKey).also { require(it.isFile) { "Preview signing file is missing" } }
            storePassword = "android"
            keyAlias = "androiddebugkey"
            keyPassword = "android"
        }
    }
    buildTypes { debug { applicationIdSuffix = ".debug" }; release { isMinifyEnabled = false } }
    buildFeatures { compose = true; buildConfig = true }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
    sourceSets["main"].assets.srcDir(layout.buildDirectory.dir("generated/assets"))
    sourceSets["androidTest"].java.srcDir("../test-support")
    packaging { resources.excludes += "/META-INF/{AL2.0,LGPL2.1}" }
}
val bundleCatalog by tasks.registering(Copy::class) {
    from("../../retro_trans/resources/catalog.json", "../../retro_trans/resources/XDELTA-LICENSE.txt")
    from("src/main/notices")
    into(layout.buildDirectory.dir("generated/assets"))
}
tasks.named("preBuild") { dependsOn(bundleCatalog) }
dependencies {
    implementation(project(":patch-core")); implementation(project(":patch-native"))
    implementation(platform(libs.compose.bom))
    implementation("androidx.activity:activity-compose:1.11.0")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.4")
    implementation("androidx.core:core-ktx:1.17.0")
    implementation("androidx.documentfile:documentfile:1.1.0")
    implementation(libs.coroutines); implementation(libs.json); implementation(libs.okhttp)
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
    androidTestImplementation("androidx.test:runner:1.7.0")
    androidTestImplementation("androidx.test:core:1.7.0")
    androidTestImplementation("androidx.test.uiautomator:uiautomator:2.3.0")
    androidTestImplementation(libs.json)
    testImplementation(libs.junit)
}
