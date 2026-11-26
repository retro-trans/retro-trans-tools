package org.retrotrans.core

import kotlinx.serialization.json.*
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/** Legal synthetic Dreamcast-like filesystem, never game content. Shared JVM/device tests. */
class DcpFixture(val root:File) {
    val original=ByteArray(3000) { ((it*7)%251).toByte() }
    val target=ByteArray(9000) { ((it*13+3)%251).toByte() }
    val ip=ByteArray(32768).also { "TOC1".toByteArray().copyInto(it,0x100) }
    val patchedIp=ip.copyOf().also { it[0x3d]=49 }
    val descriptor=File(root,"disc.gdi")
    val patch=File(root,"fixture.dcp")
    private fun both(b:ByteArray,p:Int,n:Long) { repeat(4) { b[p+it]=(n ushr (8*it)).toByte();b[p+4+it]=(n ushr (8*(3-it))).toByte() } }
    private fun record(name:ByteArray,lba:Long,size:Long,dir:Boolean=false):ByteArray {
        val row=ByteArray(33+name.size+(if(name.size%2==0)1 else 0));row[0]=row.size.toByte()
        both(row,2,lba);both(row,10,size);row[25]=if(dir)2 else 0;row[28]=1;row[31]=1;row[32]=name.size.toByte();name.copyInto(row,33);return row
    }
    fun tree(bytes:ByteArray)=Dcp.sha(buildJsonObject { put("ALPHA.DAT",buildJsonObject { put("bytes",bytes.size);put("sha256",Dcp.sha(bytes)) }) }.toString().toByteArray())
    val metadata=buildJsonObject {
        put("retro_trans_dcp",1);put("game_id","synthetic-dcp");put("game_name","Synthetic DCP");put("disc",1)
        put("version","1.0");put("source_version","original");put("target_version","1.0")
        put("source_tree_sha256",tree(original));put("target_tree_sha256",tree(target));put("bootsector_invariant_sha256",Dcp.bootHash(patchedIp))
    }
    init {
        root.mkdirs();File(root,"low.bin").writeBytes(ByteArray(2048));File(root,"audio.raw").writeBytes(ByteArray(2352*4) { if(it>2352)13 else 0 })
        val image=ByteArray(128*2048);ip.copyInto(image)
        val pvd=ByteArray(2048);pvd[0]=1;"CD001".toByteArray().copyInto(pvd,1);pvd[6]=1
        both(pvd,80,45128);pvd[128]=0;pvd[129]=8;pvd[130]=8
        both(pvd,132,0);record(byteArrayOf(0),45040,2048,true).copyInto(pvd,156);pvd.copyInto(image,16*2048)
        val end=ByteArray(2048);end[0]=(-1).toByte();"CD001".toByteArray().copyInto(end,1);end[6]=1;end.copyInto(image,17*2048)
        var at=40*2048
        for(row in listOf(record(byteArrayOf(0),45040,2048,true),record(byteArrayOf(1),45040,2048,true),record("ALPHA.DAT;1".toByteArray(),45048,original.size.toLong()))) { row.copyInto(image,at);at+=row.size }
        original.copyInto(image,48*2048);File(root,"data.iso").writeBytes(image)
        descriptor.writeText("3\n1 0 4 2048 low.bin 0\n2 450 0 2352 audio.raw 0\n3 45000 4 2048 data.iso 0\n")
    }
    private fun vi(n:Long):ByteArray { var v=n;val bytes=mutableListOf((v and 127).toByte());v=v ushr 7
        while(v>0) { bytes.add(0,((v and 127) or 128).toByte());v=v ushr 7 };return bytes.toByteArray() }
    fun writePatch(delta:Boolean=false,meta:JsonObject=metadata,extra:Pair<String,ByteArray>?=null):File {
        val instructions=byteArrayOf(1)+vi(target.size.toLong())
        val window=vi(target.size.toLong())+byteArrayOf(0)+vi(target.size.toLong())+vi(instructions.size.toLong())+vi(0)+target+instructions
        val vcdiff=byteArrayOf(0xd6.toByte(),0xc3.toByte(),0xc4.toByte(),0,0,0)+vi(window.size.toLong())+window
        ZipOutputStream(patch.outputStream()).use { zip->
            zip.setComment(meta.toString())
            for((name,bytes) in listOf((if(delta)"ALPHA.DAT.xdelta" else "ALPHA.DAT") to (if(delta)vcdiff else target),"bootsector/IP.BIN" to patchedIp)+(extra?.let { listOf(it) } ?: emptyList())) {
                zip.putNextEntry(ZipEntry(name));zip.write(bytes);zip.closeEntry()
            }
        };return patch
    }
    fun catalog():Catalog {
        val row=buildJsonObject {
            put("patch",patch.name);put("bytes",patch.length());put("sha256",Dcp.hash(patch));put("edition","disc1");put("metadata",metadata)
            put("source_tracks",JsonArray(listOf("low.bin","audio.raw","data.iso").map { n->File(root,n).let { f->buildJsonObject { put("bytes",f.length());put("sha256",Dcp.hash(f)) } } }))
        }
        val manifest=buildJsonObject {
            put("schema_version",1);put("format","DCP");put("platform","Dreamcast");put("minimum_app_version","0.5.20")
            put("game_id","synthetic-dcp");put("game_name","Synthetic DCP");put("language","en");put("version","1.0");put("source_commit","1".repeat(40));put("patches",JsonArray(listOf(row)))
        }
        return Catalog(buildJsonObject {
            put("schema_version",1);put("releases",JsonArray(emptyList()))
            put("dcp_releases",JsonArray(listOf(buildJsonObject { put("repo","retro-trans/synthetic");put("tag","v1.0");put("manifest_sha256",Dcp.sha(manifest.toString().toByteArray()));put("manifest",manifest)
                put("assets",buildJsonObject { put(patch.name,"https://github.com/retro-trans/synthetic/releases/download/v1.0/${patch.name}") }) })))
        }.toString())
    }
}
