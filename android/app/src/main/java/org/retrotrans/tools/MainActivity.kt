package org.retrotrans.tools

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.text.style.TextOverflow
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlinx.serialization.json.*
import androidx.core.content.FileProvider

class MainActivity:ComponentActivity() {
    override fun onCreate(savedInstanceState:Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent { MaterialTheme { Surface(Modifier.fillMaxSize()) { Patcher() } } }
    }
}
@Composable fun Patcher(model:PatcherModel=viewModel()) {
    val context=LocalContext.current
    val locked=model.busy || model.serviceBusy
    var menu by remember { mutableStateOf(false) }
    var details by remember { mutableStateOf(false) }
    var ps3Confirm by remember { mutableStateOf(false) }
    var pickerKind by remember { mutableStateOf("source") }
    fun persist(uri:Uri,write:Boolean=false) {
        runCatching { context.contentResolver.takePersistableUriPermission(uri,Intent.FLAG_GRANT_READ_URI_PERMISSION or if(write)Intent.FLAG_GRANT_WRITE_URI_PERMISSION else 0) }
    }
    val files=rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri->if(uri!=null) { persist(uri); model.browse(uri,pickerKind) } }
    val folder=rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri->if(uri!=null) { persist(uri); model.scan(uri) } }
    val output=rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri->if(uri!=null) { persist(uri,true); model.setOutput(uri) } }
    val notification=rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {}
    LaunchedEffect(Unit) { if(Build.VERSION.SDK_INT>=33) notification.launch(Manifest.permission.POST_NOTIFICATIONS) }
    Column(Modifier.fillMaxSize().safeDrawingPadding()) {
        Row(Modifier.fillMaxWidth().padding(horizontal=12.dp),horizontalArrangement=Arrangement.SpaceBetween) {
            Text("Retro Trans ${BuildConfig.VERSION_NAME}",style=MaterialTheme.typography.titleMedium,modifier=Modifier.weight(1f).padding(vertical=14.dp))
            Box {
                TextButton(onClick={menu=true}) { Text("Menu") }
                DropdownMenu(expanded=menu,onDismissRequest={menu=false}) {
                    DropdownMenuItem(text={Text("Refresh catalog")},enabled=!locked,onClick={menu=false;model.refresh()})
                    DropdownMenuItem(text={Text("Check app updates")},enabled=!locked,onClick={menu=false;model.checkUpdates()})
                    DropdownMenuItem(text={Text("Clear downloaded cache")},enabled=!locked && !model.interrupted,onClick={menu=false;model.clearCache()})
                    DropdownMenuItem(text={Text("About / notices")},onClick={menu=false;model.dialog="Retro Trans ${BuildConfig.VERSION_NAME}\nNative Android test build.\n\nGame files stay on this device. Catalog-based Automatic verifies whole-file identities. Manual xdelta retains the patch's checksums.\n\nDCP is experimental: verified same-tree patches, three-track MODE1 CUE/GDI to GDI. CHD, new-file DCPs, save conversion and Vita PKG rebuilding are not included.\n\n"+context.assets.open("NOTICES.txt").bufferedReader().use { it.readText() }})
                }
            }
        }
        Text(model.catalogStatus,style=MaterialTheme.typography.bodySmall,modifier=Modifier.padding(horizontal=12.dp))
        TabRow(selectedTabIndex=model.tab) {
            listOf("Automatic","Apply xdelta","DCP").forEachIndexed { i,name->
                Tab(selected=model.tab==i,enabled=!locked,onClick={model.tab=i; model.source=null; model.patch=null; model.selections=emptyList();model.selected=0;model.outputName=""},text={Text(name)})
            }
        }
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(12.dp),verticalArrangement=Arrangement.spacedBy(8.dp)) {
            FlowRow(horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                if(model.tab!=2) OutlinedButton(enabled=!locked,onClick={pickerKind="source";files.launch(arrayOf("*/*"))}) { Text(if(model.tab==0) "Browse file" else "Original binary") }
                if(model.tab!=1) {
                    OutlinedButton(enabled=!locked,onClick={folder.launch(null)}) { Text("Folder") }
                    TextButton(enabled=!locked,onClick={model.scan()}) { Text("Scan") }
                }
            }
            model.source?.let { Text(it.name,style=MaterialTheme.typography.bodySmall) }
            if(model.tab==0) {
                Choice("Recognized file / disc set",model.selections.map { it.label },model.selected,!locked) { model.selected=it;model.target="Latest";model.suggestName() }
                val versions=listOf("Latest","Next version only")+(model.choice?.let { model.catalog.versions(it) } ?: emptyList())
                Choice("Target",versions,versions.indexOf(model.target).coerceAtLeast(0),!locked) { model.target=versions[it];model.suggestName() }
                Text(model.routeError(),style=MaterialTheme.typography.bodyMedium)
                TextButton(enabled=model.route()!=null,onClick={details=true}) { Text("Route details") }
            } else if(model.tab==2) {
                Choice("Original disc set",model.selections.map { it.label },model.selected,!locked) { model.selected=it;model.suggestName() }
                OutlinedButton(enabled=!locked,onClick={pickerKind="patch";files.launch(arrayOf("*/*"))}) { Text("Choose local DCP") }
                Text(model.patch?.name ?: "No DCP selected",style=MaterialTheme.typography.bodySmall)
                Text("Experimental: three-track MODE1 CUE/GDI → GDI. Requires verification metadata; no CHD or new-file patches. Originals stay unchanged.",style=MaterialTheme.typography.bodySmall)
            } else {
                OutlinedButton(enabled=!locked,onClick={pickerKind="patch";files.launch(arrayOf("*/*"))}) { Text("Choose local xdelta") }
                Text(model.patch?.name ?: "No patch selected",style=MaterialTheme.typography.bodySmall)
                Text("Uses xdelta checksums. No catalog match required.",style=MaterialTheme.typography.bodySmall)
            }
            HorizontalDivider()
            OutlinedButton(enabled=!locked,onClick={output.launch(model.tree?.let { android.provider.DocumentsContract.buildDocumentUriUsingTree(it,android.provider.DocumentsContract.getTreeDocumentId(it)) })}) { Text(if(model.tree==null)"Choose output folder" else "Change output folder") }
            model.tree?.let { Text(Uri.decode(it.lastPathSegment ?: "Selected folder"),style=MaterialTheme.typography.bodySmall) }
            OutlinedTextField(value=model.outputName,onValueChange={model.outputName=it},enabled=!locked,
                label={Text(if(model.tab==2 || (model.tab==0 && model.route()?.grouped==true)) "New output folder name" else "New output filename")},singleLine=true,modifier=Modifier.fillMaxWidth())
            if(model.interrupted) Row(horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                OutlinedButton(enabled=!locked,onClick={model.resume()}) { Text("Resume job") }
                TextButton(enabled=!locked,onClick={model.discard()}) { Text("Discard job") }
            }
        }
        Column(Modifier.fillMaxWidth().padding(12.dp),verticalArrangement=Arrangement.spacedBy(6.dp)) {
            Text(model.status,style=MaterialTheme.typography.bodySmall,maxLines=4,overflow=TextOverflow.Ellipsis)
            if(model.status.length>160) TextButton(onClick={model.dialog=model.status}) { Text("Status details") }
            if(locked) {
                model.fraction?.let { LinearProgressIndicator(progress={it.toFloat()},modifier=Modifier.fillMaxWidth()) }
                    ?: LinearProgressIndicator(modifier=Modifier.fillMaxWidth())
            }
            Row(horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                Button(enabled=!locked && !model.interrupted && model.tree!=null && model.outputName.isNotBlank() &&
                    (if(model.tab==0) model.route()?.let { it.dcp!=null || it.edges.isNotEmpty() }==true else if(model.tab==2) model.choice?.dcp!=null && model.patch!=null else model.source!=null && model.patch!=null),
                    onClick={
                        if(model.tab==1 || model.route()?.parts?.any { it.source.platform.contains("ps3",true) || it.source.platform.contains("playstation 3",true) }==true) ps3Confirm=true
                        else model.start()
                    },modifier=Modifier.weight(1f)) { Text("Patch") }
                OutlinedButton(enabled=locked,onClick={model.cancel()}) { Text("Cancel") }
            }
        }
    }
    if(details) Message("Patch route",model.route()?.details ?: "No route.") { details=false }
    model.dialog?.let { Message("Retro Trans",it) { model.dialog=null } }
    model.updateCandidate?.let { candidate->AlertDialog(onDismissRequest={model.updateCandidate=null},title={Text("Android update")},
        text={Text("Download version ${candidate.string("version_name")}? Android will ask you to confirm installation.")},
        confirmButton={TextButton(onClick={model.downloadUpdate()}) { Text("Download") }},dismissButton={TextButton(onClick={model.updateCandidate=null}) { Text("Later") }}) }
    model.installFile?.let { file->AlertDialog(onDismissRequest={model.installFile=null},title={Text("Update ready")},text={Text("The APK and signing identity were checked. Continue to Android's installer.")},
        confirmButton={TextButton(onClick={
            if(!context.packageManager.canRequestPackageInstalls()) {
                context.startActivity(Intent(android.provider.Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,Uri.parse("package:"+context.packageName)))
            } else {
                val uri=FileProvider.getUriForFile(context,context.packageName+".files",file)
                context.startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri,"application/vnd.android.package-archive").addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION))
                model.installFile=null
            }
        }) { Text("Install") }},dismissButton={TextButton(onClick={model.installFile=null}) { Text("Later") }}) }
    if(ps3Confirm) AlertDialog(onDismissRequest={ps3Confirm=false},title={Text("Before patching")},text={Text(PS3_WARNING)},
        confirmButton={TextButton(onClick={ps3Confirm=false;model.start()}) { Text("Continue") }},dismissButton={TextButton(onClick={ps3Confirm=false}) { Text("Cancel") }})
    model.importPending?.let { (doc,_)->AlertDialog(onDismissRequest={model.importPending=null},title={Text("Import a local copy?")},
        text={Text("This provider cannot be used directly. Copy ${doc.name} into the app once, then reuse it for patching? It needs ${(doc.size ?: 0)/(1024*1024)} MB plus patching space.")},
        confirmButton={TextButton(onClick={model.import()}) { Text("Import") }},dismissButton={TextButton(onClick={model.importPending=null}) { Text("Cancel") }}) }
}
@Composable fun Choice(label:String,options:List<String>,index:Int,enabled:Boolean,choose:(Int)->Unit) {
    var expanded by remember { mutableStateOf(false) }
    Box(Modifier.fillMaxWidth()) {
        OutlinedButton(onClick={expanded=true},enabled=enabled && options.isNotEmpty(),modifier=Modifier.fillMaxWidth()) {
            Column(Modifier.fillMaxWidth()) { Text(label,style=MaterialTheme.typography.labelSmall);Text(options.getOrNull(index) ?: "None") }
        }
        DropdownMenu(expanded=expanded,onDismissRequest={expanded=false}) {
            options.forEachIndexed { i,text->DropdownMenuItem(text={Text(text)},onClick={expanded=false;choose(i)}) }
        }
    }
}
@Composable fun Message(title:String,message:String,close:()->Unit) {
    AlertDialog(onDismissRequest=close,title={Text(title)},text={Text(message,modifier=Modifier.verticalScroll(rememberScrollState()))},confirmButton={TextButton(onClick=close) { Text("OK") }})
}
