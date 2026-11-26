package org.retrotrans.tools

import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import kotlinx.serialization.json.*
import org.retrotrans.core.Asset
import java.io.File
import java.security.MessageDigest

class AndroidUpdates(private val context:Context) {
    fun check(control:Control):JsonObject? {
        val row=Json.parseToJsonElement(Network(context).bytes(Network.UPDATE,65536,control).decodeToString()).jsonObject
        validate(row)
        return row.takeIf { it.getValue("version_code").jsonPrimitive.long>BuildConfig.VERSION_CODE }
    }
    private fun validate(row:JsonObject) {
        require(row["schema_version"]?.jsonPrimitive?.int==1 && row.string("platform")=="android-arm64") { "Unsupported Android update metadata." }
        require(row.string("package_id")==context.packageName && row.getValue("min_sdk").jsonPrimitive.int<=Build.VERSION.SDK_INT) { "This update is not compatible with this installation." }
        require(Build.SUPPORTED_ABIS.contains("arm64-v8a")) { "This update is for ARM64 phones." }
        require(Regex("[0-9]+(?:\\.[0-9]+){1,3}").matches(row.string("version_name"))) { "Updates must be stable versions." }
        require(row.string("tag")=="android-v"+row.string("version_name")) { "Update tag mismatch." }
        require(row.string("asset")=="Retro-Trans-Android.apk" && Regex("[a-f0-9]{64}").matches(row.string("sha256"))) { "Invalid update identity." }
        require(row.getValue("bytes").jsonPrimitive.long in 1..(256L*1024*1024)) { "Invalid APK size." }
        require(row.getValue("version_code").jsonPrimitive.long>0)
        require(row.string("url")=="https://github.com/retro-trans/retro-trans-tools/releases/download/${row.string("tag")}/${row.string("asset")}") { "Unexpected update URL." }
    }
    @Suppress("DEPRECATION")
    fun stage(row:JsonObject,control:Control):File {
        validate(row)
        require(row.getValue("version_code").jsonPrimitive.long>BuildConfig.VERSION_CODE) { "Refusing an app downgrade." }
        val release=Json.parseToJsonElement(Network(context).bytes(
            "https://api.github.com/repos/retro-trans/retro-trans-tools/releases/tags/${row.string("tag")}",
            1024L*1024,control).decodeToString()).jsonObject
        require(release.string("tag_name")==row.string("tag") &&
            release.getValue("draft").jsonPrimitive.boolean==false &&
            release.getValue("prerelease").jsonPrimitive.boolean==false) { "Update release is not published and stable." }
        val published=release.getValue("assets").jsonArray.map { it.jsonObject }.singleOrNull {
            it.string("name")==row.string("asset")
        } ?: error("Published APK is missing or ambiguous.")
        require(published.string("browser_download_url")==row.string("url") &&
            published.getValue("size").jsonPrimitive.long==row.getValue("bytes").jsonPrimitive.long) { "Update does not match the published asset." }
        published["digest"]?.takeIf { it!=JsonNull }?.let {
            require(it.jsonPrimitive.content=="sha256:"+row.string("sha256")) { "Published APK hash mismatch." }
        }
        val downloaded=Network(context).download(Asset(row.string("asset"),row.string("url"),row.getValue("bytes").jsonPrimitive.long,row.string("sha256")),control)
        val pm=context.packageManager
        val flags=if(Build.VERSION.SDK_INT>=28) PackageManager.GET_SIGNING_CERTIFICATES else PackageManager.GET_SIGNATURES
        val archive=pm.getPackageArchiveInfo(downloaded.path,flags) ?: error("Downloaded APK cannot be read.")
        val current=pm.getPackageInfo(context.packageName,flags)
        require(archive.packageName==context.packageName && archive.versionName==row.string("version_name")) { "Downloaded APK identity mismatch." }
        val code=if(Build.VERSION.SDK_INT>=28)archive.longVersionCode else archive.versionCode.toLong()
        require(code==row.getValue("version_code").jsonPrimitive.long && code>BuildConfig.VERSION_CODE) { "APK version mismatch." }
        fun signatures(p:android.content.pm.PackageInfo)=if(Build.VERSION.SDK_INT>=28) p.signingInfo!!.apkContentsSigners.toList() else p.signatures!!.toList()
        fun digests(p:android.content.pm.PackageInfo)=signatures(p).map { hex(MessageDigest.getInstance("SHA-256").digest(it.toByteArray())) }.toSet()
        require(digests(current).isNotEmpty() && digests(archive)==digests(current)) { "Update uses a different signing key." }
        val destination=File(context.filesDir,"updates/Retro-Trans-Android.apk").apply { parentFile!!.mkdirs() }
        downloaded.copyTo(destination,true)
        require(fileHash(destination,control)==row.string("sha256")) { "Staged APK verification failed." }
        return destination
    }
}
