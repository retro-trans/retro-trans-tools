package org.retrotrans.core

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class CatalogTest {
    private fun resource(name:String)=javaClass.getResource("/$name")!!.readText()
    private fun key(a:JsonArray)=Key(a[0].jsonPrimitive.content,a[1].jsonPrimitive.content,a[2].jsonPrimitive.content,a[3].jsonPrimitive.content)
    @Test fun currentDesktopCatalogKeepsSupportedRoutesAndCombinedIdentities() {
        val c=Catalog(resource("live-catalog.json"))
        assertTrue(c.edges.size>=300)
        assertTrue(c.combinedSources.isNotEmpty())
        assertTrue(c.summary.contains("require desktop"))
        c.checkUpdate(Catalog(c.raw))
        for(k in c.combinedSources.keys) {
            val n=c.nodes.getValue(k)
            assertFalse(c.recognize(Input("test","source",n.identity.size!!,n.identity.hashes)).any { it.key==k })
        }
        val (k,parts)=c.combinedSources.entries.first()
        val data=Json.parseToJsonElement(c.raw).jsonObject
        val releases=data.getValue("releases").jsonArray.map { value->
            val r=value.jsonObject
            if(r.getValue("manifest").jsonObject["schema_version"]!=JsonPrimitive(3)) value else {
                val m=r.getValue("manifest").jsonObject
                val patches=m.getValue("patches").jsonArray.map { p->val row=p.jsonObject
                    row["combined_source"]?.let { combined->
                        val cs=combined.jsonObject
                        JsonObject(row+("combined_source" to JsonObject(cs+("files" to JsonArray(cs.getValue("files").jsonArray.reversed())))))
                    } ?: p
                }
                JsonObject(r+("manifest" to JsonObject(m+("patches" to JsonArray(patches)))))
            }
        }
        assertThrows(IllegalArgumentException::class.java) { c.checkUpdate(Catalog(JsonObject(data+("releases" to JsonArray(releases))).toString())) }
        assertEquals(parts,c.combinedSources[k])
    }
    @Test fun desktopRouteParity() {
        val c=Catalog(resource("catalog.json"))
        for(element in Json.parseToJsonElement(resource("routes.json")).jsonArray) {
            val row=element.jsonObject
            val source=c.nodes.getValue(key(row.getValue("source").jsonArray))
            val selected=Selection(source.label,source,Input("fixture","source.bin",source.identity.size ?: 0,source.identity.hashes))
            val result=runCatching { c.plan(selected,row.getValue("choice").jsonPrimitive.content) }
            if(row["error"]==JsonPrimitive(true)) assertTrue(row.toString(),result.isFailure)
            else {
                val route=result.getOrThrow()
                assertEquals(row.toString(),key(row.getValue("target").jsonArray),route.parts.single().target.key)
                assertEquals(row.getValue("edges").jsonArray.map { it.jsonPrimitive.content },route.edges.map { it.asset.url })
                assertEquals(row.getValue("reachable").jsonPrimitive.boolean,route.latestReachable)
            }
        }
    }
    @Test fun publishedCatalogAndImmutability() {
        val c=Catalog(resource("catalog.json")); assertTrue(c.edges.size>=242); assertEquals(8,c.solutions.size)
        c.checkUpdate(Catalog(c.raw))
        val mutated=c.raw.replace(c.edges.first().asset.sha256,"0".repeat(64))
        assertThrows(IllegalArgumentException::class.java) { c.checkUpdate(Catalog(mutated)) }
        val data=Json.parseToJsonElement(c.raw).jsonObject.toMutableMap()
        data["withdrawn_releases"]=JsonArray(emptyList())
        assertThrows(IllegalArgumentException::class.java) { c.checkUpdate(Catalog(JsonObject(data).toString())) }
    }
    @Test fun malformedSchemasAndTraversalAreRejected() {
        for(name in listOf("../x","a/b","a\\b","CON","name.","file\u0000")) assertThrows(IllegalArgumentException::class.java) { safeName(name) }
        assertThrows(IllegalArgumentException::class.java) { Catalog("{\"schema_version\":\"1\",\"releases\":[]}") }
        assertTrue(compareVersions("1.10","1.9")>0)
        assertTrue(compareVersions("original","0.0")<0)
    }
    @Test fun recognitionGroupsMissingAndDuplicateComponents() {
        val c=Catalog(resource("catalog.json"))
        val solution=c.solutions.values.first { it.key in c.activeSolutions }
        val inputs=solution.components.mapIndexed { i,part->val n=c.nodes.getValue(part.target);Input("$i","renamed-$i.bin",n.identity.size!!,n.identity.hashes) } +
            solution.copies.mapIndexed { i,f->Input("copy-$i",f.name,f.size,mapOf("sha256" to f.sha256)) }
        val selections=c.selections(inputs)
        val group=selections.first { it.solution?.key?.family==solution.key.family }
        assertTrue(group.problems.isEmpty()); assertTrue(c.plan(group,solution.key.version).grouped)
        val missing=c.selections(inputs.drop(1)).first { it.solution?.key?.family==solution.key.family }
        assertTrue(missing.problems.isNotEmpty()); assertTrue(runCatching { c.plan(missing) }.isFailure)
        val duplicate=c.selections(inputs+inputs.first().copy(uri="duplicate")).first { it.solution?.key?.family==solution.key.family }
        assertTrue(duplicate.problems.isNotEmpty())
        val withdrawnOnly=c.nodes.values.filter { it.key !in c.available }
        for(n in withdrawnOnly) assertTrue(c.recognize(Input("x","unknown",n.identity.size ?: 1,n.identity.hashes)).none { it.key==n.key })
    }
}
