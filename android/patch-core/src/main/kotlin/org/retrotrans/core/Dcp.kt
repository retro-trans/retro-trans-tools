package org.retrotrans.core

import kotlinx.serialization.json.*
import java.io.File
import java.io.RandomAccessFile
import java.security.MessageDigest
import java.util.Locale
import java.util.zip.ZipFile

/** Android-native, bounded DCP application. No downloaded executable or .NET runtime.
 * Initial format: verified same-file-tree patches, three-track MODE1 CUE/GDI -> GDI.
 * Unsupported layouts/additions fail closed rather than losing tracks or files.
 */
object Dcp {
    private const val BASE=45000L
    private const val BLOCK=2048
    private const val MAX_EXPANDED=4L*1024*1024*1024
    fun sha(bytes:ByteArray)=MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    fun hash(file:File,check:()->Unit={}):String {
        val digest=MessageDigest.getInstance("SHA-256"); val buffer=ByteArray(1024*1024)
        file.inputStream().use { input->while(true) { check();val n=input.read(buffer);if(n<0)break;digest.update(buffer,0,n) } }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }
    private fun JsonObject.s(k:String)=getValue(k).jsonPrimitive.content
    fun metadata(value:JsonObject):JsonObject {
        require(value["retro_trans_dcp"]==JsonPrimitive(1)) { "This Android build requires a DCP with Retro Trans verification metadata." }
        for(k in listOf("source_tree_sha256","target_tree_sha256","bootsector_invariant_sha256"))
            require(Regex("[a-f0-9]{64}").matches(value.s(k))) { "Invalid DCP verification metadata." }
        require(value.s("game_id").isNotBlank() && value.s("game_name").isNotBlank())
        require(value.getValue("disc").jsonPrimitive.int in 1..99)
        require(compareVersions(value.s("target_version"),value.s("source_version"))>0 && value.s("version")==value.s("target_version"))
        return value
    }
    private fun path(raw:String):String {
        require('\\' !in raw && !raw.startsWith('/') && raw.length<=1024) { "Unsafe DCP archive path." }
        val parts=raw.removeSuffix("/").split('/');parts.forEach(::safeName)
        return parts.joinToString("/")
    }
    data class Archive(val metadata:JsonObject,val expanded:Long,val names:List<String>)
    fun inspect(patch:File):Archive {
        // Java ZipEntry does not expose Unix file types: check central attributes explicitly.
        RandomAccessFile(patch,"r").use { f->
            require(f.length()>=22) { "Invalid DCP ZIP." }
            val tail=ByteArray(minOf(f.length(),65557).toInt());f.seek(f.length()-tail.size);f.readFully(tail)
            val end=(tail.size-22 downTo 0).firstOrNull { u32(tail,it)==0x06054b50L && it+22+u16(tail,it+20)==tail.size } ?: error("Missing DCP ZIP directory.")
            require(u16(tail,end+4)==0 && u16(tail,end+6)==0 && u16(tail,end+8)==u16(tail,end+10)) { "Split ZIPs are unsupported." }
            val count=u16(tail,end+10);val length=u32(tail,end+12);val offset=u32(tail,end+16)
            require(count in 1..50000 && length in 46..(16L*1024*1024) && offset+length==f.length()-tail.size+end) { "Unsupported DCP ZIP directory." }
            val directory=ByteArray(length.toInt());f.seek(offset);f.readFully(directory);var pos=0
            repeat(count) {
                require(pos+46<=directory.size && u32(directory,pos)==0x02014b50L) { "Invalid DCP ZIP entry." }
                require(u16(directory,pos+8) and 1==0 && u16(directory,pos+10) in listOf(0,8)) { "Encrypted/unsupported DCP compression." }
                val kind=(u32(directory,pos+38) ushr 16).toInt() and 0xf000
                require(kind in listOf(0,0x4000,0x8000)) { "DCP links/devices are unsupported." }
                require(u32(directory,pos+24)!=0xffffffffL && u32(directory,pos+42)<offset) { "ZIP64 DCPs are unsupported." }
                pos+=46+u16(directory,pos+28)+u16(directory,pos+30)+u16(directory,pos+32)
                require(pos<=directory.size)
            }
            require(pos==directory.size)
        }
        ZipFile(patch).use { zip->
            val entries=zip.entries().toList();val names=mutableSetOf<String>();var total=0L
            for(e in entries) {
                val p=path(e.name);require(names.add(p.lowercase(Locale.ROOT))) { "Duplicate DCP archive path." }
                require(e.size>=0 && e.size<=MAX_EXPANDED-total) { "DCP expands beyond supported size." };total+=e.size
            }
            val comment=zip.comment ?: error("DCP has no verification metadata.")
            require(comment.toByteArray().size<=65535)
            return Archive(metadata(Json.parseToJsonElement(comment).jsonObject),total,entries.filterNot { it.isDirectory }.map { path(it.name) })
        }
    }
    data class Track(val name:String,val lba:Long,val type:Int,val sector:Int,val offset:Long=0)
    fun tracks(name:String,text:String):List<Track> {
        require(text.length<=256*1024)
        val rows=text.removePrefix("\uFEFF").lineSequence().map { it.trim() }.filter { it.isNotEmpty() }.toList()
        val tracks=if(name.endsWith(".gdi",true)) {
            require(rows.firstOrNull()=="3" && rows.size==4) { "Android DCP currently supports three-track GDI sets only." }
            rows.drop(1).mapIndexed { index,line->
                val m=Regex("(\\d+)\\s+(\\d+)\\s+(\\d+)\\s+(\\d+)\\s+(?:\"([^\"]+)\"|(\\S+))\\s+(\\d+)").matchEntire(line) ?: error("Invalid GDI track.")
                val g=m.groupValues;require(g[1].toInt()==index+1)
                Track(safeName(g[5].ifEmpty { g[6] }),g[2].toLong(),g[3].toInt(),g[4].toInt(),g[7].toLong())
            }
        } else {
            require(name.endsWith(".cue",true)) { "Choose a CUE or GDI. Android CHD conversion is not included." }
            val files=mutableListOf<String>();val commands=mutableListOf<String>()
            rows.forEach { line->
                if(line.startsWith("REM ",true)) return@forEach
                val m=Regex("FILE\\s+\"([^\"]+)\"\\s+BINARY",RegexOption.IGNORE_CASE).matchEntire(line)
                if(m!=null) { files+=safeName(m.groupValues[1]);commands+="FILE" }
                else commands+=line.uppercase(Locale.ROOT).replace(Regex("\\s+")," ")
            }
            require(commands==listOf("FILE","TRACK 01 MODE1/2352","INDEX 01 00:00:00","FILE","TRACK 02 AUDIO","INDEX 00 00:00:00","INDEX 01 00:02:00","FILE","TRACK 03 MODE1/2352","INDEX 01 00:00:00")) {
                "Unsupported CUE layout. This build accepts the three-track Redump Dreamcast layout; use desktop DCP for other layouts."
            }
            listOf(Track(files[0],0,4,2352),Track(files[1],450,0,2352),Track(files[2],BASE,4,2352))
        }
        require(tracks.map { it.lba }==listOf(0L,450L,BASE) && tracks.map { it.type }==listOf(4,0,4) && tracks.all { it.offset==0L } &&
            tracks[0].sector in listOf(2048,2352) && tracks[1].sector==2352 && tracks[2].sector in listOf(2048,2352)) { "Unsupported DCP track geometry." }
        require(tracks.map { it.name.lowercase(Locale.ROOT) }.distinct().size==3) { "Duplicate disc track." }
        return tracks
    }
    private fun u16(b:ByteArray,p:Int)=(b[p].toInt() and 255) or ((b[p+1].toInt() and 255) shl 8)
    private fun u32(b:ByteArray,p:Int)=(0..3).fold(0L) { n,i->n or ((b[p+i].toLong() and 255) shl (8*i)) }
    private fun both(b:ByteArray,p:Int):Long {
        val n=u32(b,p);require(n==(0..3).fold(0L) { a,i->(a shl 8) or (b[p+4+i].toLong() and 255) }) { "ISO endian fields disagree." };return n
    }
    private fun putBoth(b:ByteArray,p:Int,n:Long) { repeat(4) { b[p+it]=(n ushr (8*it)).toByte();b[p+4+it]=(n ushr (8*(3-it))).toByte() } }
    data class Entry(val path:String,val lba:Long,val size:Long,val record:Long)
    class Iso(private val file:File,private val sector:Int,private val check:()->Unit={}):AutoCloseable {
        private val f=RandomAccessFile(file,"r")
        val sectors=f.length()/sector
        val files=linkedMapOf<String,Entry>()
        private val used=mutableListOf(BASE to BASE+32)
        init {
            try {
                require(sector in listOf(2048,2352) && f.length()%sector==0L && sectors in 32..(549150-BASE)) { "Unsupported/truncated data track." }
                val pvd=read(BASE+16,2048)
                require(pvd[0]==1.toByte() && pvd.copyOfRange(1,6).decodeToString()=="CD001" && pvd[6]==1.toByte() && u16(pvd,128)==2048) { "Unsupported ISO9660 data track." }
                require(both(pvd,80)<=BASE+sectors && both(pvd,80)>=BASE+32)
                // No supplementary/Joliet metadata may retain stale extents.
                var terminated=false
                for(i in 17L..31L) { val v=read(BASE+i,2048);require(v.copyOfRange(1,6).decodeToString()=="CD001");if(v[0]==(-1).toByte()) { terminated=true;break };error("Supplementary ISO volumes are unsupported.") }
                require(terminated)
                val table=both(pvd,132);require(table<=16*1024*1024)
                for((off,big) in listOf(140 to false,144 to false,148 to true,152 to true)) {
                    val lba=if(big)(0..3).fold(0L) { n,i->(n shl 8) or (pvd[off+i].toLong() and 255) } else u32(pvd,off)
                    if(lba!=0L) reserve(lba,table)
                }
                val seen=mutableSetOf<Long>();val names=mutableSetOf<String>()
                fun directory(lba:Long,size:Long,parent:String,depth:Int) {
                    require(depth<=16 && seen.add(lba) && seen.size<=8192 && size in 1..(16L*1024*1024)) { "Invalid/cyclic ISO directory." }
                    reserve(lba,size);val bytes=read(lba,size.toInt());var at=0
                    while(at<bytes.size) {
                        check();val len=bytes[at].toInt() and 255
                        if(len==0) { at=(at/2048+1)*2048;continue }
                        require(len>=34 && at+len<=bytes.size && at%2048+len<=2048)
                        val id=bytes[at+32].toInt() and 255;require(id>0 && 33+id<=len)
                        val raw=bytes.copyOfRange(at+33,at+33+id)
                        if(!(id==1 && raw[0] in listOf(0.toByte(),1.toByte()))) {
                            require(raw.all { it.toInt() in 32..126 } && bytes[at+1]==0.toByte() && bytes[at+26]==0.toByte() && bytes[at+27]==0.toByte()) { "Unsupported ISO filename/interleaving." }
                            val part=safeName(raw.decodeToString().substringBefore(';'));val path=parent+part
                            require(names.add(path.lowercase(Locale.ROOT)) && names.size<=50000)
                            val extent=both(bytes,at+2);val length=both(bytes,at+10);val flags=bytes[at+25].toInt() and 255
                            require(flags and 0x80==0) { "Multi-extent ISO files are unsupported." }
                            if(flags and 2!=0) directory(extent,length,"$path/",depth+1)
                            else { reserve(extent,length);files[path]=Entry(path,extent,length,(lba-BASE)*2048+at) }
                        }
                        at+=len
                    }
                }
                directory(both(pvd,158),both(pvd,166),"",0)
                require(files.isNotEmpty())
            } catch(e:Exception) { f.close();throw e }
        }
        private fun reserve(lba:Long,size:Long) { require(size>=0 && lba>=BASE && lba+(size+2047)/2048<=BASE+sectors);if(size>0)used+=lba to lba+(size+2047)/2048 }
        fun read(lba:Long,size:Int):ByteArray {
            require(size>=0 && lba>=BASE && (lba-BASE)*2048+size<=sectors*2048)
            val bytes=ByteArray(size);var at=0;val raw=ByteArray(sector)
            while(at<size) { check();f.seek((lba-BASE+at/2048)*sector);f.readFully(raw)
                if(sector==2352) require(raw[0]==0.toByte() && raw[15]==1.toByte()) { "Not a MODE1 raw sector." }
                val n=minOf(2048,size-at);raw.copyInto(bytes,at,if(sector==2352)16 else 0,(if(sector==2352)16 else 0)+n);at+=n }
            return bytes
        }
        fun extract(entry:Entry,out:File) { out.outputStream().use { target->var done=0L;while(done<entry.size) { check();val n=minOf(128L*2048,entry.size-done).toInt();target.write(read(entry.lba+done/2048,n));done+=n } } }
        fun tree():String {
            val result=linkedMapOf<String,JsonElement>()
            for((name,e) in files.toSortedMap()) {
                val digest=MessageDigest.getInstance("SHA-256");var done=0L
                while(done<e.size) { check();val n=minOf(128L*2048,e.size-done).toInt();digest.update(read(e.lba+done/2048,n));done+=n }
                // Canonical key order matches desktop json.dumps(sort_keys=True).
                result[name]=buildJsonObject { put("bytes",e.size);put("sha256",digest.digest().joinToString("") { "%02x".format(it) }) }
            }
            return sha(JsonObject(result).toString().toByteArray())
        }
        fun boot():ByteArray=read(BASE,32768)
        fun free(size:Long):Long {
            val blocks=(size+2047)/2048;var start=BASE+32
            for((lo,hi) in (used+((BASE+sectors) to (BASE+sectors))).sortedBy { it.first }) {
                if(lo-start>=blocks) {
                    // Unreferenced is not necessarily unused; never overwrite opaque nonzero data.
                    var zero=true;var at=start
                    while(at<start+blocks) { check();val n=minOf(128L,start+blocks-at).toInt();if(read(at,n*2048).any { it!=0.toByte() }) { zero=false;break };at+=n }
                    if(zero) { used+=start to start+blocks;return start }
                }
                start=maxOf(start,hi)
            }
            error("No verified zero free extent for expanded DCP file. Use desktop DCP rebuilding.")
        }
        fun cooked(output:File) {
            output.outputStream().buffered(1024*1024).use { out->var at=BASE;while(at<BASE+sectors) { check();val count=minOf(128L,BASE+sectors-at).toInt();out.write(read(at,count*2048));at+=count } }
        }
        override fun close()=f.close()
    }
    fun bootHash(ip:ByteArray):String {
        require(ip.size==32768 && ip.copyOfRange(0x100,0x104).decodeToString()=="TOC1") { "Unsupported Dreamcast boot track table." }
        val normalized=ip.copyOf();normalized.fill(0,0x104,0x108);return sha(normalized)
    }
    fun apply(descriptor:File,patch:File,output:File,work:File,expected:JsonObject?=null,
        check:()->Unit={},progress:(String)->Unit={},decode:(File,File,File,Long)->Unit):JsonObject {
        require(!output.exists() && work.isDirectory)
        val archive=inspect(patch);if(expected!=null)require(archive.metadata==expected) { "DCP package metadata disagrees with catalog." }
        val tracks=tracks(descriptor.name,descriptor.readText());val source=tracks.map { File(descriptor.parentFile,it.name).also { f->require(f.isFile && f.length()>0 && f.length()%it.sector==0L) { "Missing/truncated companion track." } } }
        val before=source.map { hash(it,check) }
        val high=File(output,"track03.iso")
        var created=false
        try {
            require(output.mkdir());created=true
            Iso(source[2],tracks[2].sector,check).use { iso->
                progress("Verifying original game-file tree")
                require(iso.tree()==archive.metadata.s("source_tree_sha256")) { "DCP requires a different source game-file tree." }
                // Initial engine preserves the existing ISO directory tree, including all metadata.
                val replacements=archive.names.filter { it!="bootsector/IP.BIN" }.map { name->if(name.endsWith(".xdelta",true)) name.dropLast(7) else name }
                require(replacements.distinct().size==replacements.size && replacements.all { it in iso.files }) { "DCP adds/aliases files. This Android build supports same-tree replacements only; use desktop DCP." }
                progress("Copying data track to GDI output")
                iso.cooked(high)
                ZipFile(patch).use { zip->
                    RandomAccessFile(high,"rw").use { out->
                        for(name in archive.names) {
                            check();val member=zip.getEntry(name);val delta=File(work,"member.bin");val original=File(work,"original.bin");val patched=File(work,"patched.bin")
                            zip.getInputStream(member).use { input->delta.outputStream().use { dest->val b=ByteArray(1024*1024);var count=0L;while(true) { check();val n=input.read(b);if(n<0)break;count+=n;require(count<=member.size);dest.write(b,0,n) };require(count==member.size) } }
                            if(name=="bootsector/IP.BIN") { require(delta.length()==32768L);out.seek(0);out.write(delta.readBytes());delta.delete();continue }
                            val target=if(name.endsWith(".xdelta",true)) name.dropLast(7) else name
                            val entry=iso.files.getValue(target);progress("Patching $target")
                            val replacement=if(name.endsWith(".xdelta",true)) {
                                iso.extract(entry,original);decode(original,delta,patched,iso.sectors*2048);patched
                            } else delta
                            val lba=if((replacement.length()+2047)/2048<=(entry.size+2047)/2048)entry.lba else iso.free(replacement.length())
                            out.seek((lba-BASE)*2048);replacement.inputStream().use { input->val b=ByteArray(1024*1024);while(true) { check();val n=input.read(b);if(n<0)break;out.write(b,0,n) } }
                            val record=ByteArray(16);putBoth(record,0,lba);putBoth(record,8,replacement.length());out.seek(entry.record+2);out.write(record)
                            listOf(delta,original,patched).forEach { it.delete() }
                        }
                    }
                }
                val audioSkip=if(descriptor.name.endsWith(".cue",true))150*2352 else 0
                var audioHash=""
                for(i in 0..1) { progress("Preserving track ${i+1}");source[i].inputStream().use { input->
                    if(i==1 && audioSkip>0) { val silence=ByteArray(audioSkip);var read=0;while(read<silence.size) { check();val n=input.read(silence,read,silence.size-read);require(n>0);read+=n };require(silence.all { it==0.toByte() }) { "Non-silent CUE audio pregap; use desktop DCP to normalize it." } }
                    val digest=MessageDigest.getInstance("SHA-256")
                    File(output,if(i==0)"track01.bin" else "track02.raw").outputStream().use { out->val b=ByteArray(1024*1024);while(true) { check();val n=input.read(b);if(n<0)break;out.write(b,0,n);digest.update(b,0,n) } }
                    if(i==1)audioHash=digest.digest().joinToString("") { "%02x".format(it) }
                } }
                require(File(output,"track02.raw").length()==source[1].length()-audioSkip && hash(File(output,"track02.raw"),check)==audioHash && hash(File(output,"track01.bin"),check)==before[0]) { "Companion track verification failed." }
                File(output,"disc.gdi").writeText("3\n1 0 4 ${tracks[0].sector} track01.bin 0\n2 450 0 2352 track02.raw 0\n3 45000 4 2048 track03.iso 0\n")
                progress("Verifying rebuilt game files and boot data")
                Iso(high,2048,check).use { rebuilt->
                    require(rebuilt.tree()==archive.metadata.s("target_tree_sha256")) { "Rebuilt game files failed DCP verification." }
                    require(bootHash(rebuilt.boot())==archive.metadata.s("bootsector_invariant_sha256")) { "Rebuilt boot data failed verification." }
                }
                require(source.map { hash(it,check) }==before) { "Original disc changed during patching." }
                check()
                return buildJsonObject {
                    put("format","GDI");put("engine","android-native-iso-same-tree-v1");put("metadata",archive.metadata)
                    put("verified_game_tree_sha256",archive.metadata.s("target_tree_sha256"));put("bootsector_invariant_sha256",archive.metadata.s("bootsector_invariant_sha256"))
                    put("release_metadata_verified",true);put("audio_tracks_preserved",true);put("originals_unchanged",true)
                    put("audio_silent_pregap_removed_bytes",audioSkip);put("audio_sha256",audioHash)
                    put("output_files",buildJsonObject { for(f in output.listFiles()!!.sortedBy { it.name })put(f.name,buildJsonObject { put("bytes",f.length());put("sha256",hash(f,check)) }) })
                }.also { File(output,"DCP-VALIDATION.json").writeText(it.toString()) }
            }
        } catch(e:Exception) { if(created)output.deleteRecursively();throw e }
    }
}
