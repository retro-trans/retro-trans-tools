# Retro Trans Android 0.5.24 preview

Native Kotlin/Jetpack Compose app with the pinned xdelta3 engine included.
The preview package is `org.retrotrans.tools.debug`, version `0.5.24-preview`
(versionCode 524). Android 8/API 26 or newer is required. The APK includes ARM64
and x86-64; no Python, Termux or separate patch engine is needed.

This is a fresh preview build accompanying the desktop 0.5.24 release. It retains
the existing preview signing certificate so it can update the earlier test APK.
It is not a production Android release. Real-phone, minimum-API, 16 KB runtime
and removable-storage testing remain outstanding; see the attached validation
report for the checks actually performed.

The current catalog is supported. Combined-source PC games that require assembling
several inputs remain desktop-only; the catalog status states this limitation.
Supported ordinary upgrades and multi-file output solutions remain available.

## Try it

1. Copy the test APK to the phone and open it. Allow installation for the app
   opening the APK when Android asks.
2. In **Automatic**, choose **Browse file** for one binary, or **Folder** for a
   game folder. For CUE/GDI sets, choose the folder containing the descriptor
   and all its tracks. Scanning only reads immediate files in that folder.
3. Select a recognized file or disc set. Choose **Latest**, **Next version only**
   or a published version, and review **Route details**.
4. Choose a local output folder and a new filename (or a new subfolder name for
   a disc set). Press **Patch**. Existing output names are refused.
5. To apply a local patch without the catalog, use **Apply xdelta**, select the
   source and `.xdelta`/`.vcdiff`, choose the output and press **Patch**.

Allow notifications to keep progress and Cancel accessible when the app is in
the background. Opening a file never starts patching. Originals stay unchanged.
PS3 games show the old installation-data warning; saved games are not removed.

## Included

- Bundled catalog; validated refresh at startup and via the menu; offline cache.
- Size-filtered identification with SHA-256 and legacy SHA-1 in one read pass.
- Direct/chained routes, historical targets, withdrawal protection and grouped
  multi-file solutions. The newest published version is shown if unreachable.
- Verified downloads, every intermediate and final Automatic output checked,
  and verified export to a new file/folder. Manual mode uses xdelta checksums
  and export readback, without claiming catalog-based output identity.
- Cancellable background patching in a dedicated process. An interrupted job
  offers Resume/Discard and rechecks retained results; it can repeat earlier
  steps whose intermediates were already removed. Downloads restart at file
  boundaries rather than resuming partial HTTP transfers.
- Read-only input descriptors, 64-bit file positions and bounded native
  allocations. xdelta/LZMA together get 256 MiB; secondary LZMA streams have a
  128 MiB limit. UI/runtime memory is additional. Unusually large xdelta windows
  can exceed the budget and are rejected instead of allocating without limit.

Inputs from cloud/non-seekable providers require an explicitly confirmed local
import. Providers without a file size must first be downloaded with the user's
file manager. Output currently supports Android's local internal/SD/USB document
provider, not cloud providers. No broad/all-files permission is requested.

Patching needs temporary internal storage, including space for a verified export.
Free-space estimates are conservative; destination volumes and unknown-size
legacy outputs can still run out of space during writing. In that case the app
removes its unfinished export and preserves the source. FAT32 cannot hold a
single output over 4 GiB. A provider/process failure in the narrow rename/receipt
window can leave an orphaned `.partial` or completed output; the app never deletes
an existing user filename to recover. Choose a different name after inspecting it.

CHD, save conversion, Vita PKG/license handling, private automatic downloads
and patch creation are deferred. Local private xdelta files still work manually.

## DCP (experimental)

For Black/Matrix AD, choose **Automatic → Folder** and grant access to the folder
containing an original Disc 1 or Disc 2 CUE and all three BINs. The app checks all
tracks, offers the matching experimental v0.9.0 profile, and downloads its DCP only
when you press **Patch**. Choose a new output-folder name. Load `disc.gdi` from the
result in a Dreamcast emulator that supports GDI. Handle each disc separately;
the app does not change emulator memory cards or saves.

For a downloaded local DCP, use **DCP → Folder**, select the original disc set,
choose **local DCP**, and select a new output-folder name. This works offline.
Both modes require Retro Trans ZIP-comment verification metadata and verify the
complete source and target game-file trees, target boot invariant and companion
tracks before exporting. Output files are read back and hashed after export.

This initial engine is native Kotlin plus the already-bundled xdelta decoder,
not a desktop .NET executable, downloaded executable, Termux or remote service.
It supports three-track Redump MODE1/2352 CUE/BIN or three-track GDI (data sectors
2048/2352, zero file offsets), **GDI output only**, and same-tree file replacements.
Expanded files relocate only into unreferenced sectors verified to contain zeros.
The output keeps the original filesystem layout otherwise. A silent CUE audio
pregap is removed for GDI while non-silent audio bytes/sample alignment are kept.
Non-silent pregaps, added files/directories, Joliet/supplementary volumes,
multi-extent files, other track geometries, CHD input/output and CUE output are
rejected explicitly; use desktop DCP for those. This is not universal DCP support.

All originals are staged read-only through granted document URIs; temporary space
is required on internal storage in addition to the output destination. The app
checks a conservative estimate before staging and actual archive expansion before
patching. A large game may require several GB free. DCP resume repeats application
from verified originals instead of trusting a partially rebuilt image. Do not
delete app data or force-stop the worker during export.

Both real Black/Matrix AD discs passed host execution of this exact Kotlin kernel
and independent pinned desktop UDP reading: expected target game trees, boot
invariants and non-silent audio/sample alignment matched; original track hashes
were unchanged. Device/native decoder and export results are recorded in the
local validation receipt. These are data-integrity checks, not fresh gameplay,
ARM64 phone, minimum-API, 16 KB runtime or physical Dreamcast hardware tests.

## Build and check

Use JDK 17, Android platform/build tools 36/36.0.0, NDK 28.2.13676358 and CMake
3.22.1. Set `ANDROID_HOME` to the SDK, or create ignored `android/local.properties`
with `sdk.dir=...`. Native archives are pinned by commit and SHA-256 in CMake.
The first build needs network access; installed APKs include the engine.

From `android/`:

```text
gradlew.bat :patch-core:test :app:assembleDebug :app:assembleDebugAndroidTest :app:lintDebug
```

On Linux/macOS use `./gradlew` (or `bash gradlew`). The application is written to
`app/build/outputs/apk/debug/app-debug.apk`. The test APK is separate; synthetic
test binaries are not bundled in the application.

On a disposable test emulator, create `Documents/RetroTransAndroidTest`, install
both APKs and run the instrumentation suite. Workflow tests operate only inside
that test folder and the test app's private storage. They interact with Android's
folder permission picker, so do not run them on a personal phone unattended.

```text
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb install -r app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
adb shell am instrument -w org.retrotrans.tools.debug.test/androidx.test.runner.AndroidJUnitRunner
```

The >4 GiB output test is opt-in: add `-e large true` before the runner. It needs
5 GiB free and writes/hashes 4 GiB + 8 MiB, then removes its own files.
`scripts/generate_fixtures.py` regenerates legal synthetic fixtures and 1,391
desktop route expectations from the repository's Python code and bundled Windows
xdelta engine. Run it from the repository root with the project Python environment
after changing desktop routing/catalog contracts; review expectation changes.

CI in `android-checks.yml` builds, runs JVM route tests and lint, and uploads debug
artifacts. It does not publish or run the device instrumentation suite.

## Updates and publication

Preview APKs use manual updates. Download the newer preview from the matching
app release and install it over the previous preview; settings are retained when
Android accepts the matching signer and increasing version code. Do not uninstall
first. Production signing, the stable Android update feed and automatic installer
prompts are not enabled in this preview.

The shared release workflow builds and tests this APK and checks both native ABIs,
16 KB ELF/APK alignment, its signing identity and the exact bundled catalog. The
preview signing key is held in a repository secret and never included in source
or release files. All platform artifacts must pass before publication.

Full xdelta, liblzma and Apache notices are bundled in APK assets. The About dialog
shows the dependency summary and source locations. The CMake file documents the
bounded-allocator adaptation to xdelta's LZMA integration.
