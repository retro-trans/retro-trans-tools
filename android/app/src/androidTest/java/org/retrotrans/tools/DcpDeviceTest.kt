package org.retrotrans.tools

import android.net.Uri
import android.os.ParcelFileDescriptor
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.serialization.json.*
import org.junit.*
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.retrotrans.core.*
import org.retrotrans.engine.NativePatch
import java.io.File
import java.util.concurrent.CancellationException

@RunWith(AndroidJUnit4::class)
class DcpDeviceTest {
    private val instrumentation=InstrumentationRegistry.getInstrumentation()
    private val context=instrumentation.targetContext
    private lateinit var root:File
    @Before fun setup() { root=File(context.cacheDir,"dcp-device-${System.nanoTime()}").apply { mkdirs() } }
    @After fun cleanup() { root.deleteRecursively() }
    private fun decode(s:File,p:File,o:File,limit:Long) {
        ParcelFileDescriptor.open(s,ParcelFileDescriptor.MODE_READ_ONLY).use { source->
            ParcelFileDescriptor.open(p,ParcelFileDescriptor.MODE_READ_ONLY).use { patch->
                ParcelFileDescriptor.open(o,ParcelFileDescriptor.MODE_CREATE or ParcelFileDescriptor.MODE_TRUNCATE or ParcelFileDescriptor.MODE_READ_WRITE).use { output->
                    NativePatch.decode(source.fd,patch.fd,output.fd,limit) { _,_->true }
                }
            }
        }
    }
    @Test fun nativeDeltaDcpRoundTripAndSafBridge() {
        val f=DcpFixture(File(root,"input"));f.writePatch(true);val catalog=f.catalog();val storage=Storage(context)
        val docs=listOf("disc.gdi","low.bin","audio.raw","data.iso").map { storage.describe(Uri.fromFile(File(f.root,it))) }
        val inputs=storage.identify(docs,catalog,Control())
        val selection=AndroidDcp.selections(storage,docs,inputs,catalog,Control(),false).single()
        assertNotNull(catalog.plan(selection).dcp)
        val request=AndroidDcp.request(storage,selection.dcp!!,catalog.plan(selection).dcp,null,"unused-test-output","synthetic",Control())
        val job=File(root,"job").apply { mkdirs() };File(job,"catalog.json").writeText(catalog.raw)
        // Seed verified download cache: no external network is required by this synthetic test.
        val cached=File(context.filesDir,"patch-cache/${Dcp.hash(f.patch)}");cached.parentFile!!.mkdirs();f.patch.copyTo(cached,true)
        try {
            val result=AndroidDcp.run(context,storage,job,request,Control()).toMap()
            Dcp.Iso(result.getValue("track03.iso"),2048).use { assertEquals(f.tree(f.target),it.tree()) }
            val proof=Json.parseToJsonElement(result.getValue("DCP-VALIDATION.json").readText()).jsonObject
            assertEquals(JsonPrimitive(true),proof["release_metadata_verified"])
            val manual=AndroidDcp.request(storage,selection.dcp!!,null,storage.describe(Uri.fromFile(f.patch)),"unused","manual",Control())
            val manualJob=File(root,"manual-job").apply { mkdirs() }
            assertEquals(5,AndroidDcp.run(context,storage,manualJob,manual,Control()).size)
        } finally { cached.delete() }
    }
    @Test fun nativeDcpCancelsAndRejectsCorruptOutput() {
        val f=DcpFixture(File(root,"input"));f.writePatch(true);val out=File(root,"out");val work=File(root,"work").apply { mkdirs() }
        assertThrows(CancellationException::class.java) { Dcp.apply(f.descriptor,f.patch,out,work,check={throw CancellationException()}) { s,p,o,n->decode(s,p,o,n) } }
        assertFalse(out.exists())
        assertThrows(IllegalArgumentException::class.java) { Dcp.apply(f.descriptor,f.patch,out,work) { _,_,o,_->o.writeBytes(byteArrayOf(0)) } }
        assertFalse(out.exists())
    }
    @Test fun optionalRealDiscWithAndroidNativeDecoder() {
        val args=InstrumentationRegistry.getArguments();val source=args.getString("dcp_source")
        Assume.assumeTrue(source!=null)
        val patch=File(args.getString("dcp_patch") ?: error("Missing test patch."))
        val out=File(args.getString("dcp_output") ?: error("Missing new output path."))
        val scratch=File(root,"real-work").apply { mkdirs() }
        val result=Dcp.apply(File(source!!),patch,out,scratch,progress={android.util.Log.i("RetroTransDcp",it)}) { s,p,o,n->decode(s,p,o,n) }
        assertEquals(JsonPrimitive(true),result["release_metadata_verified"])
    }
}
