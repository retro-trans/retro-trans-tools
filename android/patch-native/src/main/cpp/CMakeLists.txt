cmake_minimum_required(VERSION 3.22)
project(retro_patch LANGUAGES C CXX)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
include(FetchContent)
set(XD3_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(XD3_SECONDARY_FGK ON CACHE BOOL "" FORCE)
set(XD3_LIB_LZMA ON CACHE BOOL "" FORCE)
set(XD3_LZMA_FETCH ON CACHE BOOL "" FORCE)
FetchContent_Declare(liblzma
  URL https://codeload.github.com/tukaani-project/xz/tar.gz/4b73f2ec19a99ef465282fbce633e8deb33691b3
  URL_HASH SHA256=de536250ae287bd6cdac94e72bab680a1e2219df7e07e27c376670f9cd15dc87)
FetchContent_Declare(xdelta
  URL https://codeload.github.com/jmacd/xdelta/tar.gz/ff322e592383227b0d65ddfde7e0e5bbc504dc15
  URL_HASH SHA256=2553888160ad4e4036fc012c123e9c4d917cfc1be10f180a43b22f09dc94db53
  SOURCE_SUBDIR xdelta3)
FetchContent_MakeAvailable(xdelta)
# Keep secondary LZMA allocations inside the same per-job memory budget. The
# upstream decoder uses an unlimited independent allocator by default.
set(lzma_header "${xdelta_SOURCE_DIR}/xdelta3/xdelta3-lzma.h")
file(READ "${lzma_header}" lzma_text)
if(NOT lzma_text MATCHES "retro_trans_bounded_allocator")
  string(REPLACE "  lzma_stream lzma;" "  lzma_stream lzma;\n  lzma_allocator retro_trans_bounded_allocator;" lzma_text "${lzma_text}")
  string(REPLACE "static int xd3_lzma_init(" "static void *retro_lzma_alloc(void *opaque, size_t count, size_t size) { return xd3_alloc((xd3_stream*)opaque, count, size); }\nstatic void retro_lzma_free(void *opaque, void *ptr) { xd3_free((xd3_stream*)opaque, ptr); }\nstatic int xd3_lzma_init(" lzma_text "${lzma_text}")
  string(REPLACE "  memset(&sec->lzma, 0, sizeof(sec->lzma));" "  memset(&sec->lzma, 0, sizeof(sec->lzma));\n  sec->retro_trans_bounded_allocator.alloc = retro_lzma_alloc;\n  sec->retro_trans_bounded_allocator.free = retro_lzma_free;\n  sec->retro_trans_bounded_allocator.opaque = stream;\n  sec->lzma.allocator = &sec->retro_trans_bounded_allocator;" lzma_text "${lzma_text}")
  string(REPLACE "UINT64_MAX, LZMA_TELL_NO_CHECK" "(128ULL << 20), LZMA_TELL_NO_CHECK" lzma_text "${lzma_text}")
  file(WRITE "${lzma_header}" "${lzma_text}")
endif()
add_library(retro_patch SHARED bridge.cpp)
target_link_libraries(retro_patch PRIVATE xdelta3lib)
target_compile_features(retro_patch PRIVATE cxx_std_17)
target_compile_definitions(retro_patch PRIVATE _FILE_OFFSET_BITS=64)
target_link_options(retro_patch PRIVATE "-Wl,-z,max-page-size=16384")
