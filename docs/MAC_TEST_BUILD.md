# Mac feature-parity test build

This branch targets the same features as Windows: automatic verified patches,
manual xdelta creation/application, supported CHD conversion, Vita rePatch,
Z3 saves, experimental MX saves, and verified next-launch app updates.
It is a test build, not a release or a claim of game-specific playtesting.

## Install

Download the matching workflow artifact, then extract the contained
`Retro-Trans-macos-arm64.zip` (Apple Silicon, including M1) or
`Retro-Trans-macos-x86_64.zip` (Intel). Move `Retro-Trans.app` to a writable
folder, normally Applications. The window title includes the app version.
No Python, Homebrew, Windows, or emulator compatibility layer is needed by users.
Current runners target macOS 14 or newer on Apple Silicon and macOS 15 or newer
on Intel. The exact minimum is recorded in the app and update metadata.
Builds are ad-hoc signed, not Apple Developer ID signed or notarized. macOS may
require explicit approval in Privacy & Security; do not disable Gatekeeper.

Files beside the app are scanned. Settings and verified downloads are under
`~/Library/Application Support/RetroTrans`. Existing output is never overwritten.
PS3 installation-data warnings and all existing save/CHD restrictions still apply.

## Vita

Select the original PCSG00264 PKG and matching work.bin, choose a new output
folder, and select Create rePatch. The app downloads and verifies the official
Vita3K Mac build, temporarily mounts its disk image read-only, and copies its
unmodified app to a private temporary folder. A portable directory beside that
copy isolates conversion from an existing Vita3K installation. The disk image
is detached, and temporary files are removed after conversion. Inputs, output
hashes, and the public patch ZIP use the same checks as Windows.

The CLI smoke test does not prove real-game PKG decryption. A real PKG/work.bin
test on a Mac is required before claiming that flow is verified. Never upload
game files, license files, auth dumps or save data to CI.

## Save conversion

Both Z3 directions and the existing experimental MX checkpoint are included.
Mac MX cryptography uses Apple's CommonCrypto rather than Windows CNG and runs
the same known-answer and authenticated synthetic-save tests. The existing
MX key-input profile still reads the exact PPSSPP 1.20.4 Windows x64 EXE as
data, on either OS; it does not run that EXE. Select that file and your own
reviewed game ISO/BOOT.BIN in the advanced inputs. No keys are bundled.
Mac PPSSPP executables are not interchangeable with this exact-file profile.

## Updates and validation

Mac downloads use separate architecture-specific update metadata; Windows
UPDATE.json and EXE handling are unchanged. A verified whole-app ZIP is staged,
checked on startup, and installed with a previous-bundle backup. Failed startup
restores the previous app. No newer Mac asset means no Mac update is offered.

The macOS workflow builds both architectures and runs native GUI, patch,
CHD, save cryptography, archive-safety and update tests, plus packaged startup,
whole-bundle replacement and official Vita3K CLI checks. Test artifacts expire
after 30 days. It cannot publish a release (read-only repository permissions).

The 0.5.6 Mac test build supersedes 0.5.5, which omitted HTTPS certificates.
It bundles certifi roots and keeps TLS/hostname verification enabled. The
packaged-app test downloads the catalog, actual Vita patch ZIP and official
Vita3K DMG with developer-installed certificate paths unavailable. Certificate,
DNS and timeout failures now have distinct messages. A network that substitutes
its own HTTPS certificates may still require administrator assistance.

Build dependencies: Python 3.12, PyInstaller 6.22.3, certifi 2026.7.22, and Homebrew rom-tools.
Run `python scripts/build_macos.py`, then
`python scripts/check_macos_package.py` on a Mac. Tool receipts/notices are
included in the app. Full Windows regression runs separately.
