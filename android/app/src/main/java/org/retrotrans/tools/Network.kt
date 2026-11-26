package org.retrotrans.tools

import android.content.Context
import okhttp3.OkHttpClient
import okhttp3.Request
import org.retrotrans.core.*
import java.io.File
import java.util.concurrent.TimeUnit

class Network(private val context:Context) {
    companion object {
        const val CATALOG="https://raw.githubusercontent.com/retro-trans/retro-trans-tools/main/retro_trans/resources/catalog.json"
        const val UPDATE="https://raw.githubusercontent.com/retro-trans/retro-trans-tools/main/updates/android/stable.json"
    }
    private val client=OkHttpClient.Builder().connectTimeout(20,TimeUnit.SECONDS).readTimeout(5,TimeUnit.SECONDS)
        .addNetworkInterceptor { chain->
            val url=chain.request().url
            require(url.isHttps && url.host in setOf("raw.githubusercontent.com","github.com","api.github.com","release-assets.githubusercontent.com","objects.githubusercontent.com")) { "Unexpected download host." }
            chain.proceed(chain.request())
        }.build()
    fun bytes(url:String,limit:Long,control:Control):ByteArray {
        require(limit in 0..(4L*1024*1024))
        client.newCall(Request.Builder().url(url).header("User-Agent","Retro-Trans-Android/${BuildConfig.VERSION_NAME}").build()).execute().use { r->
            require(r.isSuccessful) { "Download unavailable (HTTP ${r.code}). Cached data remains usable." }
            val out=java.io.ByteArrayOutputStream()
            r.body!!.byteStream().use { copy(it,out,control,limit) }; return out.toByteArray()
        }
    }
    fun load():Catalog {
        val bundled=Catalog(context.assets.open("catalog.json").bufferedReader().use { it.readText() })
        val file=File(context.filesDir,"catalog.json")
        return runCatching { Catalog(file.readText()).also { bundled.checkUpdate(it) } }.getOrDefault(bundled)
    }
    fun refresh(control:Control):Catalog {
        val old=load(); val next=Catalog(bytes(CATALOG,4L*1024*1024,control).decodeToString())
        old.checkUpdate(next); control.check(); atomicWrite(File(context.filesDir,"catalog.json"),next.raw); return next
    }
    fun download(asset:Asset,control:Control):File {
        val dir=File(context.filesDir,"patch-cache").apply { mkdirs() }; val dest=File(dir,asset.sha256)
        if(dest.isFile && dest.length()==asset.size && fileHash(dest,control)==asset.sha256) return dest
        space(dir,asset.size+64*1024*1024)
        val part=File(dir,asset.sha256+".partial")
        try {
            client.newCall(Request.Builder().url(asset.url).build()).execute().use { response->
                require(response.isSuccessful) { "Patch download failed (HTTP ${response.code})." }
                response.body!!.byteStream().use { input->part.outputStream().use { copy(input,it,control,asset.size) } }
            }
            require(part.length()==asset.size && fileHash(part,control)==asset.sha256) { "Downloaded patch failed verification." }
            if(dest.exists()) require(dest.delete())
            require(part.renameTo(dest)) { "Cannot save verified patch." }; return dest
        } finally { part.delete() }
    }
}
