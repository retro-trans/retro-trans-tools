package org.retrotrans.core

import kotlinx.serialization.json.*
import java.net.URLEncoder

data class DcpProfile(val game:String,val gameName:String,val edition:String,val language:String,val version:String,
    val asset:Asset,val metadata:JsonObject,val tracks:List<Identity>,val prerelease:Boolean)
data class DcpSelection(val descriptor:Input,val tracks:List<Input>,val profiles:List<DcpProfile>)
object DcpCatalog {
    private fun JsonObject.s(k:String)=getValue(k).jsonPrimitive.also { require(it.isString) }.content
    private fun size(e:JsonElement):Long=e.jsonPrimitive.also { require(!it.isString) }.long.also { require(it in 1..(4L*1024*1024*1024)) }
    private fun hash(s:String)=s.also { require(Regex("[a-f0-9]{64}").matches(it)) }
    fun load(data:JsonObject):List<DcpProfile> {
        val records=data["dcp_releases"]?.jsonArray ?: return emptyList()
        require(records.size<=1000)
        val seen=mutableSetOf<String>();val sources=mutableMapOf<List<String>,Pair<List<Identity>,String>>()
        val targets=mutableMapOf<List<String>,List<String>>()
        return records.flatMap { record->
            val r=record.jsonObject;val repo=r.s("repo");val tag=r.s("tag");val m=r.getValue("manifest").jsonObject
            require(Regex("retro-trans/[A-Za-z0-9_.-]+").matches(repo) && seen.add("$repo/$tag"));hash(r.s("manifest_sha256"))
            require(m["schema_version"]==JsonPrimitive(1) && m.s("format")=="DCP" && m.s("platform")=="Dreamcast" && m.s("minimum_app_version")=="0.5.20")
            val version=m.s("version");require(tag.removePrefix("v")==version && compareVersions(version,"original")>0)
            require(Regex("[a-f0-9]{40}").matches(m.s("source_commit")) && Regex("[a-z0-9][a-z0-9-]*").matches(m.s("game_id")))
            val prerelease=r["prerelease"]==JsonPrimitive(true);require(!prerelease || m["allow_prerelease"]==JsonPrimitive(true))
            val rows=m.getValue("patches").jsonArray;require(rows.size in 1..20)
            val assets=r.getValue("assets").jsonObject;val names=mutableSetOf<String>();val folded=mutableSetOf<String>();val editions=mutableSetOf<String>()
            val result=rows.map { value->
                val p=value.jsonObject;val name=safeName(p.s("patch"));require(name.endsWith(".dcp") && names.add(name) && folded.add(name.lowercase()))
                val edition=p.s("edition");require(Regex("[a-z0-9][a-z0-9-]*").matches(edition))
                val metadata=Dcp.metadata(p.getValue("metadata").jsonObject)
                require(metadata.s("game_id")==m.s("game_id") && metadata.s("game_name")==m.s("game_name") && metadata.s("version")==version)
                require(editions.add(edition+"/"+metadata.s("source_version")))
                val tracks=p.getValue("source_tracks").jsonArray.map { t->t.jsonObject.let { Identity(size(it.getValue("bytes")),mapOf("sha256" to hash(it.s("sha256")))) } }
                require(tracks.size in 3..99)
                val prefix="https://github.com/$repo/releases/download/"+URLEncoder.encode(tag,"UTF-8").replace("+","%20")+"/"
                val url=prefix+URLEncoder.encode(name,"UTF-8").replace("+","%20")
                require(assets[name]?.jsonPrimitive?.content==url)
                val family=listOf(m.s("game_id"),edition,m.s("language"))
                val source=tracks to metadata.s("source_tree_sha256");val key=family+metadata.s("source_version")
                require(sources.putIfAbsent(key,source)?.let { it==source }!=false) { "Changed DCP source identity." }
                val target=listOf(metadata.s("target_tree_sha256"),metadata.s("bootsector_invariant_sha256"),metadata.getValue("disc").jsonPrimitive.content)
                require(targets.putIfAbsent(family+version,target)?.let { it==target }!=false) { "Changed DCP target identity." }
                DcpProfile(m.s("game_id"),m.s("game_name"),edition,m.s("language"),version,
                    Asset(name,url,size(p.getValue("bytes")),hash(p.s("sha256"))),metadata,tracks,prerelease)
            }
            require(assets.keys==names)
            result
        }
    }
    fun recognize(profiles:List<DcpProfile>,descriptor:Input,text:String,inputs:List<Input>):Selection? {
        val geometry=Dcp.tracks(descriptor.name,text)
        val tracks=geometry.map { t->inputs.singleOrNull { it.name==t.name } ?: return null }
        val matches=profiles.filter { p->p.tracks.size==tracks.size && p.tracks.zip(tracks).all { (id,input)->id.matches(input.size,input.hashes) } }
        if(matches.isEmpty())return null
        require(matches.map { listOf(it.game,it.edition,it.language,it.metadata["source_version"].toString()) }.distinct().size==1) { "Ambiguous DCP source profiles." }
        val p=matches.first()
        return Selection("${descriptor.name} — ${p.gameName} / ${p.edition} / ${p.metadata.s("source_version")} (DCP)",
            dcp=DcpSelection(descriptor,tracks,matches))
    }
    fun plan(selection:DcpSelection,target:String):DcpProfile {
        val sorted=selection.profiles.sortedWith { a,b->compareVersions(b.version,a.version) }
        return when(target) { "Latest"->sorted.first();"Next version only"->sorted.last();else->sorted.singleOrNull { it.version==target.removePrefix("v") } ?: error("No compatible DCP target.") }
    }
    fun checkUpdate(old:List<DcpProfile>,next:List<DcpProfile>) {
        require(old.all { p->next.any { it==p } }) { "Catalog changed a published DCP." }
        for(a in old)for(b in next)if(listOf(a.game,a.edition,a.language)==listOf(b.game,b.edition,b.language)) {
            if(a.metadata["source_version"]==b.metadata["source_version"])require(a.tracks==b.tracks && a.metadata["source_tree_sha256"]==b.metadata["source_tree_sha256"])
            if(a.version==b.version)require(listOf("target_tree_sha256","bootsector_invariant_sha256","disc").all { a.metadata[it]==b.metadata[it] })
        }
    }
}
