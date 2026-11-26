package org.retrotrans.tools

import android.content.Context
import android.net.Uri
import android.os.ParcelFileDescriptor
import kotlinx.serialization.json.*
import org.retrotrans.core.*
import org.retrotrans.engine.NativePatch
import java.io.File

/** Bridge from Storage Access Framework to the platform-independent DCP kernel.
 * Stages only read-only originals into the current app-owned job; never guesses URI paths.
 */
object AndroidDcp {
    fun selections(storage:Storage,docs:List<Doc>,inputs:List<Input>,catalog:Catalog,c:Control,manual:Boolean):List<Selection> {
        return docs.filter { it.name.endsWith(".cue",true) || it.name.endsWith(".gdi",true) }.mapNotNull { descriptor->
            c.check()
            require(descriptor.size!=null && descriptor.size<=256*1024) { "Oversized/unknown-size disc descriptor." }
            val text=storage.open(descriptor.uri).use { input->java.io.ByteArrayOutputStream().also { copy(input,it,c,256L*1024) }.toString("UTF-8") }
            try {
                val checked=Input(descriptor.uri.toString(),descriptor.name,descriptor.size,emptyMap())
                if(manual) {
                    val tracks=Dcp.tracks(descriptor.name,text).map { t->inputs.singleOrNull { it.name==t.name } ?: error("Missing ${t.name}") }
                    Selection("${descriptor.name} (local DCP source)",dcp=DcpSelection(checked,tracks,emptyList()))
                } else DcpCatalog.recognize(catalog.dcpProfiles,checked,text,inputs)
            } catch(e:java.util.concurrent.CancellationException) { throw e }
            catch(e:IllegalArgumentException) { if(manual)throw e else null }
            catch(e:IllegalStateException) { if(manual)throw e else null }
        }
    }
    fun request(storage:Storage,selection:DcpSelection,profile:DcpProfile?,localPatch:Doc?,output:String,name:String,c:Control):JsonObject {
        fun record(input:Input):JsonObject {
            val actual=storage.hash(storage.describe(Uri.parse(input.uri)),setOf("sha256"),c)
            if(input.hashes.isNotEmpty())require(input.size==actual.size && input.hashes["sha256"]==actual.hashes["sha256"]) { "Original changed since recognition. Scan again." }
            return obj("uri" to str(input.uri),"name" to str(safeName(input.name)),"size" to JsonPrimitive(actual.size),"sha256" to str(actual.hashes.getValue("sha256")))
        }
        val patch=localPatch?.let { record(Input(it.uri.toString(),it.name,it.size ?: -1,emptyMap())) }
        require((profile!=null)!=(patch!=null))
        return obj("mode" to str("dcp"),"output" to str(output),"name" to str(name),"grouped" to JsonPrimitive(true),
            "descriptor" to record(selection.descriptor),"tracks" to JsonArray(selection.tracks.map(::record)),
            "asset_url" to (profile?.let { str(it.asset.url) } ?: JsonNull),"patch" to (patch ?: JsonNull))
    }
    fun run(context:Context,storage:Storage,job:File,request:JsonObject,c:Control):List<Pair<String,File>> {
        val work=File(job,"work").apply { mkdirs() }
        // No partial DCP result is reused: resume repeats verification and application.
        val dcpWork=File(work,"dcp");require(!dcpWork.exists() || dcpWork.deleteRecursively());require(dcpWork.mkdir())
        val input=File(dcpWork,"input").apply { mkdirs() };val scratch=File(dcpWork,"scratch").apply { mkdirs() }
        val records=listOf(request.getValue("descriptor").jsonObject)+request.getValue("tracks").jsonArray.map { it.jsonObject }
        require(records.size==4 && records.map { it.string("name").lowercase() }.distinct().size==4)
        val localPatch=request["patch"] as? JsonObject
        val profile=if(localPatch==null) Catalog(File(job,"catalog.json").readText()).dcpProfiles.single { it.asset.url==request.string("asset_url") } else null
        val expandedEstimate=profile?.asset?.size ?: localPatch!!.getValue("size").jsonPrimitive.long
        val inputBytes=records.sumOf { it.getValue("size").jsonPrimitive.long.also { size->require(size in 1..(4L*1024*1024*1024)) } }
        // Staged originals + cooked GDI + export + one source/target pair + download.
        // The kernel additionally checks actual ZIP expansion before patching.
        space(work,Math.addExact(Math.multiplyExact(inputBytes,3),Math.addExact(Math.multiplyExact(expandedEstimate,4),128L*1024*1024)))
        fun stage(record:JsonObject,directory:File):File {
            val source=Uri.parse(record.string("uri"));val doc=storage.describe(source)
            val size=record.getValue("size").jsonPrimitive.long
            require(doc.size==size) { "Source size changed. Scan/select it again." }
            val file=File(directory,safeName(record.string("name")))
            storage.open(source).use { src->file.outputStream().use { dest->require(copy(src,dest,c,size)==size) } }
            require(fileHash(file,c)==record.string("sha256")) { "Source changed since job preparation." }
            return file
        }
        val descriptor=stage(records.first(),input)
        records.drop(1).forEach { stage(it,input) }
        if(profile!=null) require(records.drop(1).zip(profile.tracks).all { (r,id)->id.size==r.getValue("size").jsonPrimitive.long && id.hashes["sha256"]==r.string("sha256") }) { "Original tracks disagree with catalog." }
        val patch=profile?.let { Network(context).download(it.asset,c) } ?: stage(localPatch!!,File(dcpWork,"patch").apply { mkdirs() })
        val archive=Dcp.inspect(patch);space(work,2L*inputBytes+archive.expanded*2+64L*1024*1024)
        val output=File(dcpWork,"output")
        Dcp.apply(descriptor,patch,output,scratch,profile?.metadata,check={c.check()},progress={c.progress(it,null)}) { original,delta,out,limit->
            space(work,limit.coerceAtMost(inputBytes)+64L*1024*1024)
            try {
                ParcelFileDescriptor.open(original,ParcelFileDescriptor.MODE_READ_ONLY).use { s->
                    ParcelFileDescriptor.open(delta,ParcelFileDescriptor.MODE_READ_ONLY).use { p->
                        ParcelFileDescriptor.open(out,ParcelFileDescriptor.MODE_CREATE or ParcelFileDescriptor.MODE_TRUNCATE or ParcelFileDescriptor.MODE_READ_WRITE).use { o->
                            NativePatch.decode(s.fd,p.fd,o.fd,limit) { _,bytes->c.progress("Applying DCP file: ${bytes/(1024*1024)} MB",null);!c.cancelled.get() }
                        }
                    }
                }
            } catch(e:Exception) { out.delete();throw e }
        }
        // Re-read the actual documents, not just staging copies, before exporting.
        for(r in records+(localPatch?.let { listOf(it) } ?: emptyList())) {
            val actual=storage.hash(storage.describe(Uri.parse(r.string("uri"))),setOf("sha256"),c)
            require(actual.size==r.getValue("size").jsonPrimitive.long && actual.hashes["sha256"]==r.string("sha256")) { "Original document changed while patching; output not exported." }
        }
        return output.listFiles()!!.filter { it.isFile }.map { it.name to it }
    }
}
