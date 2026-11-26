package org.retrotrans.tools

import android.app.*
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.Uri
import android.os.*
import androidx.core.app.NotificationCompat
import kotlinx.serialization.json.*
import org.retrotrans.core.*
import org.retrotrans.engine.NativePatch
import java.io.File
import java.util.concurrent.CancellationException
import java.util.concurrent.Executors

const val PS3_WARNING="Before playing a patched PS3 game, remove its related old installation data so it can be rebuilt. Keep saved games: use Game Data Utility, not Saved Data Utility. Retro Trans never deletes either."
class PatchService:Service() {
    private val executor=Executors.newSingleThreadExecutor()
    private var control:Control?=null
    private var lastProgress=0L
    private var stateTime=0L
    private lateinit var job:File
    override fun onBind(intent:Intent?) = null
    private fun notification(message:String):Notification {
        val cancel=PendingIntent.getService(this,2,Intent(this,PatchService::class.java).setAction("cancel"),PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val open=PendingIntent.getActivity(this,1,Intent(this,MainActivity::class.java),PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        return NotificationCompat.Builder(this,"patch").setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle("Retro Trans ${BuildConfig.VERSION_NAME}").setContentText(message).setContentIntent(open)
            .setOnlyAlertOnce(true).setOngoing(true).addAction(0,"Cancel",cancel).build()
    }
    private fun state(status:String,message:String,fraction:Double?=null) {
        stateTime=maxOf(System.currentTimeMillis(),stateTime+1)
        atomicWrite(File(job,"state.json"),obj("status" to str(status),"message" to str(message),
            "fraction" to (fraction?.let { JsonPrimitive(it.coerceIn(0.0,1.0)) } ?: JsonNull),
            "time" to JsonPrimitive(stateTime)).toString())
        getSystemService(NotificationManager::class.java).notify(1,notification(message))
    }
    override fun onStartCommand(intent:Intent?,flags:Int,startId:Int):Int {
        if(intent?.action=="cancel") { control?.cancelled?.set(true); if(control==null)stopSelf(); return START_NOT_STICKY }
        if(control!=null) return START_NOT_STICKY
        job=File(filesDir,"job").apply { mkdirs() }
        val manager=getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("patch","Patching progress",NotificationManager.IMPORTANCE_LOW))
        if(Build.VERSION.SDK_INT>=29) startForeground(1,notification("Starting patch"),ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        else startForeground(1,notification("Starting patch"))
        val c=Control { message,fraction->
            if(SystemClock.elapsedRealtime()-lastProgress>400) { lastProgress=SystemClock.elapsedRealtime(); state("running",message,fraction) }
        }; control=c
        state("running","Checking source and space")
        executor.submit {
            val wake=getSystemService(PowerManager::class.java).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"RetroTrans:patch")
            wake.acquire(6*60*60*1000L)
            try {
                runJob(c)
                state("complete","Patched copy saved and verified. Original files are unchanged.")
            } catch(e:Exception) {
                val cleanup=runCatching { Storage(this).cleanupExports(job) }.getOrElse { "Unfinished export could not be cleaned up." }
                if(e is CancellationException) {
                    File(job,"work").deleteRecursively()
                    state("cancelled",listOfNotNull(e.message,cleanup).joinToString(" "))
                } else state("interrupted",listOfNotNull(e.message ?: e.javaClass.simpleName,cleanup,"You can resume or discard this job.").joinToString(" "))
            } finally {
                if(wake.isHeld)wake.release()
                control=null; stopForeground(STOP_FOREGROUND_REMOVE); stopSelf()
            }
        }
        return START_NOT_STICKY
    }
    override fun onTimeout(startId:Int,fgsType:Int) {
        control?.cancelled?.set(true)
        state("interrupted","Android stopped this long-running job. Open the app to resume.")
        stopForeground(STOP_FOREGROUND_REMOVE); stopSelf()
        // This service lives in :patch. Never terminate the UI or any other app.
        Process.killProcess(Process.myPid())
    }
    override fun onDestroy() { control?.cancelled?.set(true); executor.shutdown(); super.onDestroy() }

    private fun runJob(c:Control) {
        val storage=Storage(this); val request=readJson(File(job,"request.json")) ?: error("Missing job request.")
        val done=readJson(File(job,"complete.json"))
        if(done!=null) return // A completed export is never applied twice after a restart.
        storage.cleanupExports(job)?.let { error(it) }
        val tree=Uri.parse(request.string("output")); val name=request.string("name")
        storage.prepareOutput(tree,name)
        val work=File(job,"work").apply { mkdirs() }; val final=File(work,"final").apply { mkdirs() }
        val files=mutableListOf<Pair<String,File>>()
        if(request.string("mode")=="dcp") {
            files+=AndroidDcp.run(this,storage,job,request,c)
        } else if(request.string("mode")=="manual") {
            val source=Uri.parse(request.string("source")); val patch=Uri.parse(request.string("patch"))
            val expected=request.getValue("source_identity").jsonObject
            verifyInput(storage,source,expected,c)
            val patchExpected=request.getValue("patch_identity").jsonObject
            verifyInput(storage,patch,patchExpected,c)
            require(storage.isSeekable(source) && storage.isSeekable(patch)) { "Import non-seekable inputs into local storage first." }
            val output=File(final,"output.bin")
            // Keep room for the verified export as well as the working output.
            val max=(StatFs(work.absolutePath).availableBytes-64*1024*1024)/2
            require(max>0) { "Not enough working space." }
            decode(storage,source,patch,output,max,c)
            fileHash(output,c)
            files+=name to output
        } else {
            val catalog=Catalog(File(job,"catalog.json").readText())
            val parts=request.getValue("parts").jsonArray.map { it.jsonObject }
            val copies=request.getValue("copies").jsonArray.map { it.jsonObject }
            var completedBytes=0L
            var workingPeak=0L
            val downloads=mutableMapOf<String,Long>()
            // Completed outputs coexist with only the current pair of intermediates.
            for(p in parts) {
                val target=key(p.getValue("target_key").jsonArray)
                var previousTemporary=0L
                for(url in p.getValue("edges").jsonArray) {
                    val edge=catalog.edges.single { it.asset.url==url.jsonPrimitive.content }
                    downloads[edge.asset.sha256]=edge.asset.size
                    val size=catalog.nodes.getValue(edge.target).identity.size ?: 0
                    workingPeak=maxOf(workingPeak,Math.addExact(completedBytes,Math.addExact(previousTemporary,size)))
                    previousTemporary=size
                }
                completedBytes=Math.addExact(completedBytes,catalog.nodes.getValue(target).identity.size ?: 0)
            }
            for(p in copies) completedBytes=Math.addExact(completedBytes,p.getValue("bytes").jsonPrimitive.long)
            // Internal-storage export coexists with every verified working file.
            var required=Math.addExact(64L*1024*1024,maxOf(workingPeak,Math.multiplyExact(completedBytes,2)))
            for(size in downloads.values) required=Math.addExact(required,size)
            space(work,required)
            for((index,p) in parts.withIndex()) {
                c.check(); val source=Uri.parse(p.string("uri")); val start=catalog.nodes.getValue(key(p.getValue("source_key").jsonArray))
                val end=catalog.nodes.getValue(key(p.getValue("target_key").jsonArray))
                verifyBinary(storage,source,start.identity,c)
                val output=File(final,safeName(p.string("name")))
                if(validFile(storage,output,end.identity,c)) { files+=output.name to output; continue }
                var current=source
                var currentIdentity=start.identity
                for((step,url) in p.getValue("edges").jsonArray.withIndex()) {
                    c.check()
                    val edge=catalog.edges.single { it.asset.url==url.jsonPrimitive.content }
                    require(catalog.nodes.getValue(edge.source).identity==currentIdentity) { "Invalid route sequence." }
                    val identity=catalog.nodes.getValue(edge.target).identity
                    val next=File(work,"part-$index-step-$step.bin")
                    if(!validFile(storage,next,identity,c)) {
                        val patch=Network(this).download(edge.asset,c)
                        decode(storage,current,Uri.fromFile(patch),next,identity.size ?: (StatFs(work.absolutePath).availableBytes-64*1024*1024),c)
                        verifyBinary(storage,Uri.fromFile(next),identity,c)
                    }
                    if(current.scheme=="file" && File(current.path!!).parentFile==work) File(current.path!!).delete()
                    current=Uri.fromFile(next); currentIdentity=identity
                }
                require(currentIdentity.matches(end.identity.size ?: -1,end.identity.hashes) || currentIdentity==end.identity) { "Route did not reach the target." }
                val currentFile=if(current.scheme=="file") File(current.path!!) else null
                if(currentFile?.parentFile==work) require(currentFile.renameTo(output)) { "Cannot finalize intermediate output." }
                else storage.open(current).use { input->output.outputStream().use { copy(input,it,c,end.identity.size ?: Long.MAX_VALUE) } }
                verifyBinary(storage,Uri.fromFile(output),end.identity,c)
                if(current.scheme=="file" && File(current.path!!).parentFile==work) File(current.path!!).delete()
                files+=output.name to output
            }
            for(p in copies) {
                val source=Uri.parse(p.string("uri")); val identity=Identity(p.getValue("bytes").jsonPrimitive.long,mapOf("sha256" to p.string("sha256")))
                verifyBinary(storage,source,identity,c)
                val output=File(final,safeName(p.string("name")))
                if(!validFile(storage,output,identity,c)) storage.open(source).use { input->output.outputStream().use { copy(input,it,c,identity.size!!) } }
                verifyBinary(storage,Uri.fromFile(output),identity,c); files+=output.name to output
            }
        }
        c.check(); state("running","Saving verified output")
        storage.export(files,tree,name,request.getValue("grouped").jsonPrimitive.boolean,job,c)
        File(job,"work").deleteRecursively()
    }
    private fun verifyInput(storage:Storage,uri:Uri,record:JsonObject,c:Control) {
        verifyBinary(storage,uri,Identity(record.getValue("size").jsonPrimitive.long,mapOf("sha256" to record.string("sha256"))),c)
    }
    private fun verifyBinary(storage:Storage,uri:Uri,id:Identity,c:Control) {
        val actual=storage.hash(storage.describe(uri),id.hashes.keys,c)
        require(id.matches(actual.size,actual.hashes)) { "Source or output failed verification. Original file may have changed." }
    }
    private fun validFile(storage:Storage,file:File,id:Identity,c:Control):Boolean {
        if(!file.isFile)return false
        try { verifyBinary(storage,Uri.fromFile(file),id,c); return true }
        catch(e:CancellationException) { throw e } catch(e:Exception) { file.delete(); return false }
    }
    private fun decode(storage:Storage,source:Uri,patch:Uri,output:File,limit:Long,c:Control) {
        c.check(); output.delete(); c.progress("Applying xdelta",null)
        try {
            storage.fd(source).use { src->storage.fd(patch).use { delta->
                ParcelFileDescriptor.open(output,ParcelFileDescriptor.MODE_CREATE or ParcelFileDescriptor.MODE_TRUNCATE or ParcelFileDescriptor.MODE_READ_WRITE).use { dest->
                    NativePatch.decode(src.fd,delta.fd,dest.fd,limit) { _,written->
                        c.progress("Patching: ${written/(1024*1024)} MB",if(limit>0) written.toDouble()/limit else null)
                        !c.cancelled.get()
                    }
                }
            } }
        } catch(e:Exception) { output.delete(); throw e }
    }
}
fun key(a:JsonArray) = Key(a[0].jsonPrimitive.content,a[1].jsonPrimitive.content,a[2].jsonPrimitive.content,a[3].jsonPrimitive.content)
fun keyJson(k:Key) = JsonArray(listOf(k.game,k.edition,k.language,k.version).map(::str))
