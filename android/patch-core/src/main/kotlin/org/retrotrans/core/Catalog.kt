package org.retrotrans.core

import kotlinx.serialization.json.*
import java.net.URLEncoder
import java.util.Locale

fun safeName(name: String): String {
    require(name.isNotEmpty() && name.length <= 200 && name !in listOf(".", "..") &&
        !name.endsWith('.') && !name.endsWith(' ') && name.none { it < ' ' || it in "<>:\"/\\|?*" }) { "Unsafe filename." }
    require(!Regex("(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])").matches(name.substringBefore('.'))) { "Reserved filename." }
    return name
}
fun version(raw: String): List<Long> {
    if (raw == "original") return listOf(-1L, 0, 0, 0)
    require(Regex("v?\\d+(?:\\.\\d+){1,3}").matches(raw)) { "Unsupported version: $raw" }
    return raw.removePrefix("v").split('.').map { it.toLong() }.let { it + List(4-it.size) { 0L } }
}
fun compareVersions(a: String, b: String): Int {
    val x=version(a); val y=version(b)
    return x.indices.firstNotNullOfOrNull { (x[it].compareTo(y[it])).takeIf { n -> n != 0 } } ?: 0
}
private fun clean(v: String): String { version(v); return v.removePrefix("v") }
private fun JsonObject.text(k: String): String {
    val p = this[k] as? JsonPrimitive
    require(p != null && p.isString && p.content.isNotBlank() && p.content.length <= 200 && p.content.none { it < ' ' }) { "Invalid $k." }
    return p.content
}
private fun JsonObject.number(k: String, nullable: Boolean = false): Long? {
    val p=this[k]
    if (nullable && (p==null || p==JsonNull)) return null
    require(p is JsonPrimitive && !p.isString) { "Missing size: $k" }
    val n=p.longOrNull
    require(n!=null && n in 0..(1L shl 44)) { "Invalid size: $k" }
    return n
}
private fun JsonObject.rows(k:String): List<JsonObject> {
    val a=this[k] as? JsonArray ?: error("Missing $k.")
    return a.map { it as? JsonObject ?: error("Invalid $k record.") }
}
private fun hash(raw:String, length:Int):String {
    require(Regex("[a-fA-F0-9]{$length}").matches(raw)) { "Invalid hash." }; return raw.lowercase(Locale.ROOT)
}
private fun quote(s:String) = URLEncoder.encode(s, "UTF-8").replace("+", "%20").replace("%7E", "~")

data class Identity(val size:Long?, val hashes:Map<String,String>) {
    fun matches(size:Long, hashes:Map<String,String>):Boolean {
        val algorithm=if ("sha256" in this.hashes) "sha256" else "sha1"
        return (this.size==null || size==this.size) && hashes[algorithm]==this.hashes[algorithm]
    }
}
data class Key(val game:String, val edition:String, val language:String, val version:String) {
    val family get() = listOf(game, edition, language)
}
data class Binary(val key:Key, val gameName:String, val platform:String, val format:String, val identity:Identity) {
    val label get() = "$gameName / ${key.edition} / ${key.language} / ${key.version}"
}
data class Asset(val name:String, val url:String, val size:Long, val sha256:String)
data class Edge(val source:Key, val target:Key, val asset:Asset)
data class Component(val name:String, val target:Key)
data class CopyFile(val name:String, val size:Long, val sha256:String)
data class Solution(val key:Key, val gameName:String, val name:String, val edition:String,
    val components:List<Component>, val copies:List<CopyFile>)
data class Input(val uri:String, val name:String, val size:Long, val hashes:Map<String,String>)
data class Part(val name:String, val input:Input, val source:Binary, val target:Binary, val edges:List<Edge>) {
    val summary get() = (listOf(source.key.version) + edges.map { it.target.version }).joinToString(" → ")
}
data class Selection(val label:String, val source:Binary?=null, val input:Input?=null,
    val solution:Solution?=null, val found:Map<String,Pair<Input,Binary>> = emptyMap(),
    val problems:List<String> = emptyList(), val folder:List<Input> = emptyList(), val dcp:DcpSelection?=null)
data class Route(val targetVersion:String, val latestVersion:String, val latestReachable:Boolean,
    val parts:List<Part>, val copies:List<Pair<Input,CopyFile>> = emptyList(), val grouped:Boolean=false, val dcp:DcpProfile?=null) {
    val edges get() = parts.flatMap { it.edges }
    val summary get() = (if(dcp!=null) "DCP → $targetVersion · GDI output"+(if(dcp.prerelease) " (experimental release)" else "") else if (grouped) "${parts.size} files → $targetVersion" else parts.single().summary) +
        if(targetVersion!=latestVersion) " (latest published: $latestVersion${if (!latestReachable) "; no compatible route" else ""})" else ""
    val details get() = summary + (dcp?.let { "\n\n${it.asset.name}\nAll original tracks, complete game-file tree, boot data and CD audio are verified. Experimental three-track, same-tree DCP support. No CHD conversion." } ?: "") + "\n\n" + parts.joinToString("\n\n") { "${it.name}: ${it.summary}\n" + it.edges.joinToString("\n") { e->e.asset.name } } +
        if(copies.isEmpty()) "" else "\n\nUnchanged: " + copies.joinToString { it.second.name }
}

class Catalog(val raw:String) {
    val dcpProfiles:List<DcpProfile>
    val nodes=linkedMapOf<Key,Binary>()
    val edges=mutableListOf<Edge>()
    val withdrawn=mutableListOf<Edge>()
    val solutions=linkedMapOf<Key,Solution>()
    val activeSolutions=mutableSetOf<Key>()
    val groupedFamilies=mutableSetOf<List<String>>()
    // Preserve and validate v3 identities, but assembling PC combined sources
    // remains a desktop feature. Other routes (including upgrades) stay usable.
    val combinedSources=linkedMapOf<Key,List<CopyFile>>()
    val summary get() = "${edges.size} patches" + if(combinedSources.isEmpty()) "" else
        " · ${combinedSources.size} combined sources require desktop"
    val available:Set<Key>
    init {
        require(raw.toByteArray().size <= 4*1024*1024) { "Catalog is too large." }
        val data=Json.parseToJsonElement(raw).jsonObject
        dcpProfiles=DcpCatalog.load(data)
        require(data.number("schema_version")==1L) { "Unsupported catalog schema." }
        val releases=data.rows("releases")
        val retired=if("withdrawn_releases" in data) data.rows("withdrawn_releases") else emptyList()
        val seen=mutableSetOf<Triple<Boolean,String,String>>()
        val urls=mutableSetOf<String>()
        val rows=mutableListOf<Pair<Boolean,JsonObject>>()
        for ((isRetired,list) in listOf(false to releases,true to retired)) for (release in list) {
            if(isRetired) release.text("reason")
            val repo=release.text("repo"); val tag=release.text("tag")
            require(Regex("retro-trans/[A-Za-z0-9_.-]+").matches(repo)) { "Unsupported publisher." }
            require(seen.add(Triple(isRetired,repo,tag))) { "Duplicate release." }
            val legacy=(release["legacy"] as? JsonPrimitive)?.booleanOrNull==true
            val m=release["manifest"]!!.jsonObject
            val schema=if (legacy && "schema_version" !in m) 1L else m.number("schema_version")
            require(schema in listOf(1L,2L,3L) && !(legacy && schema!=1L)) { "Unsupported manifest." }
            if(schema==3L) {
                require("solutions" !in m && compareVersions(m.text("min_app_version"),"0.5.23")>=0 &&
                    compareVersions(m.text("min_app_version"),"0.5.24")<=0) { "Unsupported combined-source release." }
                require(m.rows("patches").any { "combined_source" in it }) { "Schema 3 requires combined sources." }
            }
            val game=m.text("game_id"); val gameName=m.text("game_name"); val platform=m.text("platform")
            require(Regex("[a-z0-9][a-z0-9-]*").matches(game)) { "Invalid game ID." }
            val targetVersion=clean(m.text("version"))
            require(targetVersion!="original" && targetVersion==clean(tag)) { "Release version mismatch." }
            if(!legacy) hash(m.text("source_commit"),40)
            val patches=m.rows("patches"); require(patches.isNotEmpty()) { "Empty release." }
            val names=mutableSetOf<String>()
            for(p in patches) {
                val name=safeName(p.text("patch"))
                require(name.lowercase().endsWith(".xdelta") || name.lowercase().endsWith(".vcdiff")) { "Invalid patch extension." }
                require(names.add(name.lowercase(Locale.ROOT))) { "Duplicate patch filename." }
                val edition=p.text("edition"); val language=p.text("language")
                val version=clean(p.text("source_version"))
                val keys=mutableListOf<Key>()
                for(side in listOf("source","target")) {
                    val format=p.text(side+"_format")
                    require(Regex("[a-z0-9]{1,12}").matches(format)) { "Invalid binary format." }
                    val hashes=mutableMapOf<String,String>()
                    for ((algo,length) in listOf("sha256" to 64,"sha1" to 40)) {
                        val h=p[side+"_"+algo]
                        if(h!=null && h!=JsonNull) hashes[algo]=hash(p.text(side+"_"+algo),length)
                    }
                    require("sha256" in hashes || (legacy && "sha1" in hashes)) { "Missing binary hash." }
                    val key=Key(game,edition,language,if(side=="source") version else targetVersion)
                    val candidate=Binary(key,if("game_name" in p) p.text("game_name") else gameName,
                        if("platform" in p) p.text("platform") else platform,format,Identity(p.number(side+"_bytes",legacy),hashes))
                    val old=nodes[key]
                    if(old==null) nodes[key]=candidate else {
                        val common=old.identity.hashes.keys.intersect(hashes.keys)
                        require(old.platform==candidate.platform && old.format==format && common.isNotEmpty() &&
                            common.all { old.identity.hashes[it]==hashes[it] } &&
                            (old.identity.size==null || candidate.identity.size==null || old.identity.size==candidate.identity.size)) { "Conflicting binary identity." }
                        nodes[key]=old.copy(identity=Identity(old.identity.size ?: candidate.identity.size,old.identity.hashes+hashes))
                    }
                    keys+=key
                }
                p["combined_source"]?.let { value->
                    require(schema==3L) { "Combined sources require schema 3." }
                    val combined=value.jsonObject
                    require(combined.keys==setOf("method","files") && combined.text("method")=="concat") { "Unsupported source assembly." }
                    val seenParts=mutableSetOf<String>()
                    val parts=combined.rows("files").map { f->
                        require(f.keys==setOf("name","bytes","sha256")) { "Invalid combined component." }
                        val filename=safeName(f.text("name"))
                        require(seenParts.add(filename.lowercase(Locale.ROOT))) { "Duplicate combined component." }
                        CopyFile(filename,f.number("bytes")!!,hash(f.text("sha256"),64))
                    }
                    require(parts.size in 2..16 && parts.sumOf { it.size }==p.number("source_bytes")) { "Combined source size mismatch." }
                    require(combinedSources.putIfAbsent(keys[0],parts)?.let { it==parts }!=false) { "Conflicting combined source." }
                }
                val url=release["assets"]!!.jsonObject[name]!!.jsonPrimitive.content
                require(url=="https://github.com/$repo/releases/download/${quote(tag)}/${quote(name)}" && urls.add(url)) { "Invalid or duplicate asset URL." }
                val edge=Edge(keys[0],keys[1],Asset(name,url,p.number("patch_bytes")!!,hash(p.text("patch_sha256"),64)))
                (if(isRetired) withdrawn else edges).add(edge)
            }
            if(schema!=2L) require("solutions" !in m) { "Solutions require schema 2." }
            else { require(m.rows("solutions").isNotEmpty()); rows+=isRetired to m }
        }
        available=edges.flatMap { listOf(it.source,it.target) }.toSet()
        val activeTargets=edges.map { it.target }.toSet()
        for((isRetired,m) in rows) {
            val seenSolutions=mutableSetOf<Pair<String,String>>()
            for(s in m.rows("solutions")) {
                val id=s.text("id"); val language=s.text("language")
                require(Regex("[a-z0-9][a-z0-9-]{0,99}").matches(id) && seenSolutions.add(id to language)) { "Duplicate or invalid solution." }
                val key=Key(m.text("game_id"),id,language,clean(m.text("version")))
                val names=mutableSetOf<String>(); val editions=mutableSetOf<String>()
                val components=s.rows("files").map {
                    val name=safeName(it.text("output_name")); val edition=it.text("edition")
                    require(names.add(name.lowercase(Locale.ROOT)) && editions.add(edition)) { "Duplicate component." }
                    val target=Key(key.game,edition,language,key.version)
                    require(m.rows("patches").any { p->p.text("edition")==edition && p.text("language")==language }) { "Missing solution component." }
                    require(target in nodes)
                    Component(name,target)
                }
                require(components.size>=2) { "Incomplete multi-file solution." }
                val copies=(if("copy_files" in s) s.rows("copy_files") else emptyList()).map {
                    val name=safeName(it.text("name"))
                    require("source" !in it && names.add(name.lowercase(Locale.ROOT))) { "Unsafe copy record." }
                    CopyFile(name,it.number("bytes")!!,hash(it.text("sha256"),64))
                }
                val solution=Solution(key,m.text("game_name"),s.text("name"),s.text("edition"),components,copies)
                require(solutions[key]==null || solutions[key]==solution) { "Conflicting solution." }
                solutions[key]=solution
                groupedFamilies.addAll(components.map { it.target.family })
                if(!isRetired && components.all { it.target in activeTargets }) activeSolutions+=key
            }
        }
        solutions.values.groupBy { it.key.family }.values.forEach { family ->
            require(family.map { s->s.components.map { it.target.family }.toSet() }.distinct().size==1) { "Changed solution components." }
        }
    }

    fun checkUpdate(next:Catalog) {
        DcpCatalog.checkUpdate(dcpProfiles,next.dcpProfiles)
        val old=(edges+withdrawn).associateBy { it.asset.url }; val new=(next.edges+next.withdrawn).associateBy { it.asset.url }
        require(withdrawn.all { it in next.withdrawn } && old.all { new[it.key]==it.value }) { "Catalog changed or reactivated a published patch." }
        require(nodes.all { (k,v)->next.nodes[k]?.let { n->n.platform==v.platform && n.format==v.format &&
            (v.identity.size==null || n.identity.size==v.identity.size) && v.identity.hashes.all { n.identity.hashes[it.key]==it.value } }==true }) { "Catalog changed a binary identity." }
        require(solutions.all { next.solutions[it.key]==it.value }) { "Catalog changed a solution." }
        require(combinedSources.all { next.combinedSources[it.key]==it.value }) { "Catalog changed a combined source." }
    }
    fun candidates(size:Long?) = nodes.values.filter { it.key in available && it.key !in combinedSources && (size==null || it.identity.size==null || it.identity.size==size) }
    fun recognize(input:Input) = candidates(input.size).filter { it.identity.matches(input.size,input.hashes) }
    fun selections(inputs:List<Input>):List<Selection> {
        val matched=inputs.flatMap { f->recognize(f).map { f to it } }
        val singles=matched.filter { it.second.key.family !in groupedFamilies }.map { (f,n)->Selection("${f.name} — ${n.label}",n,f) }
        val groups=solutions.values.filter { it.key in activeSolutions }.groupBy { it.key.family }.values.mapNotNull { versions ->
            val s=versions.maxWith { a,b->compareVersions(a.key.version,b.key.version) }
            if(s.components.none { c->matched.any { it.second.key.family==c.target.family } }) return@mapNotNull null
            val found=mutableMapOf<String,Pair<Input,Binary>>(); val problems=mutableListOf<String>()
            for(c in s.components) {
                val matches=matched.filter { it.second.key.family==c.target.family }.groupBy { it.first.uri }
                if(matches.size!=1) problems+=(if(matches.isEmpty()) "Missing: " else "Multiple matches: ")+c.name
                else found[c.target.edition]=matches.values.single().maxWith { a,b->compareVersions(a.second.key.version,b.second.key.version) }
            }
            val versionsFound=found.values.map { it.second.key.version }.distinct().joinToString(", ")
            Selection("${s.gameName} / ${s.edition} / $versionsFound"+(if(problems.isEmpty()) "" else " (incomplete)"),
                solution=s,found=found,problems=problems,folder=inputs)
        }
        return groups+singles
    }
    fun versions(selection:Selection):List<String> = if(selection.dcp!=null) selection.dcp.profiles.map { it.version }.distinct().sortedWith { a,b->compareVersions(b,a) }
        else if(selection.source!=null) binaryVersions(selection.source).map { it.key.version }
        else solutions.values.filter { it.key in activeSolutions && it.key.family==selection.solution!!.key.family }
            .map { it.key.version }.sortedWith { a,b->compareVersions(b,a) }
    private fun binaryVersions(n:Binary) = nodes.values.filter { it.key.family==n.key.family && it.key.version!="original" && edges.any { e->e.target==it.key } }
        .sortedWith { a,b->compareVersions(b.key.version,a.key.version) }
    private fun paths(source:Key):Map<Key,List<Edge>> {
        val best=mutableMapOf(source to emptyList<Edge>()); val todo=mutableSetOf(source)
        fun cost(p:List<Edge>)=p.size to p.sumOf { it.asset.size }
        fun order(p:List<Edge>,q:List<Edge>) = compareValuesBy(cost(p),cost(q),{it.first},{it.second})
        while(todo.isNotEmpty()) {
            val key=todo.minWith { a,b->order(best.getValue(a),best.getValue(b)) }; todo-=key
            for(e in edges.sortedBy { it.asset.url }.filter { it.source==key && it.target.family==source.family }) {
                val route=best.getValue(key)+e; val old=best[e.target]
                if(old==null || order(route,old)<0) { best[e.target]=route; todo+=e.target }
            }
        }
        return best
    }
    fun plan(selection:Selection,target:String="Latest"):Route {
        require(selection.problems.isEmpty()) { selection.problems.joinToString("; ") }
        selection.dcp?.let { source->val p=DcpCatalog.plan(source,target);return Route(p.version,versions(selection).first(),true,emptyList(),grouped=true,dcp=p) }
        if(selection.source!=null) {
            require(selection.source.key !in combinedSources) { "Use the desktop app to assemble this combined source." }
            val n=selection.source; val versions=binaryVersions(n); require(versions.isNotEmpty()) { "No published targets." }
            val routes=paths(n.key)
            val destination=when(target) {
                "Latest"->versions.firstOrNull { it.key in routes && compareVersions(it.key.version,n.key.version)>=0 }
                "Next version only"->versions.reversed().firstOrNull { routes[it.key]?.size==1 && compareVersions(it.key.version,n.key.version)>0 }
                else->versions.firstOrNull { it.key.version==clean(target) && it.key in routes }
            } ?: error("No compatible route to this version.")
            val file=selection.input!!
            return Route(destination.key.version,versions.first().key.version,versions.first().key in routes,
                listOf(Part(file.name,file,n,destination,routes.getValue(destination.key))))
        }
        val s=selection.solution!!
        val versions=solutions.values.filter { it.key in activeSolutions && it.key.family==s.key.family }
            .sortedWith { a,b->compareVersions(b.key.version,a.key.version) }
        val reachable=versions.mapNotNull { dest ->
            val parts=dest.components.map { c->
                val (input,source)=selection.found[c.target.edition] ?: return@mapNotNull null
                val end=nodes.getValue(c.target)
                val route=if(source.identity.size==end.identity.size && source.identity.hashes["sha256"]==end.identity.hashes["sha256"])
                    emptyList() else paths(source.key)[c.target] ?: return@mapNotNull null
                Part(c.name,input,source,end,route)
            }
            val copies=dest.copies.map { c->
                val input=selection.folder.singleOrNull { it.name==c.name && it.size==c.size } ?: return@mapNotNull null
                input to c
            }
            dest to Route(dest.key.version,versions.first().key.version,false,parts,copies,true)
        }.toMap()
        val ordered=if(target=="Next version only") versions.reversed() else versions
        val dest=ordered.firstOrNull { d->reachable[d]?.let { r->when(target) {
            "Latest"->r.parts.all { it.edges.isEmpty() || compareVersions(it.target.key.version,it.source.key.version)>=0 }
            "Next version only"->r.edges.isNotEmpty() && r.parts.all { it.edges.size<=1 && (it.edges.isEmpty() || compareVersions(it.target.key.version,it.source.key.version)>=0) }
            else->d.key.version==clean(target)
        } } ?: false } ?: error("No complete compatible route. Check companion files and the selected version.")
        return reachable.getValue(dest).copy(latestReachable=versions.first() in reachable)
    }
}
