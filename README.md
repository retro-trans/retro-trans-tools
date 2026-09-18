# Retro Trans

A compact Windows desktop patcher for translation releases from
[retro-trans](https://github.com/retro-trans). Download the standalone EXE or ZIP
from [Releases](https://github.com/retro-trans/retro-trans-tools/releases/latest).
No Python, Node.js, or .NET installation is needed to run it.

## Use

Run **Retro-Trans.exe** on 64-bit Windows 10/11. The app scans files directly
beside its EXE and identifies supported originals and previously patched versions.
It selects a file automatically only when one match is found. Use the selector
when several match, or **Browse** to a file in any other folder.

- **Automatic:** choose Latest, Next version only, or a specific published version.
  Review the route, choose a new output filename, and click Patch. Every required
  patch is downloaded and verified, and every output in the chain is checked.
- **Apply xdelta:** choose any source binary, local xdelta patch, and new output.
  This uses xdelta checks without requiring catalog recognition.
- **Create xdelta:** select an original and modified binary to generate a standard
  xdelta patch. Both input files are kept intact.

The original files are never overwritten. Existing output files are refused.
Cancelling a job removes unfinished output. Files stay on your computer and are
never uploaded. ISO, BIN, VPK, and other binary formats are handled as exact bytes;
the app does not extract CHD/archive contents or rebuild containers automatically.

The engine and initial catalog are bundled, so manual xdelta works offline from
the first launch. Automatic mode can also use cached patches offline. Network
access is needed for new catalogs, new patch downloads, and app updates.

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
