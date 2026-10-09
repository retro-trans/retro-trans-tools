# Changelog

## 0.5.3 — Single Vita patch ZIP (2026-10-09)

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
