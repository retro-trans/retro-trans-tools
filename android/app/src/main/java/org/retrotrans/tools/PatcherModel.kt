package org.retrotrans.tools

import android.app.Application
import android.app.ActivityManager
import android.content.Intent
import android.net.Uri
import androidx.core.content.ContextCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import androidx.compose.runtime.*
import kotlinx.coroutines.*
import kotlinx.serialization.json.*
import org.retrotrans.core.*
import java.io.File

class PatcherModel(app:Application):AndroidViewModel(app) {
    val app get()=getApplication<Application>()
    val storage=Storage(app)
    private val prefs=app.getSharedPreferences("settings",0)
    var catalog by mutableStateOf(Network(app).load()); private set
    var tab by mutableIntStateOf(0)
    var selections by mutableStateOf(emptyList<Selection>())
    var selected by mutableIntStateOf(0)
    var source by mutableStateOf<Doc?>(null)
    var patch by mutableStateOf<Doc?>(null)
    var target by mutableStateOf("Latest")
    var tree by mutableStateOf(prefs.getString("output",null)?.let(Uri::parse))
    var outputName by mutableStateOf("")
    var status by mutableStateOf("Choose a game file or Games folder.")
    var fraction by mutableStateOf<Double?>(null)
    var busy by mutableStateOf(false)
    var serviceBusy by mutableStateOf(false)
    var interrupted by mutableStateOf(false)
    var catalogStatus by mutableStateOf("${catalog.summary} (bundled/cache)")
    var dialog by mutableStateOf<String?>(null)
    var importPending by mutableStateOf<Pair<Doc,String>?>(null)
    var updateCandidate by mutableStateOf<JsonObject?>(null)
    var installFile by mutableStateOf<File?>(null)
    private var lastJobTime=0L
    private var control:Control?=null
    override fun onCleared() { control?.cancelled?.set(true); super.onCleared() }
    val jobDir get()=File(app.filesDir,"job")
    val choice get()=selections.getOrNull(selected)
    fun route():Route? = choice?.let { runCatching { catalog.plan(it,target) }.getOrNull() }
    fun routeError():String = choice?.let { runCatching { catalog.plan(it,target).summary }.getOrElse { it.message ?: "No compatible route." } } ?: "No recognized file selected"
    init {
        viewModelScope.launch {
            while(isActive) {
                val saved=withContext(Dispatchers.IO) { readJson(File(jobDir,"state.json")) }
                if(saved!=null && !busy) {
                    @Suppress("DEPRECATION") val active=app.getSystemService(ActivityManager::class.java).getRunningServices(30)
                        .any { it.service.className==PatchService::class.java.name }
                    serviceBusy=active
                    val state=saved.string("status")
                    interrupted=(state=="interrupted" || (state in listOf("running","ready") && !active))
                    val time=saved.getValue("time").jsonPrimitive.long
                    if(time!=lastJobTime) {
                        status=if(state=="running" && !active) "Previous job was interrupted. Resume or discard it." else saved.string("message")
                        fraction=(saved["fraction"] as? JsonPrimitive)?.doubleOrNull
                        lastJobTime=time
                    }
                }
                delay(700)
            }
        }
        viewModelScope.launch {
            try {
                val next=withContext(Dispatchers.IO) { Network(app).refresh(Control()) }
                if(!busy && !serviceBusy && selections.isEmpty()) catalog=next
                catalogStatus="${next.summary} · catalog refreshed"
            } catch(e:Exception) { catalogStatus="${catalog.summary} · using saved catalog" }
            val remembered=prefs.getString("games",null)
            if(remembered!=null && !busy && !serviceBusy && !interrupted && source==null && selections.isEmpty()) scan(Uri.parse(remembered))
            if(!BuildConfig.DEBUG) runCatching {
                updateCandidate=withContext(Dispatchers.IO) { AndroidUpdates(app).check(Control()) }
            }
        }
    }
    private fun work(block:suspend (Control)->Unit) {
        if(busy || serviceBusy)return
        busy=true
        val c=Control { message,value->viewModelScope.launch { status=message; fraction=value } }; control=c
        viewModelScope.launch {
            try { block(c) } catch(e:Exception) { status=e.message ?: "Operation failed." }
            finally { busy=false; fraction=null; control=null }
        }
    }
    fun cancel() {
        control?.cancelled?.set(true)
        if(serviceBusy) app.startService(Intent(app,PatchService::class.java).setAction("cancel"))
    }
    fun browse(uri:Uri,kind:String) {
        if(busy || serviceBusy)return
        work { c->
            val doc=withContext(Dispatchers.IO) { storage.describe(uri) }
            if(doc.name.substringAfterLast('.').lowercase() in listOf("chd","dcp") && !(tab==2 && kind=="patch" && doc.name.endsWith(".dcp",true))) {
                status="CHD conversion is unavailable. For DCP use the DCP tab, or Automatic → Folder for the original CUE/BIN set."; return@work
            }
            val seekable=withContext(Dispatchers.IO) { storage.isSeekable(uri) }
            if(!seekable || (uri.scheme!="file" && uri.authority !in listOf("com.android.externalstorage.documents","com.android.providers.downloads.documents"))) {
                importPending=doc to kind; return@work
            }
            accept(doc,kind,c)
        }
    }
    fun import() {
        val pending=importPending ?: return; importPending=null
        work { c->val doc=withContext(Dispatchers.IO) { storage.importFile(pending.first,c) }; accept(doc,pending.second,c) }
    }
    private suspend fun accept(doc:Doc,kind:String,c:Control) {
        if(kind=="patch") { patch=doc; status="Local patch selected."; return }
        source=doc
        if(tab==1) {
            outputName=doc.name.substringBeforeLast('.')+"-patched."+doc.name.substringAfterLast('.',"bin")
            status="Manual xdelta uses patch checksums; there is no catalog output guarantee."; return
        }
        val inputs=withContext(Dispatchers.IO) { storage.identify(listOf(doc),catalog,c,true) }
        selections=catalog.selections(inputs); selected=0; target="Latest"
        if(selections.isEmpty()) status=if(doc.name.substringAfterLast('.').lowercase() in listOf("cue","gdi"))
            "Choose Folder and select the folder containing this descriptor and all tracks."
            else "No matching catalog binary. You can use a local patch in Apply xdelta."
        else { status="File recognized."; suggestName() }
    }
    fun scan(uri:Uri?=prefs.getString("games",null)?.let(Uri::parse)) {
        if(uri==null) { status="Choose a Games folder first."; return }
        work { c->
            require(uri.authority=="com.android.externalstorage.documents") {
                "Choose a local internal, SD-card or USB folder. Use Browse file to import from another provider."
            }
            val docs=withContext(Dispatchers.IO) { storage.list(uri) }
            val inputs=withContext(Dispatchers.IO) { storage.identify(docs,catalog,c) }
            val dcp=withContext(Dispatchers.IO) { AndroidDcp.selections(storage,docs,inputs,catalog,c,tab==2) }
            prefs.edit().putString("games",uri.toString()).apply()
            selections=if(tab==2)dcp else dcp+catalog.selections(inputs); selected=0; target="Latest"; source=null
            status=when(selections.size) { 0->"No matching files in this folder."; 1->"One match selected."; else->"Choose from ${selections.size} recognized files/disc sets." }
            suggestName()
        }
    }
    fun refresh()=work { c->
        val next=withContext(Dispatchers.IO) { Network(app).refresh(c) }
        catalog=next; selections=emptyList(); selected=0
        catalogStatus="${next.summary} · catalog refreshed"; status="Catalog refreshed. Scan or select your file again."
    }
    fun setOutput(uri:Uri) { tree=uri; prefs.edit().putString("output",uri.toString()).apply() }
    fun suggestName() {
        if(tab==2 && choice?.dcp!=null) { outputName="dreamcast-dcp";return }
        val r=route() ?: return
        outputName=if(r.grouped) "translated-${r.targetVersion}" else {
            val p=r.parts.single(); p.input.name.substringBeforeLast('.').take(140)+"-${r.targetVersion}."+p.target.format
        }
    }
    fun start() {
        if(busy || serviceBusy)return
        val output=tree ?: run { status="Select an output folder."; return }
        if(interrupted) { status="Resume or discard the previous job first."; return }
        work { c->
            val name=safeName(outputName)
            withContext(Dispatchers.IO) { storage.prepareOutput(output,name) }
            val selectedDcp=choice?.dcp
            val request=if((tab==0 || tab==2) && selectedDcp!=null) {
                val profile=if(tab==0)catalog.plan(choice!!,target).dcp!! else null
                val local=if(tab==2)patch ?: error("Choose a local DCP patch.") else null
                withContext(Dispatchers.IO) { AndroidDcp.request(storage,selectedDcp,profile,local,output.toString(),name,c) }
            } else if(tab==0) {
                val r=catalog.plan(choice ?: error("Select a recognized game."),target)
                require(r.edges.isNotEmpty()) { "This file is already at the selected version." }
                automaticRequest(r,output.toString(),name)
            } else {
                val s=source ?: error("Select an original binary."); val p=patch ?: error("Select an xdelta patch.")
                val identities=withContext(Dispatchers.IO) { listOf(s,p).map { storage.hash(it,setOf("sha256"),c) } }
                fun identity(i:Int)=obj("size" to JsonPrimitive(identities[i].size),"sha256" to str(identities[i].hashes.getValue("sha256")))
                obj("mode" to str("manual"),"output" to str(output.toString()),"name" to str(name),"grouped" to JsonPrimitive(false),
                    "source" to str(s.uri.toString()),"patch" to str(p.uri.toString()),"source_identity" to identity(0),"patch_identity" to identity(1))
            }
            withContext(Dispatchers.IO) {
                require(Storage(app).cleanupExports(jobDir)==null) { "Clean up the previous unfinished export first." }
                jobDir.deleteRecursively(); jobDir.mkdirs()
                atomicWrite(File(jobDir,"catalog.json"),catalog.raw)
                atomicWrite(File(jobDir,"request.json"),request.toString())
                atomicWrite(File(jobDir,"state.json"),obj("status" to str("ready"),
                    "message" to str("Job prepared. Resume to start patching."),"time" to JsonPrimitive(System.currentTimeMillis())).toString())
            }
            launchWorker()
        }
    }
    private fun launchWorker() {
        serviceBusy=true; interrupted=false; status="Starting patch…"
        try { ContextCompat.startForegroundService(app,Intent(app,PatchService::class.java)) }
        catch(e:Exception) {
            serviceBusy=false; interrupted=true
            status="Android could not start background patching. Keep the app open and choose Resume. ${e.message ?: ""}"
        }
    }
    fun resume() { if(busy || serviceBusy)return; launchWorker() }
    fun discard()=work { _->
        withContext(Dispatchers.IO) { storage.cleanupExports(jobDir)?.let { error(it) }; jobDir.deleteRecursively() }
        interrupted=false; status="Unfinished job discarded. Originals are unchanged."
    }
    fun clearCache()=work { _->withContext(Dispatchers.IO) { File(app.filesDir,"patch-cache").deleteRecursively(); File(app.filesDir,"imports").deleteRecursively() }
        selections=emptyList(); source=null; patch=null; status="Downloaded patches and imported copies cleared." }
    fun checkUpdates()=work { c->
        if(BuildConfig.DEBUG) dialog="This local test APK does not install production updates. Install an explicitly published Android release when one is available."
        else {
            updateCandidate=withContext(Dispatchers.IO) { AndroidUpdates(app).check(c) }
            if(updateCandidate==null) dialog="This Android version is current."
        }
    }
    fun downloadUpdate()=work { c->
        val candidate=updateCandidate ?: return@work; updateCandidate=null
        installFile=withContext(Dispatchers.IO) { AndroidUpdates(app).stage(candidate,c) }
    }
}
