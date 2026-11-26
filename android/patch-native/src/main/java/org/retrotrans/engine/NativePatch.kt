package org.retrotrans.engine

object NativePatch {
    init { System.loadLibrary("retro_patch") }
    /** Return false to cancel. Called on the worker thread, never the UI thread. */
    fun interface Progress { fun update(inputBytes: Long, outputBytes: Long): Boolean }
    external fun decode(sourceFd: Int, patchFd: Int, outputFd: Int, maxOutput: Long, progress: Progress): Long
}
