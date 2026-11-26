package org.retrotrans.tools

import android.os.ParcelFileDescriptor
import android.os.StatFs
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.*
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.retrotrans.engine.NativePatch
import java.io.File
import java.security.MessageDigest

/** Opt-in: writes and hashes 4 GiB + 8 MiB, then removes only this test's files. */
@RunWith(AndroidJUnit4::class)
class LargeOutputTest {
    @Test fun outputBeyondFourGiBHasExactLengthAndHash() {
        Assume.assumeTrue(InstrumentationRegistry.getArguments().getString("large")=="true")
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        val root=File(context.cacheDir,"large-output-test").apply { mkdirs() }
        val window=8*1024*1024; val count=513; val length=window.toLong()*count
        try {
            assertTrue("Large-file check needs 5 GiB free",StatFs(root.path).availableBytes>length+(1L shl 30))
            val source=File(root,"source").apply { writeBytes(byteArrayOf(0)) }
            fun vi(n:Long):ByteArray { var v=n;val bytes=mutableListOf((v and 127).toByte());v=v ushr 7
                while(v>0) { bytes.add(0,((v and 127) or 128).toByte());v=v ushr 7 };return bytes.toByteArray() }
            val instructions=byteArrayOf(0)+vi(window.toLong()) // VCDIFF RUN of zero bytes.
            val delta=vi(window.toLong())+byteArrayOf(0)+vi(1)+vi(instructions.size.toLong())+vi(0)+byteArrayOf(0)+instructions
            val patch=File(root,"large.xdelta")
            patch.outputStream().use { stream->
                stream.write(byteArrayOf(0xd6.toByte(),0xc3.toByte(),0xc4.toByte(),0,0))
                repeat(count) { stream.write(byteArrayOf(0)+vi(delta.size.toLong())+delta) }
            }
            val output=File(root,"output.bin")
            ParcelFileDescriptor.open(source,ParcelFileDescriptor.MODE_READ_ONLY).use { s->
                ParcelFileDescriptor.open(patch,ParcelFileDescriptor.MODE_READ_ONLY).use { p->
                    ParcelFileDescriptor.open(output,ParcelFileDescriptor.MODE_CREATE or ParcelFileDescriptor.MODE_READ_WRITE).use { o->
                        assertEquals(length,NativePatch.decode(s.fd,p.fd,o.fd,length,NativePatch.Progress { _,_->true }))
                    }
                }
            }
            assertEquals(length,output.length())
            val expected=MessageDigest.getInstance("SHA-256"); val zeros=ByteArray(1024*1024)
            repeat((length/zeros.size).toInt()) { expected.update(zeros) }
            assertEquals(hex(expected.digest()),fileHash(output))
        } finally { root.deleteRecursively() }
    }
}
