package org.retrotrans.core

import kotlinx.serialization.json.*
import org.junit.*
import org.junit.Assert.*
import java.io.File
import java.nio.file.Files
import java.util.concurrent.CancellationException

class DcpTest {
    private lateinit var root:File
    @Before fun setup() { root=Files.createTempDirectory("retro-trans-dcp-test-").toFile() }
    @After fun cleanup() { root.deleteRecursively() }
    private fun run(f:DcpFixture,meta:JsonObject?=null,check:()->Unit={}):JsonObject = Dcp.apply(f.descriptor,f.patch,File(root,"output"),File(root,"work").apply { mkdirs() },meta,check=check) { _,_,_,_->error("Unexpected delta") }
    @Test fun currentBundledCatalogHasBothBlackMatrixDiscProfiles() {
        val c=Catalog(javaClass.getResource("/live-catalog.json")!!.readText())
        assertEquals(setOf(1,2),c.dcpProfiles.filter { it.game=="black-matrix-ad-dreamcast" }
            .map { it.metadata.getValue("disc").jsonPrimitive.int }.toSet())
        assertTrue(c.edges.size>=246)
        c.checkUpdate(Catalog(c.raw))
    }
    @Test fun wholeFilePatchRelocatesExpandedFileAndVerifiesCompleteOutput() {
        val f=DcpFixture(File(root,"input"));f.writePatch();val before=f.root.listFiles()!!.associate { it.name to Dcp.hash(it) }
        val proof=run(f);assertEquals(JsonPrimitive(true),proof["originals_unchanged"])
        Dcp.Iso(File(root,"output/track03.iso"),2048).use { iso->
            assertEquals(f.tree(f.target),iso.tree());assertEquals(f.metadata["bootsector_invariant_sha256"]!!.jsonPrimitive.content,Dcp.bootHash(iso.boot()))
            val e=iso.files.getValue("ALPHA.DAT");assertNotEquals(45048L,e.lba);assertEquals(f.target.size.toLong(),e.size)
        }
        assertEquals(before,f.root.listFiles()!!.associate { it.name to Dcp.hash(it) })
        assertEquals(Dcp.hash(File(f.root,"audio.raw")),Dcp.hash(File(root,"output/track02.raw")))
        assertThrows(IllegalArgumentException::class.java) { run(f) }
    }
    @Test fun wrongTreeTargetAndBootMetadataNeverPublishOutput() {
        val f=DcpFixture(File(root,"input"))
        for(key in listOf("source_tree_sha256","target_tree_sha256","bootsector_invariant_sha256")) {
            f.writePatch(meta=JsonObject(f.metadata+mapOf(key to JsonPrimitive("0".repeat(64)))))
            assertThrows(IllegalArgumentException::class.java) { run(f) };assertFalse(File(root,"output").exists())
        }
        f.writePatch();assertThrows(IllegalArgumentException::class.java) { run(f,JsonObject(f.metadata+mapOf("disc" to JsonPrimitive(2)))) }
    }
    @Test fun unsafeAddedAndConflictingMembersAreRejected() {
        val f=DcpFixture(File(root,"input"))
        for(name in listOf("../escape","/absolute","bootsector/../escape","CON","ALPHA.DAT/child")) {
            f.writePatch(extra=name to byteArrayOf(1));assertTrue(runCatching { run(f) }.isFailure);assertFalse(File(root,"output").exists())
        }
        f.writePatch(extra="NEW.DAT" to byteArrayOf(2));assertThrows(IllegalArgumentException::class.java) { run(f) }
        f.writePatch(extra="alpha.dat" to byteArrayOf(2));assertThrows(IllegalArgumentException::class.java) { Dcp.inspect(f.patch) }
    }
    @Test fun cancellationTruncationAndUnsupportedLayoutsFailClosed() {
        val f=DcpFixture(File(root,"input"));f.writePatch()
        assertThrows(CancellationException::class.java) { run(f,check={throw CancellationException()}) };assertFalse(File(root,"output").exists())
        assertThrows(IllegalArgumentException::class.java) { Dcp.tracks("disc.gdi",f.descriptor.readText().replace("3 45000","3 45150")) }
        assertThrows(IllegalArgumentException::class.java) { Dcp.tracks("disc.cue","FILE \"x\" BINARY\nTRACK 01 AUDIO") }
        File(f.root,"data.iso").writeBytes(byteArrayOf(0));assertThrows(IllegalArgumentException::class.java) { run(f) }
    }
    @Test fun dcpCatalogRecognitionRemainsSeparateFromBinaryRoutes() {
        val f=DcpFixture(File(root,"input"));f.writePatch();val catalog=f.catalog();assertEquals(0,catalog.edges.size);assertEquals(1,catalog.dcpProfiles.size)
        val inputs=f.root.listFiles()!!.map { Input(it.path,it.name,it.length(),mapOf("sha256" to Dcp.hash(it))) }
        val descriptor=inputs.single { it.name=="disc.gdi" }
        val selected=DcpCatalog.recognize(catalog.dcpProfiles,descriptor,f.descriptor.readText(),inputs)!!
        assertNotNull(catalog.plan(selected).dcp);assertTrue(catalog.plan(selected).grouped);assertEquals(listOf("1.0"),catalog.versions(selected))
        assertNull(DcpCatalog.recognize(catalog.dcpProfiles,descriptor,f.descriptor.readText(),inputs.map { it.copy(hashes=mapOf("sha256" to "0".repeat(64))) }))
        assertNull(DcpCatalog.recognize(catalog.dcpProfiles,descriptor,f.descriptor.readText(),inputs.filter { it.name!="audio.raw" }))
        catalog.checkUpdate(Catalog(catalog.raw))
        val bad=Catalog(catalog.raw.replace(Dcp.hash(f.patch),"0".repeat(64)))
        assertThrows(IllegalArgumentException::class.java) { catalog.checkUpdate(bad) }
    }
    @Test fun optionalRealBlackMatrixDiscs() {
        val game=System.getenv("RETRO_TRANS_DCP_GAME_ROOT");Assume.assumeTrue(game!=null)
        val output=File(System.getenv("RETRO_TRANS_DCP_TEST_OUTPUT") ?: error("Explicit new test output required."));require(!output.exists());require(output.mkdirs())
        val engine=System.getenv("RETRO_TRANS_DCP_TEST_XDELTA") ?: error("Explicit desktop test decoder required.")
        for(disc in 1..2) {
            val source=File(game!!,"Black-Matrix Advanced (Japan) (Disc $disc).cue")
            val patch=File(game,"build/dcp-v0.9.0/ready/Black-Matrix-AD-Disc${disc}-English-v0.9.0.dcp")
            val work=File(output,"disc$disc-work").apply { mkdirs() }
            val proof=Dcp.apply(source,patch,File(output,"disc$disc-gdi"),work,progress={println("Disc $disc: $it")}) { original,delta,out,_->
                val process=ProcessBuilder(engine,"-d","-s",original.absolutePath,delta.absolutePath,out.absolutePath).redirectErrorStream(true).start()
                val log=process.inputStream.bufferedReader().readText();require(process.waitFor()==0) { log }
            }
            assertEquals(JsonPrimitive(true),proof["release_metadata_verified"])
        }
    }
}
