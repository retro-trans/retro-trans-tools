# Game release standard

Each game release publishes exactly one `BUILD-MANIFEST.json`, the xdelta assets
it lists, `SHA256SUMS.txt`, and `VALIDATION.json`. Optional texture packs, source
archives, screenshots and documentation are separate assets. Do not include any
original or complete translated game binaries in the release directory.

Single-file releases use `schema/game-release-v1.schema.json`; releases declaring
multi-file solutions use `schema/game-release-v2.schema.json`. The shared
validator additionally checks unique asset names, matching release tags, asset
sizes and hashes, round-trip reports, and immutable binary identities.

## Build a release locally

Install Python 3.12+ and this package:

```powershell
python -m pip install git+https://github.com/retro-trans/retro-trans-tools.git@v0.2.0
python -m retro_trans.release build release-local.json --out release-v1.2.0
python -m retro_trans.release validate release-v1.2.0
```

Copy `examples/release-config.json` and supply the actual source commit and local
file paths. Paths resolve relative to the configuration file, not the working
directory. Keep this local configuration outside your game repository or ignore
it. The builder never puts local paths into the published manifest.

One configuration can contain a full patch from the original and any number of
upgrade patches from known translated versions, for multiple editions. Every
entry names its exact source and desired target file. The builder hashes both,
encodes the patch, decodes it to a temporary file, verifies the entire target,
and rechecks that its inputs did not change during the build. It stops before
producing a final release directory if any operation fails.

For releases containing separate platform editions, a patch row can override
`platform` and `game_name`. Omitted fields inherit the manifest defaults. Keep
the release's stable `game_id` and distinct edition IDs; each edition has its
own source/output identities and upgrade route. This allows one release tag
to list bare PSP and PS2 xdelta files with accurate catalog labels. Older apps
can still apply these files manually; update the app for platform-specific
Automatic labels. Existing patch bytes and binary identities must be preserved
when adding another edition to a published release.

The release directory must not already exist. Inputs are never modified. Large
files are streamed; allow disk space for the target verification copy and patch
assets. Temporary verification images and private configuration are not release
assets. The build report is evidence from the local round trip; GitHub validation
checks its agreement with the manifest and assets, and does not itself run a
game-specific round trip without the original binaries.

For CHD-compatible releases, build patches against the exact unpacked ISO/BIN
and record that disc's format, full hashes and size. Do not substitute hashes
of a compressed CHD. The app handles supported CHD extraction/recompression
separately; include SHA-1 alongside required SHA-256 when available to enable
fast DVD CHD selection. Extracted bytes are still verified before patching.
Multi-track/audio and GD-ROM conversion are not supported by this contract.
Unpacked multi-track sets can use the multi-file solution contract below.

## Manifest fields

| Field | Meaning |
| --- | --- |
| `schema_version` | Integer `1`, or `2` for multi-file solutions |
| `game_id` | Stable lowercase slug; never reuse it for another game |
| `game_name` | Display name |
| `platform` | Console/platform label |
| `version` | Numeric stable target version, such as `1.2.0` |
| `source_commit` | Full 40-character commit identifying the game translation/tool sources |
| `patches` | Nonempty list of compatible source-to-target patches |

Each patch requires `patch` (unique release asset filename), `edition`,
`language`, `source_version`, `source_format`, `target_format`, `source_sha256`,
`source_bytes`, `target_sha256`, `target_bytes`, `patch_sha256`, and `patch_bytes`.
Use `original` for an untranslated source version. The target version comes
from the release-level `version` field. The GitHub tag must match that version,
optionally prefixed with `v`. Formats are lowercase extensions without a dot,
such as `iso`, `bin`, or `vpk`; patching always operates on exact file bytes.

The stable identity of a published binary is game + edition + language + version.
All patches producing that identity must agree on its size and hash. A local
test build with different bytes is a different version, even if the in-game
title has not been changed. Do not overwrite published patch files or reuse a
version for corrected bytes. Publish a new version instead. Downgrades are
possible only when a release explicitly provides a reverse-compatible edge.

`SHA256SUMS.txt` covers the protocol assets: patches, manifest and validation
report. Optional extras may provide their own separate checksum file.

## Multi-file patch solutions (manifest v2)

Use this when several binaries must be patched together, such as Marionette
Handler 2's raw Track 3 and Track 17. The existing `patches` rows still describe
individual xdelta operations with their complete source/target identities.
Keep a distinct, stable component `edition` for each track; do not encode a
file set as alternatives under one edition or infer dependencies from names.

Add `solutions` to the local builder configuration (see
`examples/multi-file-release-config.json`). The builder emits schema version 2
automatically. Use Retro Trans Tools 0.4.1 or later (or `python -m pip install .`
from an updated checkout). Each solution contains:

| Field | Meaning |
| --- | --- |
| `id` | Stable lowercase slug, unique within game and language |
| `name`, `edition`, `language` | Human-readable solution name, disc edition and language |
| `files` | At least two required components, each with `edition` and `output_name` |
| `copy_files` | Optional unchanged files, each with published `name`, `bytes` and `sha256` |

A component references the patch rows with its edition and the solution's
language in this release. All those rows must produce identical target bytes.
Multiple incoming rows can provide full and incremental routes for a component.
The solution's target version is the manifest's version. Keep its set of
component identities stable across versions; use a new solution ID if that set
changes. Output names are flat Windows-safe filenames, unique without regard
to case across both lists. Paths, subfolders and device names are rejected.

In the local configuration only, an unchanged file has `name` and `source`
(a local path). The builder replaces `source` with its SHA-256 and byte count,
and rechecks it after all xdelta round trips. It never packages the unchanged
game files, full target binaries, or local paths. Include **every** unchanged
track and the original CUE/GDI in this list to produce a complete disc folder.
Ensure the descriptor refers to the exact declared output filenames. The
example lists only a few unchanged files; extend it for the actual disc.

In Automatic mode, select the folder, a required track, or its CUE/GDI. Required
components are found by size and hash, so patched inputs can be renamed. The
unchanged files must retain their declared names. Only immediate children are
scanned. Missing or duplicate matching components disable patching; put one
copy of each input in the chosen folder. Grouped components are not offered
individually in Automatic mode. Manual Apply xdelta remains available.

Latest selects the newest solution reachable by **all** components. Next version
only selects the earliest newer set requiring at most one xdelta per component.
Specific versions use explicit compatible routes. Mixed input versions are
allowed; already-current or byte-identical components are verified and copied.
Route details list the source file and full patch chain for every component.
Each component route prefers fewer operations, then smaller downloads.

Patch revalidates all sources, checks space for the complete output plus
intermediates, verifies and copies the declared unchanged files, then applies
and verifies every xdelta step. The app stages the entire set on the output
drive and publishes a new folder only after every component succeeds. Existing
destinations are refused, originals are preserved, and cancellation/failure
removes the staged folder. Unrelated source files are never copied. Multi-file
CHD extraction/recompression and descriptor rewriting are not included.

The catalog generator validates v2 releases using the same uploaded-asset and
round-trip-report checks as v1. Published solution membership, output names and
unchanged-file identities are immutable. Withdraw a solution with all its
component records together, preserving its definition in `withdrawn_releases`.

Clients older than 0.4.1 reject these manifests and retain
their previous catalog; their separate app update check continues. Release the
updated application before publishing v2 game manifests. Existing v1 releases
remain valid single-file releases. Do not silently guess a group from a list
of xdelta assets or replace historical patch bytes; add explicit reviewed
metadata or publish a new version with a v2 manifest.

## Publishing and catalog updates

Publish to the relevant public repository in `retro-trans`. The catalog workflow
discovers repositories and stable GitHub releases, validates every new manifest,
downloads and verifies its required assets, checks consistency with known binary
identities, and commits the resulting catalog. It runs hourly and can be started
manually. A validation failure prevents the entire new catalog from being saved;
the last valid catalog remains available.

SRW-Z's adapted `tools/release.py` uses this builder and keeps its pinned source
branch/archive and optional texture pack. It stages a draft release, checks
uploaded asset metadata, and only then publishes it. It never uses `--clobber`.
The reusable integration copy is `integrations/srw_z_release.py`.

## Historical releases

The initial catalog includes 9 SRW-Z releases, 21 patches and 13 binary identities.
Legacy records are explicitly marked and use reviewed hashes from the published
notes/readmes. SHA-256 takes precedence; SHA-1 is accepted only for those imported
records. Output lengths were read from the actual VCDIFF windows. The one-time
import script documents the published hash values and their provenance.

New releases cannot opt into legacy validation through their manifest. The
catalog generator grants that status only to already-reviewed catalog records.
Readers retain support for the historical versioned SRW-Z manifests through
the legacy catalog and the existing single-release compatibility reader.

A reviewed v1 release can gain an explicit multi-file solution in the central
catalog without replacing any published assets. Keep its original manifest
fields and patch records, set the catalog copy's `schema_version` to 2, and add
verified `solutions`. Include a release-level `solution_import` object with
`schema_version: 1`, the SHA-256 of the exact published `BUILD-MANIFEST.json`
bytes in `manifest_sha256`, and a nonempty `reason` pointing to the review record.
Document the component mapping, unchanged-file hashes, and local complete-disc
verification. Never infer this grouping from asset names alone.

On each refresh, the generator requires that exact original v1 manifest and
validates all its published assets, checksums, and round-trip report before
reapplying the reviewed solution. A changed manifest or invalid asset rejects
the refresh. The imported solution is subject to the same immutable membership,
output-name, and file-identity rules as a published v2 solution. See the
[MH2 v0.1.17 review](catalog-imports/marionette-handler-2-v0.1.17.md) for an example.

## Withdrawn patches

When a maintainer explicitly withdraws a patch, move its exact catalog record
from `releases` to `withdrawn_releases`, adding a nonempty `reason`. A release
may have separate active and withdrawn records, each containing only its own
patches and asset URLs. Keep every binary hash, asset hash, size and URL intact.
These records preserve identity evidence but are excluded from recognition,
automatic routes and download validation. They cannot be removed, altered or
reactivated by a later catalog refresh. Changed game output still requires a
new version and patch URL.

Update the live release manifest, validation report and checksums to list only
the remaining assets. Older clients predating withdrawal support must update
to Retro Trans 0.3.1 or later before refreshing a catalog with withdrawals.

## Application releases

Set `retro_trans.__version__` and push a matching stable `vX.Y.Z` tag. The Windows
workflow runs tests, builds a standalone EXE with the engine/catalog bundled,
checks its offline startup, and publishes `Retro-Trans.exe`, the distribution ZIP,
and `UPDATE.json`. The update metadata contains schema version, app version,
platform, asset filename, byte size and SHA-256. Existing app releases are never
overwritten. Patch-catalog updates do not require a new application version.

## Scoped catalog maintenance

A manual **Refresh patch catalog** run can set its optional `repository` input,
for example `retro-trans/ACE-3`. The equivalent CLI is
`python -m retro_trans.catalog_builder --repo retro-trans/ACE-3`.
This runs all manifest, asset-download, checksum and identity checks for that
repository and preserves every other catalog record unchanged. It does not
approve or import unselected releases. Scheduled runs still validate all
repositories; unrelated malformed release metadata remains an error there.
