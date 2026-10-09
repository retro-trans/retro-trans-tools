# Changelog

## 0.5.4 — ZIP-only Vita release (2026-10-09)

- Fix 0.5.3's remaining dependency on individual Vita assets: when a ZIP is
  published, the app reads only the ZIP and profile release entries and verifies
  the patches inside the archive. Missing bare assets no longer block it.
- Catalog validation accepts complete ZIP-only inventories, records minimum
  app version 0.5.4, and retains all PS3/profile/ZIP identities. Added ZIP-only
  application and gradual bare-asset removal regression tests.
- User explicitly requested withdrawing the 0.5.2 app release and approved
  removing all 153 individual Vita patches after the new app is verified.
  Existing 0.5.2/0.5.3 Vita clients must update; PS3 cached routes are unchanged.
  Updated player instructions and work.bin guide. App 0.5.2 release and its three
  assets are withdrawn; its source tag and verified local recovery files remain.
  App0.5.4 published at09:44:59 UTC from8edfb2e after release37913041790 passed.
  Actual public EXE/ZIP/UPDATE hashes, startup and update staging pass.
- Removed exactly153 bare Vita assets after app verification, retaining recovery
  ZIP/metadata. Seven game assets, both PS3 patches and game tag are unchanged.
  Post-removal public PKG flow verifies154 payloads; catalog37913522760 and
  old PS3 cached refresh/parser checks pass. Updated release/README migration
  notices and historical0.5.3 docs; see v0.5.4-validation.md for complete evidence.

## 0.5.3 — Single Vita patch ZIP (2026-10-09)

- Historical note: 0.5.3 still required bare asset listings. The 0.5.4 change
  removes that dependency and supersedes the older-client retention below.
- Published v0.5.3 at 09:25:02 UTC from d83c504 after release run37910890752
  passed every gate. Actual public EXE/ZIP/UPDATE hashes, downloaded startup
  and isolated update staging from0.5.2 pass. Added the step-by-step work.bin
  guide; public game README/release instructions now describe the ZIP flow.
- Published the optional 15.1 MB Vita ZIP; all 159 existing game-release assets
  retain their IDs/sizes/hashes. Public ZIP + PKG/work.bin reproduces all 154
  payloads without individual patch downloads. Windows CI, live catalog and
  0.5.1/0.5.2 cached-client checks pass. See v0.5.3-validation.md for evidence.
- Prefer the verified SRW Z3 Vita patch ZIP for online rePatch creation instead
  of 153 separate patch downloads. Original metadata and individual assets
  remain available for 0.5.2 clients; PS3 patch routes are unchanged.
- Accept the same ZIP directly in Local patch, alongside existing JSON profiles.
  Resolve and verify it once before PKG conversion. Extraction rejects extra,
  missing, duplicate, unsafe, linked, oversized or corrupt entries, checks each
  patch hash, and cleans temporary files on success, cancellation or failure.
- Catalog validation checks the ZIP against the unchanged profile and records
  its immutable identity separately. Added ZIP and compatibility regressions.
- Corrected file-picker filters for Vita PKG, work.bin and ZIP/JSON inputs.

## 0.5.2 — Vita rePatch workflow (2026-10-09)

- Withdrawn at the user's request later on October 9. This section records the
  original release; its binaries are no longer public. Source tag retained.
- Published v0.5.2 at 08:55:32 UTC; release run 37907763867 passed all gates.
  Actual public EXE/ZIP/UPDATE hashes, downloaded startup and isolated public
  update staging from 0.5.1 pass. No game or license is bundled.

- Direct original PKG + matching NoNpDrm work.bin input is now implemented.
  Uses an unmodified official Vita3K download in an isolated portable workspace,
  not the development-only custom PFS helper. Publisher checksum, exact PKG
  allowlist, license identity, read locks, disk checks, safe archive extraction,
  cancellation and decrypted-file hashes are enforced. License stays local.
- The real full PKG -> rePatch flow passes all 154 target hashes, preserves both
  inputs and removes its temporary installation. Tested official archive:
  711f1ee15c1d9edcc4efdb1eb0481f94a14081e6addb346bb854af6a81188ee8.
- 181 tests run (180 pass, one opt-in online test skipped), including seven new package
  tests and all four tabs at normal/150%/200% scaling. Added detailed work.bin,
  privacy, temporary-space and device-copy instructions.
- User explicitly approved the separate SRW Z3 v0.9.0 Vita patch extras and
  sanitized executable permission metadata. Published 153 bare deltas plus the
  profile, preserving all five PS3 assets. Public README and release instructions
  now describe PKG/work.bin input. All 154 actual public downloads and target
  payloads pass; live catalog, old cached refreshes and v0.5.1 parser checks pass.
- Catalog builder validates the separate Vita profile and every listed delta,
  rejects undeclared/corrupt/missing/replaced extras, and records its immutable
  discovery metadata without changing any PS3 patch identities or routes.
- Fixed the reparse-point test fixture to canonicalize Windows CI's short
  temporary paths, so its injected junction metadata matches the checked path.
  The production path/link guards are unchanged; no test was skipped or relaxed.
- Windows CI, standalone startup and packaged next-launch update checks pass.
  See docs/releases/v0.5.2-validation.md for exact evidence and runtime limits.

### Earlier local development stages (superseded by the completed workflow)

- Earlier preflight held the release pending the PKG + work.bin workflow.
  The existing local PFS helper depends on Vita3K/psvpfsparser at
  d14381f871a69009bd18b2aaec2213a6738bebba. Its repository and upstream
  motoharu-gosuto/psvpfstools provide no license declaration found during review;
  redistribution permission was not established. The helper was not bundled;
  PKG input was not yet implemented and no publication happened at that stage.
  Fast-forwarded the local base to 33718ba, retaining current public catalog data.

- Added a compact native Vita rePatch tab for PCSG00264 v01.00, a reviewed local
  profile selector, and verified optional-release downloads when published.
- Added declarative nested-file patching, sanitized auth validation and matching
  against the output executable, strict path/link checks, input preservation,
  staged output, cancellation and digest verification. No package scripts run.
- Added 13 backend tests and GUI worker/layout coverage; 172 tests pass with
  one opt-in online test skipped. Real test18 integration matches all 154
  previously verified hardware payloads. No game build or installation.
- At that earlier stage, app version/public releases/catalog were unchanged;
  the metadata/deltas and app update remained local pending publication approval.
- Packaged a standalone local test EXE; offline startup/engine checks pass
  with the new fourth tab. It uses the reviewed sidecar profile automatically.
# 0.5.5 Mac feature-parity candidate (unreleased)

- Added Apple Silicon/Intel Mac app packaging and a read-only test-build
  workflow; no release, tag or main-branch publication. Windows packaging and
  update protocol remain unchanged.
- Native verified xdelta/chdman, Finder output folders and bundle-aware scanning;
  native CommonCrypto AES/CMAC for the existing experimental MX profile.
  Existing PPSSPP EXE key input is read as data, never executed on Mac.
- Official architecture-specific Vita3K DMG verification, read-only mounting,
  isolated portable conversion and input revalidation. No game/license CI upload.
- Whole-app Mac updates with independent per-architecture metadata, archive
  boundaries, startup checks and previous-app rollback. Added Mac-specific tests
  and enabled shared GUI, patch, CHD and cryptography tests on macOS.
- Validation is in progress. Real PKG/work.bin conversion and physical-console
  gameplay require separate user testing; do not infer them from CLI startup.
- First Windows regression passes192 tests/3 expected skips. Initial native Mac
  run exposed root-owned /var aliases and Windows-specific test doubles; allow
  only macOS's fixed /private aliases, retaining descendant symlink rejection.
  Added real packaged next-launch helper coverage and startup-exception rollback.
- Mac package conversion rechecks both PKG and work.bin after conversion;
  external Vita3K does not inherit app-specific dynamic-library overrides.
  Added architecture-specific update download/tampering tests.
- Both native suites now pass193 tests/3 expected skips; Apple Silicon app
  startup and real next-launch updater pass. The Vita3K DMG smoke check exposed
  a second /var versus /private/var identity comparison; mount checks now compare
  resolved paths. External conversion processes also drop GitHub API tokens.
- Mac bundles declare the build host's macOS major version as their minimum,
  matching their tested native dependencies; metadata and installation guide
  expose that requirement rather than relying on Python's older default.
- Mac UI keeps native system fonts instead of requesting Windows-only Segoe UI.
