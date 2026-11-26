package org.retrotrans.tools

import android.content.Context
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.os.StatFs
import android.provider.DocumentsContract
import android.provider.OpenableColumns
import android.system.Os
import android.system.OsConstants
import android.util.AtomicFile
import androidx.documentfile.provider.DocumentFile
import kotlinx.serialization.json.*
import org.retrotrans.core.*
import java.io.File
import java.io.InputStream
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.CancellationException
import java.util.concurrent.atomic.AtomicBoolean

fun obj(vararg fields:Pair<String,JsonElement>) = JsonObject(mapOf(*fields))
fun str(s:String)=JsonPrimitive(s)
fun JsonObject.string(k:String)=getValue(k).jsonPrimitive.content
fun atomicWrite(file:File,text:String) {
    file.parentFile!!.mkdirs()
    val atomic=AtomicFile(file); val stream=atomic.startWrite()
    try { stream.write(text.toByteArray()); atomic.finishWrite(stream) }
    catch(e:Exception) { atomic.failWrite(stream); throw e }
}
fun readJson(file:File):JsonObject? = runCatching { Json.parseToJsonElement(AtomicFile(file).readFully().decodeToString()).jsonObject }.getOrNull()
class Control(val progress:(String,Double?)->Unit = {_,_->}) {
    val cancelled=AtomicBoolean(false)
    fun check() { if(cancelled.get() || Thread.currentThread().isInterrupted) throw CancellationException("Cancelled. Originals are unchanged.") }
}
data class Doc(val uri:Uri,val name:String,val size:Long?)
class Storage(val context:Context) {
    private val resolver=context.contentResolver
    fun describe(uri:Uri):Doc {
        if(uri.scheme=="file") {
            val f=File(requireNotNull(uri.path)); require(f.isFile) { "Local file is unavailable." }
            return Doc(uri,f.name,f.length())
        }
        resolver.query(uri,arrayOf(OpenableColumns.DISPLAY_NAME,OpenableColumns.SIZE),null,null,null)?.use { c->
            require(c.moveToFirst()) { "File is no longer available." }
            return Doc(uri,c.getString(0) ?: "binary",if(c.isNull(1)) null else c.getLong(1).takeIf { it>=0 })
        }
        error("Cannot read this file. Select it again.")
    }
    fun folder(uri:Uri):DocumentFile = DocumentFile.fromTreeUri(context,uri)?.also {
        require(it.isDirectory && it.canRead()) { "Folder access is unavailable. Select it again." }
    } ?: error("Select a folder.")
    fun list(uri:Uri):List<Doc> = folder(uri).listFiles().filter { it.isFile }.map { describe(it.uri) }
    fun open(uri:Uri):InputStream = resolver.openInputStream(uri) ?: error("Cannot open file.")
    fun fd(uri:Uri):ParcelFileDescriptor = resolver.openFileDescriptor(uri,"r") ?: error("Cannot open original.")
    fun isSeekable(uri:Uri):Boolean = runCatching { fd(uri).use { Os.lseek(it.fileDescriptor,0,OsConstants.SEEK_CUR) }; true }.getOrDefault(false)
    fun hash(doc:Doc,algorithms:Set<String>,control:Control):Input {
        val hashes=algorithms.associateWith { MessageDigest.getInstance(if(it=="sha1") "SHA-1" else "SHA-256") }
        var count=0L; val buffer=ByteArray(1024*1024)
        open(doc.uri).use { stream->while(true) {
            control.check(); val n=stream.read(buffer); if(n<0) break
            hashes.values.forEach { it.update(buffer,0,n) }; count+=n
            control.progress("Checking ${doc.name}: ${count/(1024*1024)} MB",doc.size?.takeIf { it>0 }?.let { count.toDouble()/it })
        } }
        require(doc.size==null || count==doc.size) { "File changed while reading: ${doc.name}" }
        return Input(doc.uri.toString(),doc.name,count,hashes.mapValues { hex(it.value.digest()) })
    }
    fun identify(docs:List<Doc>,catalog:Catalog,control:Control,explicit:Boolean=false):List<Input> = docs.map { d->
        control.check()
        val candidates=if(d.size==null && !explicit) emptyList() else catalog.candidates(d.size)
        val needed=candidates.map { if("sha256" in it.identity.hashes) "sha256" else "sha1" }.toSet()
        val dcp=catalog.dcpProfiles.any { p->p.tracks.any { it.size==d.size } }
        if(needed.isEmpty() && !dcp) Input(d.uri.toString(),d.name,d.size ?: -1,emptyMap()) else hash(d,needed+(if(dcp)setOf("sha256") else emptySet()),control)
    }
    fun importFile(doc:Doc,control:Control):Doc {
        val dir=File(context.filesDir,"imports").apply { mkdirs() }
        val output=File(dir,UUID.randomUUID().toString()+"-"+safeName(doc.name))
        require(doc.size!=null) { "This provider has no file size. Download the file to a local Games folder first." }
        space(dir,doc.size+64*1024*1024)
        try { open(doc.uri).use { input->output.outputStream().use { copy(input,it,control,doc.size) } }
            require(output.length()==doc.size) { "Incomplete import." }
            return Doc(Uri.fromFile(output),doc.name,output.length())
        } catch(e:Exception) { output.delete(); throw e }
    }
    fun prepareOutput(tree:Uri,name:String) {
        safeName(name)
        require(tree.authority=="com.android.externalstorage.documents") { "Choose local internal, SD-card or USB storage for output." }
        val root=folder(tree)
        require(root.canWrite()) { "Output folder is read-only." }
        require(root.listFiles().none { it.name.equals(name,true) }) { "That output name already exists. Choose a new name." }
    }
    /** Ledger is persisted before bytes are written. Recovery only deletes URIs created here. */
    fun export(files:List<Pair<String,File>>, tree:Uri, name:String, grouped:Boolean, job:File, control:Control):Uri {
        prepareOutput(tree,name)
        val root=folder(tree); val owned=mutableListOf<Uri>()
        fun remember(uri:Uri) { owned+=uri; atomicWrite(File(job,"exports.json"),JsonArray(owned.map { str(it.toString()) }).toString()) }
        val tempName="retro-trans-${UUID.randomUUID()}.partial"
        try {
            val parent=if(grouped) root.createDirectory(tempName)?.also { remember(it.uri) } ?: error("Cannot create output folder.") else root
            var single:DocumentFile?=null
            for ((filename,file) in files) {
                control.check()
                val target=parent.createFile("application/octet-stream",if(grouped) safeName(filename) else tempName) ?: error("Cannot create output.")
                remember(target.uri); single=target
                resolver.openOutputStream(target.uri,"w")!!.use { out->file.inputStream().use { copy(it,out,control,file.length()) } }
                val written=hash(describe(target.uri),setOf("sha256"),control)
                require(written.size==file.length() && written.hashes["sha256"]==fileHash(file,control)) { "Export verification failed." }
            }
            control.check(); prepareOutput(tree,name)
            val target=if(grouped) parent else single!!
            val renamed=DocumentsContract.renameDocument(resolver,target.uri,name) ?: error("Provider cannot finalize the output.")
            // Rename may change every descendant URI: replace the ledger with the new root.
            owned.clear(); remember(renamed)
            atomicWrite(File(job,"complete.json"),obj("uri" to str(renamed.toString()),"name" to str(name)).toString())
            File(job,"exports.json").delete()
            return renamed
        } catch(e:Exception) {
            val cleanup=cleanupExports(job)
            if(cleanup!=null) throw java.io.IOException("${e.message} $cleanup",e)
            throw e
        }
    }
    fun cleanupExports(job:File):String? {
        val ledger=File(job,"exports.json")
        if(!ledger.exists() || File(job,"complete.json").exists()) return null
        val owned=Json.parseToJsonElement(ledger.readText()).jsonArray.map { Uri.parse(it.jsonPrimitive.content) }
        var failed=false
        for(uri in owned.reversed()) {
            try { if(DocumentFile.fromSingleUri(context,uri)?.exists()==true && !DocumentsContract.deleteDocument(resolver,uri)) failed=true }
            catch(e:Exception) { failed=true }
        }
        if(!failed) ledger.delete()
        return if(failed) "Some unfinished output could not be removed; check the selected output folder." else null
    }
}
fun hex(bytes:ByteArray)=bytes.joinToString("") { "%02x".format(it) }
fun fileHash(file:File,control:Control=Control()):String {
    val digest=MessageDigest.getInstance("SHA-256"); val buffer=ByteArray(1024*1024)
    file.inputStream().use { s->while(true) { control.check(); val n=s.read(buffer); if(n<0)break; digest.update(buffer,0,n) } }
    return hex(digest.digest())
}
fun copy(input:InputStream,output:java.io.OutputStream,control:Control,max:Long):Long {
    val buffer=ByteArray(1024*1024); var done=0L
    while(true) { control.check(); val n=input.read(buffer); if(n<0) break; require(n<=max-done) { "File exceeds its declared size." }; output.write(buffer,0,n); done+=n
        control.progress("Copying: ${done/(1024*1024)} MB",if(max>0)done.toDouble()/max else null) }
    return done
}
fun space(directory:File,required:Long) { require(StatFs(directory.absolutePath).availableBytes>=required) { "Not enough working space. Need ${required/(1024*1024)} MB free." } }
