# Vita rePatch — SRW Z3 Jigoku-hen

**Original PKG + matching work.bin → Create rePatch → copy to Vita.**

Creates a physical-Vita overlay for **PCSG00264 v01.00**. It is not a Vita3K
installer or a replacement for installing your original game. Only the exact
original digital PKG is accepted: 2,338,423,472 bytes, SHA-256
`3a13c11c0097ea8faa864c03add89cf7fb6e9c10bce352396ce105df884ac2fd`.

## Players

1. Open **Retro-Trans.exe → Vita rePatch** on an x64 Windows 10/11 PC.
2. Select your original **PKG** and its matching NoNpDrm **work.bin**. No
   decrypted game folder, Python, terminal commands, firmware download, or
   configured Vita3K installation is needed.
3. Browse to the parent where a **new** output folder should be created. Keep
   at least **6 GB free** on that drive for temporary extraction/verification.
4. Leave **Local patch** blank to download the published patch automatically.
   Retro Trans **0.5.4 or newer** downloads one verified
   `SRW-Z3-v0.9.0-Vita-patches.zip`. Alternatively, select that ZIP directly in
   Local patch—no manual extraction needed. A reviewed `VITA-REPATCH.json`
   with its `.xdelta` files beside it remains supported. No package scripts run.
5. Click **Create rePatch**. The app downloads the official Vita3K Windows tool
   directly from its publisher, verifies it, and converts your PKG inside an
   isolated temporary portable folder. It then applies and verifies the patch.
   Keep internet access for tool metadata and uncached downloads. Conversion
   can take several minutes. Wait for successful verification.
6. Close the game, back up saves and the previous overlay, and copy the output's
   `rePatch/PCSG00264` to `ux0:rePatch/PCSG00264` using VitaShell. Do not merge
   old mods or overwrite `ux0:app`, official updates, or savedata. Keep at least
   500 MB free on the Vita, plus backup space. Launch the existing game with
   compatible rePatch installed. Test a spare save slot first.

The reviewed sanitized `self_auth.bin` is generated from patch metadata. Users
do not need to supply a personal auth dump. This file holds the executable's
authority ID/capabilities/attributes; padding and the full shared-secret region
are zero. It is not a replacement for owning/installing the original game.

To disable, close the game and move the game's overlay out of `ux0:rePatch`.
Disabling an overlay does not revert saves made while testing.

## Finding your work.bin

Use the **NoNpDrm license from your own matching game**, not the original
account-bound PlayStation Store license. With NoNpDrm installed, launch your
owned game once. Its generated license is under
`ux0:nonpdrm/license/app/PCSG00264/6488b73b912a753a492e2714e9b38bc7.rif`.
Copy that file to your PC as `work.bin`. A correctly prepared NoNpDrm backup
already has this replacement at `PCSG00264/sce_sys/package/work.bin`.
See the [NoNpDrm instructions](https://github.com/TheOfficialFloW/NoNpDrm#creating-the-fake-license).
For a step-by-step walkthrough, see [Getting work.bin](VITA_WORK_BIN.md).
Retro Trans checks its size, type and full content ID, then verifies actual
decrypted file hashes. Matching headers alone are not proof of decryption.

## Package conversion privacy

No PKG, game files, license or saves are uploaded. Network requests obtain
public tool/patch metadata and downloads only. PKG and work.bin are held
read-only during conversion. The user's real emulator setup is not used.

The official installer accepts its encoded license through local process
arguments. It can be visible briefly to same-user or administrator process
inspection. Do not collect/share process dumps during conversion. Arguments
and raw installer output are never logged by Retro Trans. Temporary license
copies and installer logs are removed with the workspace after normal
completion, cancellation or failure. Power loss or forced app termination may
leave `.retro-pkg-*` folders beside the output; treat them as private and remove
them once no conversion is running.

The official Vita3K archive is downloaded directly and remains unmodified;
Retro Trans does not redistribute the development-only custom PFS helper.
Upstream downloads are checksum-verified and decrypted game hashes are always
checked, even when the upstream process reports success. The source-folder
backend remains available to developers for local tests.

## Implementation and publication boundary

The optional `VITA-REPATCH.json` uses schema `retro-trans-vita-repatch-v1`,
independent of the existing v1/v2 disc catalog. No existing catalog identities,
PS3 routes, published manifests, or schema-v2 flat-filename safeguards change.
The dedicated tab is not Automatic disc patching. The catalog builder verifies
the separate Vita inventory and records `vita_repatch` discovery metadata on
the existing release. Old clients ignore that additional field and retain their
unchanged PS3 routes. Once recorded, the profile identity cannot be replaced.

The online loader currently targets `retro-trans/SRW-Z3` tag `v0.9.0`. Version
0.5.4 uses its exact metadata asset and patch ZIP; no individual delta assets
are required. It verifies GitHub asset digests, sizes and every patch inside
the ZIP, then reuses the hash-checked download cache and bundled xdelta engine.
The extras were explicitly approved and initially published as bare deltas on
October 9, 2026, followed by the approved ZIP-only migration. Absent metadata
produces an explicit unavailable message;
it cannot silently use another build. The user approved the sanitized fixed
permission metadata separately; this is not permission to publish raw auth
dumps, licenses, game packages, or complete game files. App release and extras
still require their public-download/catalog regression gates.

Version 0.5.4 uses the single ZIP without requiring individual release assets.
Version 0.5.3 preferred the ZIP but still checked for all bare deltas; upgrade
to 0.5.4 or newer for the ZIP-only release. The ZIP's publisher checksum and
size are verified, then its flat inventory must contain exactly the unchanged
profile and every declared delta, with matching sizes and hashes. Unsafe paths,
links, duplicate names, extra files and oversized contents are rejected before
use. Extraction is temporary. The catalog records the ZIP separately as
`vita_archive`; existing `vita_repatch` and PS3 identities are unchanged.
All 153 individual Vita assets were retired with explicit user approval after
0.5.4 was published and verified. Old 0.5.2/0.5.3 online Vita clients must update; their
PS3 patch routes and cached catalog refreshes remain unchanged. No cache reset
is needed. If a release has no ZIP, the new app retains the verified individual
route; a present but invalid ZIP fails validation instead of falling back.

Every declared nested file has source/target SHA-256 and size plus the delta's
identity. Only `eboot.bin` and `.cpk`/`.bin` under `DATA` or `CommonData` are
allowed. Traversal, Windows device names, case-colliding outputs, symlinks and
junctions are rejected. Input hashes are checked before patching and again
before output publication. The patched executable's authority ID must match
the sanitized auth. All outputs are staged, verified and published into a new
folder; cancellation/failure does not leave a usable partial overlay. Nothing
from a user's unrelated files, licenses, modules or saves is copied.

## Local validation

- Full suite: 181 tests, one explicitly opt-in online test skipped.
- Real Z3 test18: all 153 xdelta outputs plus sanitized auth (154 payloads)
  match the existing verified physical-Vita build byte for byte.
- Input files remain unchanged; no Vita installation performed. Only the
  explicitly approved deltas and sanitized profile are published.
- Real original-PKG conversion additionally matched all 153 required source
  files; the complete PKG-to-overlay flow matched all 154 output payloads,
  preserved PKG/work.bin and removed its temporary installation. Tested official
  runtime archive SHA-256:
  `711f1ee15c1d9edcc4efdb1eb0481f94a14081e6addb346bb854af6a81188ee8`.
- Standalone Windows test EXE passes its offline startup diagnostic with all
  four tabs, bundled xdelta, CHD round trip and existing save-conversion checks.
- Physical runtime remains unverified by this integration. The Vita staff roll
  and ending teaser remain Japanese; matching shared text is not PS3 parity.
