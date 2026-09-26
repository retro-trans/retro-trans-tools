# Game release standard v1

Each game release publishes exactly one `BUILD-MANIFEST.json`, the xdelta assets
it lists, `SHA256SUMS.txt`, and `VALIDATION.json`. Optional texture packs, source
archives, screenshots and documentation are separate assets. Do not include any
original or complete translated game binaries in the release directory.

The normative JSON Schema is `schema/game-release-v1.schema.json`. The shared
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

## Manifest fields

| Field | Meaning |
| --- | --- |
| `schema_version` | Integer `1` |
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
