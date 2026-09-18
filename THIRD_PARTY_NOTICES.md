# Third-party components

## xdelta3 3.2.0

Copyright Joshua MacDonald and the xdelta contributors. Licensed under Apache
License 2.0; the full license is included as `licenses/XDELTA-LICENSE.txt` in the
distribution and `retro_trans/resources/XDELTA-LICENSE.txt` in the source.

The unmodified official Windows x64 archive is bundled and checked before each
extraction. Source and release: https://github.com/jmacd/xdelta/releases/tag/v3.2.0

ZIP SHA-256: `af8ef036cb077a48df080c9a8ac1be4a6e7511c32d11f8bec89b6803a9e52576`.
The archive's own README is retained inside the bundled archive.

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
