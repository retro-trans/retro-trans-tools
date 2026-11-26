plugins { alias(libs.plugins.kotlin.jvm) }
kotlin { jvmToolchain(17) }
kotlin.sourceSets.getByName("test").kotlin.srcDir("../test-support")
dependencies { implementation(libs.json); testImplementation(libs.junit) }
tasks.test { testLogging { events("failed", "skipped") } }
tasks.processTestResources { from("../../retro_trans/resources/catalog.json") { rename { "live-catalog.json" } } }
