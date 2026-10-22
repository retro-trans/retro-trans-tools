# Changelog

## 0.5.18 — Accurate app version and update status

- Always show the running app version in About. Read update history when the dialog opens so a late update-helper result is visible, and suppress success messages belonging to a different executable version.
- Clear an earlier update-check error after a successful check while retaining current download notices and installation failures. Malformed history safely uses the default message without modifying diagnostic records.
- Include the latest verified catalog and the catalog validation improvements documented below.
- Validation: the 280-test suite passes with four platform-specific skips; packaged Windows startup and next-launch update checks pass, including backup and settings preservation.

## Unreleased — Resilient catalog refresh and generic Vita extras

- Deployment verified: full hosted refresh succeeded with 77 releases, zero rejections and unchanged existing patch/binary/solution identities. Cross Ange v0.1.13 plus two blocked Macross Triangle Frontier releases are now cataloged. Hosted CI checks passed. See docs/catalog-refresh-repair-deployment.json.

- Validate generic Vita rePatch profiles/ZIPs, including Cross Ange's asset-only overlay and bounded credits/font attribution, alongside standard binary manifests. Preserve the stricter legacy/new Z3 policy and all existing integrity checks.
- Scheduled unscoped refreshes isolate rejected releases/repository fetches, keep cached verified entries, continue other releases and upload a JSON rejection report with workflow warnings. Explicit scoped refreshes remain strict; cancellation and global integrity errors remain fatal.
- Validate and download every checksummed supplemental asset rather than rejecting valid credits/check reports or omitting checksum lines. Standard VALIDATION.json remains mandatory and bound to the exact manifest; custom CPK evidence is not a substitute.
- Regression checks cover generic overlays, damaged/undeclared credits, immutable metadata, supplemental checksums, per-release/repository isolation, cached identities, cancellation and report safety. Full suite: 276 tests with four platform skips.
- Live validation continued past Cross Ange's missing standard proof, then accepted both Cross Ange and a healthy repository using staged metadata. All 74 existing records stayed immutable; the candidate has 75 releases. The user explicitly approved the source push, existing-release metadata repair and full hosted refresh on 2026-10-19. No app release is needed.


## 0.5.17 — Larger complete Vita3K profiles

- Raise the bounded Vita PKG JSON reader from 128 KiB to 256 KiB so Z3's
  complete 589-file original inventory and 160 component deltas can be verified.
  Keep ZIP size, path safety, license exclusion and all hash checks unchanged.
- Add complete-profile, exact-boundary, oversized compressed ZIP and mismatched
  component-source regressions. Existing PS3 and hardware rePatch routes stay
  unchanged.
- Local verification: all 264 tests pass (four platform skips); standalone
  health check and isolated next-launch update preserve startup, backup and
  settings. Source and standalone EXE both rebuild Z3 and verify all 589
  native-installed files, producing the same complete PKG hash. Original PKG
  and matching license are unchanged. Full gameplay remains untested.
- User authorized the scoped source push and Windows release. See
  docs/builds/v0.5.17-validation.json for local proof; game patch publication
  is separate from this app release.

## Unreleased — Z3 combined-release catalog validation

- Permit reviewed Z3 numeric releases after the legacy v0.9.0 profile to carry a hash-verified Vita rePatch ZIP alongside their PS3 manifest. Require matching release/build versions, PCSG00264 original-PKG identity, the discoverable ZIP suffix and Retro Trans 0.5.16. Keep the legacy profile, downloads and cached PS3 routes immutable.
- Reject missing, ambiguous, corrupt or replaced Vita profiles/ZIPs. This catalog-only change does not publish a new app version or change existing downloads.
- Validation: all 260 tests pass (four platform-specific skips), including 14 catalog-builder tests and legacy/new-release cached-refresh checks.

## 0.5.16 — Small-download local PKG Automatic

- Publish the Windows app at the user's request. Automatic downloads small component patches, decrypts the original locally using its matching work.bin/.rif, then rebuilds and verifies an English PKG. Cross Ange's translation download is about 5.4 MB; the native runtime downloads separately on first use. Allow 6 GB temporary space.
- Generic hardware rePatch discovers profiles by game identity; added credits/font attribution and every output are hash-verified. Retain manual CPK patching, ordinary binary routes, CHD and save conversion. Never download or bundle licenses or package-size whole-PKG deltas.
- Handle transient Windows sharing locks safely, preserve originals/licenses/emulator data/saves, and retain GitHub CLI access for private profiles. Public releases work without sign-in, subject to GitHub's anonymous request limits.
- Validation: 257 tests with four platform skips; frozen Automatic and actual UI rebuilt Cross Ange's exact English PKG, each verifying all 48 installed files. Full gameplay and physical-Vita testing remain outstanding. See the local proof and release validation records.

## 0.5.15 — Return to installed CPK patching (local)

- Verification: the 251-test suite passed with four platform skips; frozen startup reports installed CPK patching and disabled whole-PKG support. The actual Apply xdelta UI produced Cross Ange's exact complete English CPK; optional metadata and credits/font extras also passed. See `docs/builds/v0.5.15-local-validation.json`. Previous app bundles are archived outside dist.

- Withdraw local whole-PKG builds 0.5.12–0.5.14 and remove their Automatic, Vita3K PKG and CLI patch routes. PKG selection now explains original installation and installed CPK input; hardware rePatch and ordinary binary/manual patching remain available.
- Keep the existing published tools 0.5.4 available for Apply xdelta. Original-game installation requires the matching license; CPK patching does not. No new tools release or source push is authorized by this update.
- Preserve historical proof records and a local source snapshot of the withdrawn route. Existing game installations, licenses and saves are untouched.

## 0.5.14 — Generic hardware rePatch discovery (local build)

- Verification: 270 tests passed with four platform-specific skips. Frozen startup and the published Cross Ange hardware route passed, including isolated native extraction, all three overlay files, unchanged original PKG and license, and no executable/authentication replacement. See `docs/builds/v0.5.14-local-validation.json`. Physical-Vita gameplay remains untested.

- Discover hardware rePatch profiles and ZIPs by original PKG identity, with private GitHub access and a legacy Z3 fallback. Keep hardware extraction's matching local license separate from license-free whole-PKG patching.
- Support asset-only overlays without an executable/authentication replacement, plus bounded, hash-verified added credit pictures and attribution text. Retain executable authentication requirements when an executable changes.
- Add the hardware CLI route, clearly require the same game's work.bin at installation, and preserve source files, licenses, emulator configuration and saves. This app build remains local and is not published.

## 0.5.13 — Hardware candidate superseded locally

- The initial generic hardware candidate passed 268 unit tests and startup, but its real published Cross Ange test was blocked by an unrelated legacy Z3 profile's internal build label. Superseded by local 0.5.14, which filters game identity before enforcing matching release versions and includes a regression. This candidate was not published.

## 0.5.12 — Whole-PKG patching without a license (local test build)

- Verification: 260 tests passed with four platform-specific skips; frozen Windows startup and absence of PKG license inputs passed. The packaged executable applied Cross Ange's local whole-PKG ZIP without a license argument and reproduced the previously native-verified English package exactly, preserving the original. See `docs/builds/v0.5.12-local-validation.json`.
- Automatic and Vita3K PKG now apply xdelta directly to encrypted package bytes. Remove the license input and license CLI argument from this route. The user's matching work.bin/.rif is needed separately when installing the output in Vita3K.
- Add generic VITA-PKG-XDELTA.json profiles and whole-PKG ZIP discovery, exact source/delta/output size and SHA-256 checks, safe ZIP extraction, cancellation and collision-safe output publication. Preserve hardware rePatch as a separate license-based extraction flow.
- Reject the old per-file PKG profiles in the new route. Automatic downloads require a published whole-PKG profile; local testing uses Vita → Vita3K PKG → Local patch.
- Keep v0.5.11 withdrawn. This build and Cross Ange's approximately 945 MB test delta remain local; no new release is authorized.

## 2026-10-12 — Withdraw v0.5.11

- Removed the GitHub release and its EXE, ZIP and update-metadata downloads at the user's explicit request. This version required a matching local license during Vita PKG patching.
- Retained the source tag, prior validation records and local builds. Older releases are unchanged; v0.5.4 is now the latest published release and does not support the withdrawn Automatic Vita PKG route.
- Marked the Vita instructions as historical. A whole-PKG xdelta replacement has not been published.

## 0.5.11 — Vita packages in Automatic

- Verification: 247 tests passed with four platform-specific skips; frozen Windows health checks and 150%/200% Vita-field layout checks passed. The actual Automatic UI worker downloaded the private Cross Ange ZIP without a local patch selection and verified all 48 installed files in the completed 0.1.13 PKG. See `docs/releases/v0.5.11-validation.json`.
- Automatic now detects original supported Vita PKGs through Browse, Folder and app-folder Scan. It shows the Vita title ID and latest compatible Vita3K PKG route, reveals the matching license field and downloads translation assets only when Patch is clicked.
- Reuse generic release discovery, original identity checks, encrypted package rebuilding, isolated native installation verification and Windows file-lock retries. Public/private download behavior is the same as the Vita tab.
- Keep ordinary binary, PS3, CHD and grouped-file routes unchanged. Clear the license on input changes, keep Vita selection across unrelated catalog refreshes, and preserve local patch/hardware options in the Vita tab.

## 0.5.10 — Retry temporary Vita file locks (local test build)

- Verification: 242 tests passed with four platform-specific skips; frozen health checks passed. The packaged automatic conversion completed all 48 installed-file checks while a real Windows handle denied temporary CPK deletion, then retried and removed its workspace after the lock was released. See `docs/releases/v0.5.10-validation.json`.
- Retry Windows sharing and lock violations while verifying Vita files and cleaning up owned PKG workspaces, with a bounded 12-second wait. Cancellation remains available during file verification. Ordinary permissions, missing files, disk errors and incorrect hashes still fail immediately.
- Preserve the original conversion, verification or cancellation exception when cleanup also fails. If only cleanup fails after a verified output was saved, explain that the completed output is usable rather than exposing a misleading raw WinError 32.
- Do not stop a user's Vita3K instance or operate on existing emulator data. Cleanup remains limited to the current operation's generated temporary directory.

## 0.5.9 — Automatic Vita translation downloads (local test build)

- Verified the frozen Windows app without a local patch argument: automatic discovery and authenticated private-release download, encrypted PKG conversion, and all 48 installed Cross Ange file hashes passed. The output matched the independently verified 0.1.13 package. The 236-test suite passed with four platform-specific skips; frozen health checks passed.

- The Vita3K PKG flow now works with only an original PKG, matching license and new output filename. Leave Local patch blank to identify the game and download its translation ZIP automatically from Retro Trans releases.
- Match exact content identity, original size and full SHA-256, then choose the newest matching published stable profile among each project's ten recent releases. Verify publisher asset checksums and require the downloaded ZIP profile to match published metadata. Other games need profiles, without a hardcoded game registry.
- Keep local ZIP/JSON selection for offline use or unavailable releases. Explain missing profiles, wrong original revisions, competing projects and PS3 PKGs before rebuilding; PS3 users are directed to Automatic.
- Private releases can use an existing local GitHub CLI sign-in or GH_TOKEN/GITHUB_TOKEN. No credentials are bundled, stored in files or logged; authentication is stripped on cross-host asset redirects. Original packages and licenses stay local.
- Retain existing hardware rePatch behavior. This is a local app build; no application push or release publication is requested.

## 0.5.8 — Generic Vita release profiles (local test build)

- Verification: 226 tests passed with four platform-specific skips, frozen Windows health checks passed, and the packaged app converted Cross Ange's release ZIP to a PKG whose 48 installed files and full package hash matched an independently verified build. A second title's synthetic PKG and hardware profiles passed. See `docs/releases/v0.5.8-validation.json`; gameplay and hardware execution remain untested.

- Renamed the Vita tab and added destination selection: translated Vita3K PKG or hardware rePatch. Game identity, source edition, inventories and extras come from the selected release profile. The PKG route has no Cross Ange registry or permanent game-specific UI.
- Added `retro-trans-vita-pkg-v1` profiles and strict ZIP readback; future games using the supported native format can supply profiles without changing application code. Retained standard two-file Automatic compatibility for Cross Ange.
- Rebuild encrypted PFS v5 and Vita key-type-2 PKGs, then verify a second isolated official Vita3K installation and every complete game-file hash before saving. Validate outer and authenticated inner paths before extracting arbitrary profile-pinned originals. Unsupported encryption formats fail explicitly.
- Use only user-provided matching NoNpDrm licenses; no automatic license downloads or uploads. Preserve packages, licenses, real emulator settings and saves. Native logs and subprocess arguments are not recorded.
- Retained the Z3 automatic hardware route. Local hardware profiles can identify other titles; their output directory and instructions use that title. Generic PKG inputs also declare and verify original package identity.
- Added cryptography and full dependency notices, packaged native-format resources, frozen-app crypto checks and generic-profile/UI regressions. PKG rebuilding is Windows-only; Cross Ange installation is tested separately from gameplay and physical-Vita compatibility.
- Preserved the earlier uncommitted 0.5.7 diagnostics work. No Retro Trans app push or release publication is implied by this local build.

## 0.5.7 — Local diagnostics (unreleased)

- Add bounded per-session JSON-line logs and an Open logs button on Windows
  and Mac. Record versions, operation IDs, phases, network/cache decisions,
  Vita automatic/local input mode, archive lifecycle, installer exit status,
  and distinct missing/size/hash file-check failures.
- Capture error types, numeric codes and code locations without raw exception
  text, private paths, URL parameters/headers, subprocess output/arguments,
  license contents, keys or saves. No automatic upload. Logging failures do
  not stop operations; retain five sessions with one 512 KiB backup each.
- Source change only; no build, push or release publication requested.

## 0.5.6 — Mac HTTPS test fix (2026-10-09)

- Supersedes the 0.5.5 Mac test build: bundle certifi CA roots so secure GitHub
  downloads do not depend on certificates installed on the build machine.
  Certificate and hostname verification remain required; Windows trust is unchanged.
- Add distinct certificate, TLS, DNS and timeout messages instead of hiding every
  connection failure behind the generic GitHub message.
- Add a frozen-app test of the actual catalog, Vita patch ZIP and official Vita3K
  download with host CA paths unavailable. No game/license inputs go to CI.
- Both Mac architectures and Windows pass 200 tests in workflow 37950148961.
  Frozen Mac checks verify the catalog, all 153 patches inside the public ZIP,
  and official Vita3K DMGs with zero host CA roots and 121 bundled roots.
- User-authorized Mac test extras and checksums are attached to v0.5.4 with
  installation/limitation notes. Public downloads are reverified; the release
  tag and all three Windows asset IDs, bytes and hashes are unchanged. No Mac
  updater metadata was added to the older release. See the 0.5.6 validation note.
- Real-game Mac PKG conversion and physical-Vita gameplay remain unverified.

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

- Test builds completed on Apple Silicon and Intel, source7af3856; workflow
  37947388822 passes all three runners (193 tests/3 expected skips each).
  Packaged startup, whole-app and real next-launch updates, native tools and
  official Vita3K CLI pass. Downloaded both artifacts and verified sizes/hashes.
  See docs/releases/v0.5.5-macos-test-validation.md. Real Mac PKG/work.bin testing
  is still pending; no release/tag/main merge or Windows publication change.
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
- Initial validation was in progress; final test-build evidence is above.
  Real PKG/work.bin conversion and physical-console
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
