# Retro Trans

A compact Windows desktop toolkit for translation releases from
[retro-trans](https://github.com/retro-trans). Download the standalone EXE or ZIP
from [Releases](https://github.com/retro-trans/retro-trans-tools/releases/latest).
No Python, Node.js, or .NET installation is needed to run it.

## Use

Run **Retro-Trans.exe** on 64-bit Windows 10/11. The title bar shows the app version.
The app scans files directly
beside its EXE and identifies supported originals and previously patched versions.
It selects a file automatically only when one match is found. Use the selector
when several match, or **Browse** to a file in any other folder.
For a release that requires several files, use **Folder…** to select the disc
folder, or browse to one of its tracks or its CUE/GDI. The app selects the
complete patch solution and checks every required component.

- **Automatic:** choose Latest, Next version only, or a specific published version.
  Review the route, choose a new output filename, and click Patch. Every required
  patch is downloaded and verified, and every output in the chain is checked.
  Multi-file solutions save a new folder containing all verified patched tracks
  and the declared unchanged tracks and descriptor. **Route details** shows each
  file's patch sequence. Missing or duplicate required files block the operation.
- **Apply xdelta:** choose any source binary, local xdelta patch, and new output.
  This uses xdelta checks without requiring catalog recognition.
- **Vita rePatch — Z3:** select your original PCSG00264 v01.00 **PKG**, its
  matching NoNpDrm **work.bin**, and a new output folder, then **Create rePatch**.
  Downloads the official Vita3K tool and runs its package conversion in an
  isolated temporary folder, then verifies and patches the decrypted files.
  Copy the resulting `rePatch/PCSG00264` folder to your physical Vita.
  Needs an x64 Windows PC, internet, 6 GB of temporary space, and the matching
  patch profile (online when published, or a reviewed local `VITA-REPATCH.json`
  with its deltas). No Python, command-line steps, or personal auth dump needed.
  Your license is used locally, never uploaded. See [Vita instructions](docs/VITA_REPATCH.md).
- **Save conversion — Z3:** convert Jigoku-hen saves from RPCS3 to Vita3K, the reverse, or
  both directions. Select both save folders and a new output folder, close both
  emulators, then **Check saves** and **Convert saves**. Includes backups, verified
  ZIPs, and import instructions. Works offline. Supports decrypted emulator saves
  (NPJB00520 / PCSG00264); physical-console decryption and signing are not included.
  See [save conversion instructions](retro_trans/resources/Z3-SAVE-CONVERSION.txt).
- **Save conversion — MX (experimental):** create PS2 ↔ PSP manual-save test
  candidates at the reviewed early Hugo/Cerberus intermission, using fresh
  PS2 English-port and PSP English 0.4.9 saves. PS2 output targets local 0.1.18;
  the earlier fresh 0.1.14 sample remains compatible. Includes authenticated
  mode-3 PSP input, PPSSPP plaintext output, PS2 PSU packaging, preservation of
  all favorite-series choices, one PSP difficulty checkbox, backups and an audit. The
  first PSP candidate was reported working in PPSSPP; **PS2 loading and a full
  save/reload cycle remain unverified**. Other checkpoints, stock PS2, system saves and battle
  suspend are unsupported. Use a separate test card/profile. See the
  [MX instructions](retro_trans/resources/MX-SAVE-CONVERSION.txt) and
  [implementation notes](docs/MX_SAVE_CONVERSION.md). The app includes no game
  keys: encrypted input uses the user's reviewed PSP ISO/BOOT.BIN and installed
  PPSSPP 1.20.4 Windows x64 executable; AES runs through Windows CNG.

The original files are never overwritten. Existing output files are refused.
Cancelling a job removes unfinished output. Files stay on your computer and are
never uploaded. ISO, BIN, VPK, and other binary formats are handled as exact bytes.
Supported CHDs are unpacked with your permission into a new child folder; ZIP, 7z and
other archives still need to be extracted separately.

Both engines and the initial catalog are bundled, so manual xdelta and CHD conversion work offline from
the first launch. Automatic mode can also use cached patches offline. Network
access is needed for new catalogs, new patch downloads, app updates, and the
official package-conversion tool used by the Vita rePatch workflow.

### CHD disc images

Browse to a CHD or put it beside the EXE for automatic scanning. Choose **CHD**
or **Original format** in the output selector; CHD inputs default to CHD output.
Scanning lists CHDs without extracting them. When you select one, the app asks
before unpacking and shows the destination and required disc space. It creates
`<game>-unpacked` beside the CHD (or a numbered new folder if that name exists).
It then selects the extracted ISO, or BIN with a CUE for raw CD sectors, verifies
its catalog identity, and waits for you to click **Patch**. The extracted source
is kept and reused; clicking Patch does **not** unpack the source a second time.
You can browse to that extracted file again in a later session.

The app applies the patch route and optionally compresses the result back to CHD. A new CHD is extracted
again and compared with the verified patched disc before it is saved. The
original CHD and extracted source are preserved. No separate chdman installation is needed.

Supports standalone **CHD v5 DVDs** and **single data-track CDs** in MODE1/2048,
MODE1/2352 or MODE2/2352, without gaps or subchannels. CD BIN output includes a
new CUE sheet, and an existing CUE is also refused. Multi-track/audio CDs,
GD-ROM, parent-dependent CHDs, hard disks and other layouts are rejected.
Unpacked Dreamcast tracks are supported through explicit multi-file solutions;
multi-track/GD-ROM CHD extraction and recompression are not supported.

The actual extracted bytes are verified before patch downloads or patch
execution. Compressed file size and filename are not binary identities.

In **Apply xdelta**, leave **Unpack CHD input before patching** enabled for
patches intended for the original ISO/BIN. This also asks before keeping and
selecting the extraction; click **Apply patch** after it finishes. Disable it only for a patch made
against the compressed CHD file itself, and choose **Original format**. Manual
mode retains xdelta checks; CHD round-trip checks do not add a catalog identity
that the manual patch did not provide.

Allow space beside the CHD for the retained extracted source, and temporary
space on the output drive for the largest pair of patch
steps. CHD output also needs room for the final disc, compressed copy and
verification extraction (conservatively three times the target disc size),
plus 64 MiB. Cancellation or failure during extraction removes unfinished files;
completed extractions remain available even if identification or patching fails.

### PS3 installation data

Every catalog-recognized PS3 patch shows an installation warning before patching
and keeps the reminder in its completion message. Manual mode also shows the
reminder; recognized PS3 disc headers and PS3_GAME paths trigger the dialog.
Before playing, close the game/emulator and delete the related **old installation
data**, so it is rebuilt from the patched files. On PS3, use **Game Data Utility**,
not **Saved Data Utility**. On RPCS3, remove only the matching installation-data
folder under `dev_hdd0/game` (SRW Z3 Jigoku-hen: `BLJS10256_DATA`). Keep your game
images, saved games, and other games. The patcher never deletes installation data.

The bundled official chdman 0.289 requires a CPU supporting x86-64-v2. Engine
documentation: [MAME chdman](https://docs.mamedev.org/tools/chdman.html).

### Versions and routes

The initial catalog supports SRW-Z's 9 published releases through v0.9.83: 21
patches and 13 Original/Best binary identities. Older releases retain their
published SHA-1 verification; SHA-256 is preferred whenever available. All new
standard releases require SHA-256. Recognition uses content, not filenames.

Latest means the latest *reachable* version for your binary; the route also shows
when a newer published version cannot be reached. Next version only applies one
compatible upgrade. Older targets are available only when a compatible route
exists; the app never attempts to reverse an ordinary xdelta patch.

Multi-step upgrades prefer fewer patch operations, then smaller downloads. Allow
space for the largest pair of consecutive intermediate images plus 64 MiB; the
app checks this before beginning. Downloads also need space in the cache drive.

### Application updates and local storage

The app checks stable releases at startup, downloads verified updates in the
background, and installs them on the next launch. It never interrupts patching.
A hidden helper checks startup, replaces the exited EXE, and retains the previous
version as `.previous`; failed startup restores it. A non-writable installation
folder leaves the existing app usable. See **About / Updates** for status.

Settings, verified downloads, the last valid catalog, and pending updates live
under `%LOCALAPPDATA%\RetroTrans`. Updates are tracked per EXE location. Game files
are scanned only in the EXE's real folder, not a temporary extraction directory.
GitHub API limits apply; network failures retain the saved catalog. A stalled
network operation may take up to the 30-second socket timeout to cancel.

The executable is not code-signed. Windows ARM64 depends on x64 emulation and has
not been tested. Builds are tested using generated binaries; game-specific
playtesting is a separate activity.

## Publish a compatible game patch

Use the [release standard](docs/RELEASE_STANDARD.md) and
[example configuration](examples/release-config.json). Build locally:

```powershell
python -m retro_trans.release build release-local.json --out release-v1.2.0
python -m retro_trans.release validate release-v1.2.0
```

The builder generates full/incremental patches, applies every one, verifies the
results, and produces the manifest, checksums and validation report. Publish only
those artifacts and optional extras, never the game binaries. The central catalog
workflow discovers new standard releases hourly; it can also be run manually.

## Development

The runtime uses Python's standard library and Tkinter. Use Python 3.12+ with
Tkinter for new builds; the source requires Python 3.8+.

```powershell
python -m retro_trans
python -m unittest discover -s tests -v
python -m retro_trans.catalog_builder
powershell -ExecutionPolicy Bypass -File scripts/build.ps1 -Python python
```

The build script installs PyInstaller 6.22.3 in a local `.venv`, runs tests, and
creates `dist/Retro-Trans.exe`, `dist/Retro-Trans-Windows.zip`, and `dist/UPDATE.json`.
Use `-OutputDirectory dist/v0.2.0` if another build is still running. Build artifacts,
private release configuration, caches, and integration checkouts are ignored by Git.

The packaged startup check is offline and opens no visible window:

```powershell
& '.\dist\Retro-Trans.exe' --health-check '.\health.json'
```

Tests cover real xdelta creation/apply and release-builder round trips, chain
verification, scanning, edition separation, historical hashes, immutability,
failure cleanup, update staging/rollback, and the native interface. Set
`RETRO_TRANS_ONLINE_TEST=1` to additionally verify live SRW-Z downloads.

CHD tests use synthetic DVD/CD images and the bundled engines, including
recognition, extraction/patch/compression round trips, cancellation, unsupported
layouts, false header hints, output preservation and offline operation. The
pinned engine bundle is reproducible with `python scripts/bundle_chdman.py`
(requires 7-Zip only on the build machine).

The Z3 converter is maintained in `retro_trans/z3_saves.py`, migrated from the
SRW Z3 project's standalone tool. Synthetic tests cover both directions, native
checksums, metadata preservation, slot mapping, backups, cancellation, and
changed-source rejection. Converted saves still need an in-game load/save test.
For command-line use, omit `--write` to check without creating output:

```powershell
python -m retro_trans.z3_saves --ps3-save-root "D:/RPCS3/dev_hdd0/home/00000001/savedata" --vita-save-root "D:/Vita3K/ux0/user/00/savedata/PCSG00264" --output "D:/Converted/Z3-new" --direction both --write
```
