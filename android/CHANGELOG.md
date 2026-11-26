# Android changes

## 0.1.0-test2 — 2026-11-02 (local debug APK, not published)

- Add experimental Android-native DCP application and a separate DCP tab.
- Recognize both Black/Matrix AD original disc sets through the independent
  `dcp_releases` catalog records; retain ordinary binary/multi-file xdelta routes.
- Download only the selected verified DCP on Patch. Local DCP mode works offline.
- Stage document-provider originals read-only; verify complete source/target
  game-file identities, target boot data, preserved audio and exported bytes.
- Produce three-track GDI with a cooked 2048-byte high-density data track. Keep
  existing ISO extents unless a file grows; allocate growth only in proven-zero
  unreferenced space. Preserve original low-density data and non-silent audio.
- Fail closed on unsupported formats, missing tracks, unsafe ZIP paths/symlinks,
  additions, mismatched hashes, corrupt output, cancellation and existing exports.
- Keep CHD, other disc layouts and universal DCP rebuilding out of this first
  implementation. No desktop helper/runtime is embedded; no game data is bundled.
- Add synthetic JVM/device/SAF export tests and opt-in real-disc tests; real disc
  images and full outputs stay local. Do not interpret integrity tests as gameplay
  or real-phone compatibility claims.

Test1 and issued desktop releases/patch assets are preserved. This task does not
create a tag, release, upload, public catalog change or production Android feed.
