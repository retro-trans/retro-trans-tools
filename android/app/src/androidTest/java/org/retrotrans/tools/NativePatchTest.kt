package org.retrotrans.tools

import android.os.ParcelFileDescriptor
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.*
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.retrotrans.engine.NativePatch
import java.io.File
import java.io.RandomAccessFile
import java.util.concurrent.CancellationException

@RunWith(AndroidJUnit4::class)
class NativePatchTest {
    private val instrumentation=InstrumentationRegistry.getInstrumentation()
    private val context=instrumentation.targetContext
    private lateinit var root:File
    @Before fun setup() { root=File(context.cacheDir,"native-test").apply { mkdirs() } }
    @After fun cleanup() { root.deleteRecursively() }
    private fun fixture(name:String)=File(root,name).also { file->instrumentation.context.assets.open(name).use { input->file.outputStream().use { input.copyTo(it) } } }
    private fun decode(source:File,patch:File,output:File,limit:Long=64L*1024*1024,progress:NativePatch.Progress=NativePatch.Progress { _,_->true }):Long {
        ParcelFileDescriptor.open(source,ParcelFileDescriptor.MODE_READ_ONLY).use { s->
            ParcelFileDescriptor.open(patch,ParcelFileDescriptor.MODE_READ_ONLY).use { p->
                ParcelFileDescriptor.open(output,ParcelFileDescriptor.MODE_CREATE or ParcelFileDescriptor.MODE_TRUNCATE or ParcelFileDescriptor.MODE_READ_WRITE).use { o->
                    return NativePatch.decode(s.fd,p.fd,o.fd,limit,progress)
                }
            }
        }
    }
    @Test fun desktopPatchesRoundTripWithAllPublishedCompressionModes() {
        val source=fixture("source.bin"); val target=fixture("modified.bin"); val before=fileHash(source)
        for(mode in listOf("none","djw","lzma")) {
            val out=File(root,"out-$mode.bin")
            assertEquals(target.length(),decode(source,fixture("$mode.xdelta"),out))
            assertEquals(fileHash(target),fileHash(out))
            assertEquals(before,fileHash(source))
        }
    }
    @Test fun wrongSourceIsRejectedByChecksum() {
        val source=fixture("source.bin"); RandomAccessFile(source,"rw").use { it.seek(100); it.writeByte(37) }
        assertThrows(java.io.IOException::class.java) { decode(source,fixture("lzma.xdelta"),File(root,"out")) }
    }
    @Test fun truncatedAndCorruptPatchesAreRejected() {
        val source=fixture("source.bin"); val patch=fixture("none.xdelta")
        RandomAccessFile(patch,"rw").use { it.setLength(it.length()-5) }
        assertThrows(java.io.IOException::class.java) { decode(source,patch,File(root,"out")) }
        patch.writeBytes(byteArrayOf(0,1,2,3,4))
        assertThrows(java.io.IOException::class.java) { decode(source,patch,File(root,"out")) }
    }
    @Test fun cancellationAndOutputBounds() {
        val source=fixture("source.bin");val patch=fixture("djw.xdelta")
        assertThrows(CancellationException::class.java) { decode(source,patch,File(root,"cancel"),progress=NativePatch.Progress { _,_->false }) }
        assertThrows(CancellationException::class.java) { decode(source,patch,File(root,"cancel-after-write"),progress=NativePatch.Progress { _,written->written==0L }) }
        assertTrue(File(root,"cancel-after-write").length()>0)
        assertThrows(java.io.IOException::class.java) { decode(source,patch,File(root,"bounded"),32) }
        assertTrue(File(root,"bounded").length()<=32)
    }
    @Test fun sourceOffsetsBeyondFourGiB() {
        val source=File(root,"large-source"); val position=(5L shl 30)+123
        val payload=ByteArray(32768) { ((it*37)%251).toByte() }
        RandomAccessFile(source,"rw").use { it.seek(position); it.write(payload) }
        fun vi(n:Long):ByteArray { var v=n;val bytes=mutableListOf((v and 127).toByte());v=v ushr 7
            while(v>0) { bytes.add(0,((v and 127) or 128).toByte());v=v ushr 7 };return bytes.toByteArray() }
        val instructions=byteArrayOf(19)+vi(payload.size.toLong())
        val delta=vi(payload.size.toLong())+byteArrayOf(0)+vi(0)+vi(instructions.size.toLong())+vi(1)+instructions+byteArrayOf(0)
        val patch=File(root,"large.xdelta")
        patch.writeBytes(byteArrayOf(0xd6.toByte(),0xc3.toByte(),0xc4.toByte(),0,0,1)+vi(payload.size.toLong())+vi(position)+vi(delta.size.toLong())+delta)
        val output=File(root,"large-output")
        assertEquals(payload.size.toLong(),decode(source,patch,output))
        assertArrayEquals(payload,output.readBytes())
    }
    @Test fun pipeSourceFailsClearlyInsteadOfSeekingIncorrectly() {
        val pipes=ParcelFileDescriptor.createPipe(); val patch=fixture("none.xdelta")
        try { ParcelFileDescriptor.open(patch,ParcelFileDescriptor.MODE_READ_ONLY).use { p->
            ParcelFileDescriptor.open(File(root,"pipe-output"),ParcelFileDescriptor.MODE_CREATE or ParcelFileDescriptor.MODE_READ_WRITE).use { o->
                val error=assertThrows(java.io.IOException::class.java) { NativePatch.decode(pipes[0].fd,p.fd,o.fd,10000000,NativePatch.Progress { _,_->true }) }
                assertTrue(error.message!!.contains("seekable"))
            }
        } } finally { pipes.forEach { it.close() } }
    }
    @Test fun bundledCatalogLoadsAndLocalRecognitionIsExact() {
        val c=Network(context).load();assertTrue(c.edges.size>=242)
        val file=fixture("source.bin"); val doc=Storage(context).describe(android.net.Uri.fromFile(file))
        val checked=Storage(context).hash(doc,setOf("sha256","sha1"),Control())
        assertEquals(file.length(),checked.size);assertEquals(fileHash(file),checked.hashes["sha256"])
        assertTrue(c.recognize(checked).isEmpty())
    }
}
