> **2026-11-26:** The user authorized 0.5.24 publication with all platform builds.
> Android ships as a freshly built, signed preview with the current catalog;
> production-only validation and automatic updates remain deferred. The earlier
> publication restrictions below describe the historical implementation tasks.

# Retro Trans for Android — implementation plan

> **2026-11-02 update:** the user explicitly requested Android DCP support.
> Local `0.1.0-test2` adds experimental verified three-track/same-tree CUE/GDI
> application to GDI, both Black/Matrix AD Automatic profiles and a local DCP tab.
> No Android publication is authorized by this implementation request. See
> `android/README.md` and `android/CHANGELOG.md` for actual scope and limits.
> References below to DCP being entirely deferred describe the original test1
> plan; CHD, arbitrary track layouts/file additions and production gates remain
> deferred. Existing unrelated Android and Mac work is preserved.

Prepared 2026-10-30. Implementation started after the user's “go”. A local
`0.1.0-test1` debug APK implements Automatic and Apply xdelta. At the user's
request, the test APK, checksums and validation report were attached to the existing
Windows `v0.5.18` release on October 30. Android source changes remain local; the
tag's source archive predates them. Build/use details are in
[`android/README.md`](../android/README.md).

## Current implementation status

The three modules, native engine, shared catalog/routing contracts, compact UI,
folder access, verified downloads/exports, background worker and recovery records
are implemented. JVM fixtures compare 1,391 route decisions with desktop. Device
tests use synthetic files in an isolated Android 16 x86_64 emulator. Both ARM64
and x86_64 compile; native ELF/APK alignment is checked for 16 KB pages.

These checks do not establish real-phone compatibility. Before production,
test ARM64 decoding, minimum Android versions, an actual 16 KB runtime, removable
storage, provider grant revocation, screen-off/service-timeout/process-death
recovery, device memory/throughput and signed application upgrades. The separate
Android update code is present but production signing/feed/publication are not
configured. The release workflow below remains a future explicitly authorized
step; current CI only produces test artifacts.

The user selected **Automatic patching + manual xdelta first**, with CHD, DCP,
save conversion and Vita package tools deferred. Build a compact native Android
app in this repository, sharing the desktop release contracts and catalog.

## Baseline and proposed defaults

- Upstream synchronized to `b09dc5b` on `origin/main`. Its catalog validates:
  106 active release records, 242 active patch connections, 12 withdrawn patch
  connections, 170 binary identities and 8 multi-file solutions.
- Preserve the existing uncommitted desktop 0.5.19/DCP work. Android work belongs
  under `android/`; do not include unrelated desktop changes in Android commits.
- Native Kotlin + Jetpack Compose UI; no WebView, Electron or embedded desktop
  Python runtime. Port the small catalog/routing layer and compare it against
  the existing Python implementation using shared fixtures.
- Proposed minimum: Android 8.0/API 26, ARM64 phones/tablets. Add x86_64 for
  emulator testing; defer 32-bit phones. Start with compile/target API 36, then
  recheck supported stable tooling before implementation and publication.
- Distribute a signed APK through GitHub first. Proposed package ID:
  `org.retrotrans.tools`; Android version starts at `0.1.0` with a monotonically
  increasing versionCode. Display the actual Android build version in the app
  bar and About. This version is independent of the desktop Python version.
- No Android SDK, Python, .NET, Termux or separate patching engine is required
  on the user's phone. Development requires Android SDK/NDK, Gradle and a JDK.

Compose provides native Android UI. Native dependencies must also work on
16 KB page-size devices; make this an initial build/test requirement, not a
later packaging change. [Compose](https://developer.android.com/develop/ui/compose),
[SDK platforms](https://developer.android.com/tools/releases/platforms),
[native page-size support](https://developer.android.com/guide/practices/page-sizes).

## First release behavior

Use two compact tabs, **Automatic** and **Apply xdelta**, with one shared job
status area, progress bar and Cancel control. About, logs, cache management and
updates belong in a small menu. Keep touch targets accessible and support
large text, landscape and narrow phone screens.

Automatic contains file/folder selection, recognized-file selector, detected
game/edition/version, Latest / Next version only / Specific version, route
summary, output folder/name and Patch. Detailed component routes open in a
dialog. Patch always requires a user tap. A single match may select itself;
multiple matches require a choice.

Support exact ISO, BIN, VPK, CPK and other binary bytes, plus schema-v2
multi-file solutions with CUE/GDI and unchanged companion files. A CUE/GDI
selection requests access to its containing folder when required; granting
one document does not automatically grant access to sibling tracks. Preserve
edition/language separation, legacy SHA-1 recognition, explicit compatible
downgrades, withdrawn-route rules and the warning when the latest published
version is unreachable. Prefer fewer patch steps, then smaller downloads.

Apply xdelta accepts an original binary, local xdelta and new output. It works
offline immediately and keeps xdelta checksum validation enabled. Clearly
distinguish these checks from catalog whole-file verification. Do not add a
Create xdelta tab. Private patches may be downloaded separately and selected
locally; Android does not inherit desktop GitHub CLI credentials.

CHD and DCP inputs explain that conversion is not available in this first
version. Ordinary binary VPK/CPK patches remain supported; Vita PKG rebuilding
and hardware rePatch are different operations and stay unavailable. Retain
the existing PS3 installation-data warning whenever applicable, explicitly
protecting saved games.

## Storage and recognition

Use Android's system document/folder picker and persist granted URI access.
On first use, let the user choose a Games folder. On later launches, scan only
its immediate files, with cancellation; never scan the entire phone or the APK
installation location. Offer Browse and Scan again. Handle revoked grants and
removed SD/USB storage with a request to select the location again.

Android restricts access to storage roots and other apps' private folders;
emulator files may need to be exported into a shared Games folder. No broad
all-files permission is planned. [Android document access](https://developer.android.com/training/data-storage/shared/documents-files).

Filter by known byte sizes before hashing. Calculate all required SHA-256/SHA-1
hashes in one streaming pass, with bytes processed and cancellation. A missing
provider size is unknown, not zero. Avoid hashing unrelated unknown-size files
during automatic scans; explicitly selected files may be read to identify them.
Recognition caches are hints only: revalidate the source when Patch starts.

Treat `content://` URIs as documents, never guessed filesystem paths. Use a
read-only file descriptor directly when it supports seeking. Otherwise offer
one local staging copy, hashing during that copy, and reuse it for the job.
Do not request write access merely to make a source seekable. Cloud/streaming
providers require an explicit local import in this first version.
[Descriptor behavior](https://developer.android.com/reference/android/content/ContentResolver#openFileDescriptor(android.net.Uri,%20java.lang.String)).

Patch into an owned local workspace. Before starting, account separately for
source staging, cached patches, the largest pair of intermediate files, final
output and export duplication across the actual storage volumes. Explain
unknown capacity and filesystem size limits, including files over 4 GiB on
FAT32; stop safely on write errors.

Verify every intermediate and the final local output before export. For
multi-file solutions verify patched and copied components and descriptors.
Export only to a selected, tested local document provider: create new documents,
reject existing names, track their returned URIs, close and read back to verify.
Use a new temporary name/folder and rename on completion where supported;
never assume document-provider operations are atomic. If safe create/delete/
rename behavior cannot be established, retain the verified local result and
request a supported destination. Cancellation/failure removes only documents
created by this job and its temporary workspace; never overwrite an original
or delete unrelated files. Report any cleanup that could not finish.

## Engine and background execution

Build the pinned xdelta3 3.2.0 source as an APK-bundled Android native library,
called through JNI. Match the desktop decoder's secondary-compression support,
retain checksums and resource bounds, and use 64-bit offsets. First prove this
works against desktop-generated patches, including large files. Do not execute
downloaded binaries or extract an executable into writable app storage.
[Android executable restrictions](https://developer.android.com/about/versions/10/behavior-changes-10#execute-permission).

Run one job at a time in a dedicated app-owned worker process with a foreground
service started by a user action. Use the `dataSync` service type for download,
local processing and export, with a persistent progress/Cancel notification.
The UI reconnects to the job after rotation or navigation. Native decoding uses
bounded buffers, progress callbacks and cooperative cancellation. A fallback
stop may terminate only this app's own worker process.

Persist job steps and verified intermediate identities. After process death,
offer Resume or Discard; revalidate sources and retained results before reuse.
Resume at a verified patch boundary, not an arbitrary xdelta byte offset.
Explicit cancellation removes intermediates; interrupted-job recovery may keep
verified work until the user chooses. Handle service timeout by stopping the
worker promptly and recording an interrupted state. Long-running WorkManager
jobs are not an escape from Android execution limits.
[Service types](https://developer.android.com/develop/background-work/services/fgs/service-types#data-sync),
[timeouts](https://developer.android.com/develop/background-work/services/fgs/timeout).

Proposed modules:

| Location | Responsibility |
| --- | --- |
| `android/app` | Compose screens, service, notifications, document access and installer |
| `android/patch-core` | Pure Kotlin manifest/catalog validation, recognition and route planning |
| `android/patch-native` | Pinned xdelta source, CMake build, JNI decoding and cancellation |
| `android/app/src/androidTest/assets`, `android/patch-core/src/test/resources` | Generated synthetic binaries and desktop compatibility cases |

The initial implementation uses Kotlin coroutines/Compose state, Kotlin
serialization and OkHttp for HTTPS. SharedPreferences holds folder settings;
AtomicFile JSON records persist the single active job, its pinned catalog and
verified completion receipt. A database is unnecessary for one job at a time.
Pin compatible versions and record native source commits/notices. Keep
Android filesystem, networking and UI APIs outside the pure routing module.

## Catalog, downloads and application updates

Bundle the existing catalog in the APK and refresh the same central catalog
URL on startup. Cache only updates that pass structural, identity, URL,
withdrawal and immutability checks; otherwise retain the last valid catalog.
Pin the selected route to its catalog snapshot for the active job. Do not
change catalog schemas merely to add Android, and keep the existing hourly
server workflow independent of app releases.

Use public GitHub downloads initially, HTTPS with normal certificate checks,
bounded metadata, timeouts, explicit rate-limit errors, and verified cache
entries. Check size/hash before using downloads. No game images, saves or
licenses are uploaded. Private automatic discovery/authentication is deferred.

Check a separate Android stable feed at
`updates/android/stable.json` in this repository. Its versioned format identifies
the exact release tag, APK asset, size, SHA-256, package ID, versionName,
versionCode, minimum SDK and ABI. Validate metadata and release-asset identity,
then download only when the user chooses Update. Before installation verify
size/hash, package ID, newer versionCode and the expected signing certificate;
let Android's package installer confirm installation. Preserve app data through
same-package, same-signing-key updates. Do not promise Windows-style silent
replacement or rollback. [Installer user action](https://developer.android.com/reference/android/content/pm/PackageInstaller.SessionParams#setRequireUserAction(int)).

Use independent tags such as `android-v0.1.0`, with an Android workflow that
does not match the Windows `v*` trigger. Publish Android releases with
`make_latest: false`, and update the Android feed only after the APK is uploaded
and validated. This is necessary because the current Windows updater reads
GitHub's repository-wide `/releases/latest`. Explicitly test that it still
returns a Windows release after Android publication.
[GitHub release controls](https://docs.github.com/en/rest/releases/releases#create-a-release).

CI builds/tests unsigned or debug artifacts without publishing. Release signing
uses a backed-up owner-controlled key and protected CI secrets; never commit
the key. A separate explicitly requested release produces the signed ARM64 APK,
checksums, notices and update metadata. Google Play distribution and its AAB/
update path are deferred, not silently added to the first-release scope.

## Delivery order and acceptance checks

1. **Storage/native feasibility build.** Deliver a debug APK that selects a
   source and patch, applies xdelta and exports a verified new output. Prove
   ARM64 decoding, checksum failures, cancellation, seekable/non-seekable input,
   files over 4 GiB, 16 KB pages and bounded memory on a real phone before
   building the full interface.
2. **Catalog and route parity.** Port schema-v1/v2 and legacy handling, numeric
   version ordering, immutable/withdrawn identities, grouped solutions and
   route selection. Generate fixtures with the existing Python tests and
   require both implementations to agree, including malformed data, conflicts,
   originals/intermediates/current versions, renamed/unknown files, direct and
   chained routes, unavailable targets and edition separation.
3. **Compact usable app.** Add both tabs, remembered folder scanning, responsive
   identification, route details, downloads/cache, notifications, recovery and
   safe exports. Test zero/one/many matches, missing companion tracks, offline
   use, corrupted downloads/intermediates, low disk space and existing outputs.
4. **Device and failure validation.** Test minimum API, Android 11 storage
   restrictions, Android 14-16 service behavior, ARM64 and emulator builds,
   internal/SD/USB storage, revoked grants, rotation, screen off, process death,
   service timeout and cancellation during each stage. Include large text,
   long filenames/messages, thermal slowdown and measured hash/patch throughput.
   Prove unchanged originals and no cleanup outside the owned workspace.
5. **Update/distribution readiness.** Test signed APK upgrades preserving
   settings/cache, wrong signing keys/packages, corrupted metadata/APKs,
   unsupported ABI/SDK, declined installs, offline behavior and Windows update
   isolation. Produce a reviewable local APK and validation report. Publish
   only when explicitly requested.

The local implementation advances steps 1–3 together so both workflows can be
tried. Real-device/storage/memory measurements still determine whether the
proposed minimum-device support needs narrowing; do not claim verified support
based solely on an emulator or successful compilation.

## Later additions

- **CHD:** Android-native reader/writer, explicit extraction permission, retained
  extracted input reused for patching, and verified recompression. If the selected
  document does not grant parent-folder access, request the containing folder
  before creating the retained child folder. Never silently unpack during scans.
- **DCP:** separate feasibility work. Local desktop 0.5.19 uses a pinned .NET 8
  Universal Dreamcast Patcher process and native dependencies; that helper is
  not an Android binary. Resolve engine/runtime distribution and required
  notices/source before choosing an Android integration. Preserve game-tree,
  audio alignment and boot-code checks; do not equate rebuilt-disc hashes with
  raw-track xdelta output.
- **Save conversion:** decrypted Z3 conversion first; experimental MX later,
  retaining checkpoint limitations, favorite-series/difficulty behavior and
  user-supplied key material. MX crypto currently uses desktop OS APIs and must
  receive an independently tested Android implementation.
- **Vita PKG/rePatch:** requires an Android-capable isolated extraction and
  independent installation-verification route. Do not bypass verification,
  touch another emulator's private data, distribute licenses, or restore
  package-sized whole-PKG xdelta downloads to avoid this work.
