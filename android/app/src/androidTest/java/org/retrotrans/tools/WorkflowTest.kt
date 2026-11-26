package org.retrotrans.tools

import android.net.Uri
import androidx.lifecycle.ViewModelProvider
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import org.junit.*
import org.junit.Assert.*
import org.junit.runner.RunWith
import java.io.File
import java.util.concurrent.TimeUnit
import kotlinx.serialization.json.*
import org.retrotrans.core.Catalog

@RunWith(AndroidJUnit4::class)
class WorkflowTest {
    private val instrumentation=InstrumentationRegistry.getInstrumentation()
    private val context=instrumentation.targetContext
    private val device=UiDevice.getInstance(instrumentation)
    private val tree=Uri.parse("content://com.android.externalstorage.documents/tree/primary%3ADocuments%2FRetroTransAndroidTest")
    private lateinit var root:File
    @Before fun setup() {
        device.executeShellCommand("mkdir -p /sdcard/Documents/RetroTransAndroidTest")
        if(android.os.Build.VERSION.SDK_INT>=33) device.executeShellCommand("pm grant ${context.packageName} android.permission.POST_NOTIFICATIONS")
        root=File(context.filesDir,"workflow-fixtures").apply { mkdirs() }
        for(name in listOf("source.bin","modified.bin","lzma.xdelta")) instrumentation.context.assets.open(name).use { input->File(root,name).outputStream().use { input.copyTo(it) } }
        context.getSharedPreferences("settings",0).edit().clear().putString("output",tree.toString()).commit()
        File(context.filesDir,"job").deleteRecursively()
    }
    @After fun cleanup() { root.deleteRecursively() }
    private fun waitFor(timeout:Long=20000,block:()->Boolean) {
        val end=System.currentTimeMillis()+timeout
        while(System.currentTimeMillis()<end) { if(block())return;Thread.sleep(100) }
        error("Timed out waiting for app state")
    }
    private fun chooseFolder() {
        device.wait(Until.findObject(By.text("Change output folder")),10000)!!.click()
        device.waitForIdle()
        // Providers may ignore EXTRA_INITIAL_URI until the first grant.
        device.findObject(By.text("Documents"))?.click()
        device.wait(Until.findObject(By.text("RetroTransAndroidTest")),2000)?.click()
        device.waitForIdle()
        val use=device.wait(Until.findObject(By.text(java.util.regex.Pattern.compile("(?i)use this folder"))),10000)!!
        assertTrue("Choose the test child folder, not a restricted storage root",use.isEnabled)
        use.click()
        device.wait(Until.findObject(By.text(java.util.regex.Pattern.compile("(?i)allow"))),5000)?.click()
        waitFor { runCatching { Storage(context).folder(tree).canWrite() }.getOrDefault(false) }
    }
    @Test fun manualPatchThroughUiExportsVerifiedCopyAndRefusesOverwrite() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario->
            var model:PatcherModel?=null
            scenario.onActivity { model=ViewModelProvider(it)[PatcherModel::class.java];model!!.tab=1 }
            chooseFolder()
            scenario.onActivity { model!!.browse(Uri.fromFile(File(root,"source.bin")),"source") }
            waitFor { model?.busy==false && model?.source!=null }
            scenario.onActivity { model!!.browse(Uri.fromFile(File(root,"lzma.xdelta")),"patch") }
            waitFor { model?.busy==false && model?.patch!=null }
            val name="manual-${System.nanoTime()}.bin"
            scenario.onActivity { model!!.outputName=name }
            device.wait(Until.findObject(By.text("Patch")),5000)!!.click()
            device.wait(Until.findObject(By.text("Continue")),5000)!!.click()
            waitFor(30000) { readJson(File(context.filesDir,"job/state.json"))?.string("status") in listOf("complete","interrupted") }
            val state=readJson(File(context.filesDir,"job/state.json"))!!
            assertEquals(state.toString(),"complete",state.string("status"))
            val done=readJson(File(context.filesDir,"job/complete.json"))!!
            val uri=Uri.parse(done.string("uri")); val storage=Storage(context)
            assertEquals(fileHash(File(root,"modified.bin")),storage.hash(storage.describe(uri),setOf("sha256"),Control()).hashes["sha256"])
            assertThrows(IllegalArgumentException::class.java) { storage.prepareOutput(tree,name) }
            val screenshot=instrumentation.uiAutomation.takeScreenshot()
            File(context.filesDir,"workflow-screen.png").outputStream().use { screenshot.compress(android.graphics.Bitmap.CompressFormat.PNG,100,it) }
            android.provider.DocumentsContract.deleteDocument(context.contentResolver,uri)
        }
    }
    @Test fun exportCancellationCleansOnlyOwnedDocuments() {
        // Reuses the explicit picker grant when the UI round trip has run; otherwise
        // the test must establish it rather than granting broad storage permission.
        ActivityScenario.launch(MainActivity::class.java).use {
            chooseFolder()
            val storage=Storage(context);waitFor { runCatching { storage.folder(tree).canWrite() }.getOrDefault(false) }
            val name="cancel-${System.nanoTime()}"
            val job=File(context.filesDir,"export-test").apply { mkdirs() }
            val control=Control(); control.cancelled.set(true)
            assertThrows(java.util.concurrent.CancellationException::class.java) {
                storage.export(listOf("a.bin" to File(root,"source.bin")),tree,name,true,job,control)
            }
            assertNull(storage.folder(tree).findFile(name))
            assertFalse(storage.folder(tree).listFiles().any { it.name?.endsWith(".partial")==true })
            assertTrue(File(root,"source.bin").exists());job.deleteRecursively()
        }
    }
    @Test fun automaticMultiFileChainAndOfflineCacheRoundTrip() {
        ActivityScenario.launch(MainActivity::class.java).use {
            chooseFolder()
            val catalog=Catalog(instrumentation.context.assets.open("fixture-catalog.json").bufferedReader().use { it.readText() })
            for(name in listOf("second.bin","second-target.bin","final.bin","disc.cue")) {
                instrumentation.context.assets.open(name).use { input->File(root,name).outputStream().use { input.copyTo(it) } }
            }
            val storage=Storage(context)
            val docs=listOf("source.bin","second.bin","disc.cue").map { name->storage.describe(Uri.fromFile(File(root,name))) }
            val selection=catalog.selections(storage.identify(docs,catalog,Control())).single()
            val route=catalog.plan(selection)
            assertEquals("1.1",route.targetVersion);assertEquals(3,route.edges.size)
            val cache=File(context.filesDir,"patch-cache").apply { mkdirs() }
            for(e in route.edges) instrumentation.context.assets.open(e.asset.name).use { input->File(cache,e.asset.sha256).outputStream().use { input.copyTo(it) } }
            val job=File(context.filesDir,"job").apply { mkdirs() }
            atomicWrite(File(job,"catalog.json"),catalog.raw)
            val name="automatic-${System.nanoTime()}"
            atomicWrite(File(job,"request.json"),automaticRequest(route,tree.toString(),name).toString())
            androidx.core.content.ContextCompat.startForegroundService(context,android.content.Intent(context,PatchService::class.java))
            waitFor(30000) { readJson(File(job,"state.json"))?.string("status") in listOf("complete","interrupted") }
            assertEquals(readJson(File(job,"state.json")).toString(),"complete",readJson(File(job,"state.json"))!!.string("status"))
            val done=Uri.parse(readJson(File(job,"complete.json"))!!.string("uri"))
            val docId=android.provider.DocumentsContract.getDocumentId(done)
            for((name,expected) in listOf("track01.bin" to "final.bin","track02.bin" to "second-target.bin","disc.cue" to "disc.cue")) {
                val child=android.provider.DocumentsContract.buildDocumentUriUsingTree(tree,"$docId/$name")
                val actual=storage.hash(storage.describe(child),setOf("sha256"),Control())
                assertEquals(fileHash(File(root,expected)),actual.hashes["sha256"])
            }
            assertFalse(File(job,"work").exists())
            android.provider.DocumentsContract.deleteDocument(context.contentResolver,done)
        }
    }
    @Test fun dcpWorkerExportsVerifiedFolderAndRefusesOverwrite() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario->
            chooseFolder()
            val fixture=org.retrotrans.core.DcpFixture(File(root,"dcp-fixture"));fixture.writePatch(true)
            val storage=Storage(context);val catalog=fixture.catalog()
            val docs=listOf("disc.gdi","low.bin","audio.raw","data.iso").map { storage.describe(Uri.fromFile(File(fixture.root,it))) }
            val selections=AndroidDcp.selections(storage,docs,storage.identify(docs,catalog,Control()),catalog,Control(),true)
            var model:PatcherModel?=null
            scenario.onActivity { model=ViewModelProvider(it)[PatcherModel::class.java];model!!.tab=2;model!!.selections=selections;model!!.selected=0;model!!.patch=storage.describe(Uri.fromFile(fixture.patch));model!!.outputName="dcp-${System.nanoTime()}" }
            val name=model!!.outputName
            // Exercise the real DCP tab button and background worker, not only the kernel.
            device.wait(Until.findObject(By.text("Patch")),5000)!!.click()
            waitFor(45000) { readJson(File(context.filesDir,"job/state.json"))?.string("status") in listOf("complete","interrupted") }
            val state=readJson(File(context.filesDir,"job/state.json"))!!;assertEquals(state.toString(),"complete",state.string("status"))
            val done=Uri.parse(readJson(File(context.filesDir,"job/complete.json"))!!.string("uri"))
            try {
                val id=android.provider.DocumentsContract.getDocumentId(done)
                val proof=android.provider.DocumentsContract.buildDocumentUriUsingTree(tree,"$id/DCP-VALIDATION.json")
                val data=storage.open(proof).bufferedReader().use { Json.parseToJsonElement(it.readText()).jsonObject }
                assertEquals(fixture.metadata["target_tree_sha256"],data["verified_game_tree_sha256"])
                assertThrows(IllegalArgumentException::class.java) { storage.prepareOutput(tree,name) }
                assertTrue(File(fixture.root,"data.iso").exists());assertFalse(File(context.filesDir,"job/work").exists())
            } finally { android.provider.DocumentsContract.deleteDocument(context.contentResolver,done) }
        }
    }
}
