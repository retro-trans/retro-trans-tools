package org.retrotrans.tools

import kotlinx.serialization.json.*
import org.retrotrans.core.Route

fun automaticRequest(route:Route,output:String,name:String):JsonObject = obj(
    "mode" to str("automatic"),"output" to str(output),"name" to str(name),"grouped" to JsonPrimitive(route.grouped),
    "parts" to JsonArray(route.parts.map { p->obj("name" to str(p.name),"uri" to str(p.input.uri),
        "source_key" to keyJson(p.source.key),"target_key" to keyJson(p.target.key),"edges" to JsonArray(p.edges.map { str(it.asset.url) })) }),
    "copies" to JsonArray(route.copies.map { (input,copy)->obj("uri" to str(input.uri),"name" to str(copy.name),"bytes" to JsonPrimitive(copy.size),"sha256" to str(copy.sha256)) }))
