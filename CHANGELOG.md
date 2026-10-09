# Changelog

## 0.5.2 — Vita rePatch workflow (2026-10-09, release preparation)

- Direct original PKG + matching NoNpDrm work.bin input is now implemented.
  Uses an unmodified official Vita3K download in an isolated portable workspace,
  not the development-only custom PFS helper. Publisher checksum, exact PKG
  allowlist, license identity, read locks, disk checks, safe archive extraction,
  cancellation and decrypted-file hashes are enforced. License stays local.
- The real full PKG -> rePatch flow passes all 154 target hashes, preserves both
  inputs and removes its temporary installation. Tested official archive:
  711f1ee15c1d9edcc4efdb1eb0481f94a14081e6addb346bb854af6a81188ee8.
- 179 tests pass (one opt-in online test skipped), including seven new package
  tests and all four tabs at normal/150%/200% scaling. Added detailed work.bin,
  privacy, temporary-space and device-copy instructions.
- User explicitly approved the separate SRW Z3 v0.9.0 Vita patch extras and
  sanitized executable permission metadata; publication/verification pending.
- Catalog builder validates the separate Vita profile and every listed delta,
  rejects undeclared/corrupt/missing/replaced extras, and records its immutable
  discovery metadata without changing any PS3 patch identities or routes.

- Earlier preflight held the release pending the PKG + work.bin workflow.
  The existing local PFS helper depends on Vita3K/psvpfsparser at
  d14381f871a69009bd18b2aaec2213a6738bebba. Its repository and upstream
  motoharu-gosuto/psvpfstools provide no license declaration found during review;
  redistribution permission has not been established. Do not bundle the helper
  or advertise direct PKG input as implemented. No version/tag/push/release yet.
  Fast-forwarded the local base to 33718ba, retaining current public catalog data.

- Added a compact native Vita rePatch tab for PCSG00264 v01.00, a reviewed local
  profile selector, and verified optional-release downloads when published.
- Added declarative nested-file patching, sanitized auth validation and matching
  against the output executable, strict path/link checks, input preservation,
  staged output, cancellation and digest verification. No package scripts run.
- Added 13 backend tests and GUI worker/layout coverage; 172 tests pass with
  one opt-in online test skipped. Real test18 integration matches all 154
  previously verified hardware payloads. No game build or installation.
- App version, public releases and existing catalog are unchanged. The Vita
  metadata/deltas and app update remain local pending publication approval.
- Packaged a standalone local test EXE; offline startup/engine checks pass
  with the new fourth tab. It uses the reviewed sidecar profile automatically.
