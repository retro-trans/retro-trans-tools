# Third-party components

## xdelta3 3.2.0

Copyright Joshua MacDonald and the xdelta contributors. Licensed under Apache
License 2.0; the full license is included as `licenses/XDELTA-LICENSE.txt` in the
distribution and `retro_trans/resources/XDELTA-LICENSE.txt` in the source.

The unmodified official Windows x64 archive is bundled and checked before each
extraction. Source and release: https://github.com/jmacd/xdelta/releases/tag/v3.2.0

ZIP SHA-256: `af8ef036cb077a48df080c9a8ac1be4a6e7511c32d11f8bec89b6803a9e52576`.
The archive's own README is retained inside the bundled archive.

## chdman 0.289

The unmodified official Windows x64 chdman executable is bundled for offline
CHD conversion. Copyright Aaron Giles, MAMEdev and contributors. The tool's
source is marked BSD-3-Clause; the original distribution notices and full
license texts accompany it in `licenses/chdman` and in the bundled engine ZIP.

- Source: https://github.com/mamedev/mame/tree/mame0289
- Official release: https://github.com/mamedev/mame/releases/tag/mame0289
- Official archive: `mame0289b_x64.exe`, 87,626,249 bytes.
- Archive SHA-256: `a1aa7912168c9d1b05e611906bc21b8b9be3935822aead36d12a1da363150b7d`.
- Executable SHA-256: `8a74468e3b0879698835b57c3b58e88e5a51e4de73bee6ef755c28530b5b040f`.
- Bundled ZIP SHA-256: `39c4cc4f8dc4da8422c378886458745fba1304ebe7bc8f69ebbd30baa97fdfeb`.

`scripts/bundle_chdman.py` verifies the official archive before extracting the
engine and its notices into a reproducible ZIP. The runtime verifies that ZIP
before extracting the named executable into a private temporary folder.
This MAME build requires x86-64-v2 CPU functionality for CHD operations.

## Python, Tcl/Tk, and PyInstaller

The standalone executable includes the Python runtime and Tcl/Tk. Their licenses
are included in the distribution's `licenses` folder. PyInstaller packages these
components under their respective licenses; its bootloader exception permits
distribution of the packaged application.

- Python: https://docs.python.org/3/license.html
- Tcl/Tk: https://www.tcl-lang.org/software/tcltk/license.html
- PyInstaller: https://pyinstaller.org/en/stable/license.html

## Translation patches

Patches retain the terms published by their respective repositories. No game
binary or translation patch is included in the executable; patches are downloaded
when selected. The bundled catalog contains release metadata and hashes only.
