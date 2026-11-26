#include <jni.h>
#include <unistd.h>
#include <sys/stat.h>
#include <cerrno>
#include <cstring>
#include <cstdlib>
#include <cstddef>
#include <limits>
#include <vector>
#include <string>
extern "C" {
#include "xdelta3.h"
}

// The codec never opens files, runs subprocesses, or uses an app-header filename.
// Every fd belongs to this invocation. Java retains ownership of closing it.
namespace {
constexpr size_t BLOCK = 1 << 20;
constexpr size_t MEMORY_LIMIT = 256 << 20;
struct Budget { size_t used = 0; };
struct alignas(std::max_align_t) Allocation { size_t bytes; };
void* allocate(void* opaque, size_t count, usize_t size) {
    auto* b = static_cast<Budget*>(opaque);
    if (size && count > MEMORY_LIMIT / size) return nullptr;
    size_t bytes = count * size;
    if (bytes > MEMORY_LIMIT - b->used) return nullptr;
    auto* p = static_cast<Allocation*>(std::malloc(bytes + sizeof(Allocation)));
    if (!p) return nullptr;
    p->bytes = bytes; b->used += bytes;
    return p + 1;
}
void release(void* opaque, void* pointer) {
    if (!pointer) return;
    auto* p = static_cast<Allocation*>(pointer) - 1;
    static_cast<Budget*>(opaque)->used -= p->bytes;
    std::free(p);
}
ssize_t readAt(int fd, void* buffer, size_t size, off_t offset) {
    size_t done = 0;
    while (done < size) {
        ssize_t n = pread(fd, static_cast<char*>(buffer) + done, size - done, offset + done);
        if (n < 0 && errno == EINTR) continue;
        if (n < 0) return -1;
        if (!n) break;
        done += n;
    }
    return done;
}
bool writeAll(int fd, const uint8_t* buffer, size_t size) {
    while (size) {
        ssize_t n = write(fd, buffer, size);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return false;
        buffer += n; size -= n;
    }
    return true;
}
}

extern "C" JNIEXPORT jlong JNICALL
Java_org_retrotrans_engine_NativePatch_decode(JNIEnv* env, jobject,
        jint sourceFd, jint patchFd, jint outputFd, jlong limit, jobject callback) {
    xd3_stream stream{}; xd3_config config{}; xd3_source source{};
    Budget budget;
    std::vector<uint8_t> input(BLOCK), sourceBlock(BLOCK);
    std::string error;
    jlong produced = 0; off_t consumed = 0;
    bool initialized = false, eof = false, gotWindow = false;
    jclass cbClass = env->GetObjectClass(callback);
    jmethodID progress = env->GetMethodID(cbClass, "update", "(JJ)Z");
    struct stat sourceStat{}, patchStat{};
    if (!progress || limit < 0 || fstat(sourceFd, &sourceStat) ||
        fstat(patchFd, &patchStat) || lseek(sourceFd, 0, SEEK_CUR) < 0 ||
        lseek(patchFd, 0, SEEK_CUR) < 0) {
        error = "Input is not a seekable local file.";
    } else {
        xd3_init_config(&config, 0); // Never use XD3_ADLER32_NOVER.
        config.alloc = allocate; config.freef = release; config.opaque = &budget;
        int result = xd3_config_stream(&stream, &config);
        initialized = result == 0;
        source.blksize = BLOCK; source.curblk = sourceBlock.data();
        source.curblkno = static_cast<xoff_t>(-1);
        if (result || xd3_set_source_and_size(&stream, &source, sourceStat.st_size)) {
            error = "Cannot initialize xdelta.";
        }
        while (error.empty()) {
            if (!env->CallBooleanMethod(callback, progress, static_cast<jlong>(consumed), produced)
                    || env->ExceptionCheck()) { error = "Cancelled"; break; }
            result = xd3_decode_input(&stream);
            if (result == XD3_INPUT) {
                if (eof) {
                    if (!gotWindow || xd3_close_stream(&stream)) error = "Incomplete xdelta patch.";
                    break;
                }
                auto n = readAt(patchFd, input.data(), BLOCK, consumed);
                if (n < 0) { error = "Cannot read patch."; break; }
                consumed += n;
                eof = n == 0 || consumed >= patchStat.st_size;
                if (eof) xd3_set_flags(&stream, XD3_FLUSH);
                xd3_avail_input(&stream, input.data(), n);
            } else if (result == XD3_OUTPUT) {
                if (stream.avail_out > static_cast<uint64_t>(limit - produced)) {
                    error = "Patch output exceeds the available space or declared size."; break;
                }
                if (!writeAll(outputFd, stream.next_out, stream.avail_out)) {
                    error = "Cannot write output. Check free space."; break;
                }
                produced += stream.avail_out;
                xd3_consume_output(&stream);
            } else if (result == XD3_GETSRCBLK) {
                if (source.getblkno > static_cast<uint64_t>(std::numeric_limits<off_t>::max()) / BLOCK) {
                    error = "Invalid source offset."; break;
                }
                auto n = readAt(sourceFd, sourceBlock.data(), BLOCK, source.getblkno * BLOCK);
                if (n < 0) { error = "Cannot read original."; break; }
                source.onblk = n; source.curblkno = source.getblkno;
            } else if (result == XD3_WINFINISH) gotWindow = true;
            else if (result != XD3_GOTHEADER && result != XD3_WINSTART) {
                error = stream.msg ? stream.msg : "Invalid xdelta patch."; break;
            }
        }
    }
    if (initialized) { xd3_abort_stream(&stream); xd3_free_stream(&stream); }
    if (error.empty() && fsync(outputFd)) error = "Output could not be flushed.";
    if (!error.empty() && !env->ExceptionCheck()) {
        jclass cls = env->FindClass(error == "Cancelled" ? "java/util/concurrent/CancellationException" : "java/io/IOException");
        env->ThrowNew(cls, error.c_str());
    }
    return produced;
}
