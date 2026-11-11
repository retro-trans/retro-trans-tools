# Retro Trans 0.5.22 for Linux

This portable x86-64 build targets Ubuntu 24.04 and compatible desktop systems
with glibc 2.39 or newer. ARM Linux, older distributions and Steam Deck have not
been validated. X11 is required, or XWayland in a Wayland session.

Extract the complete archive and run `Retro-Trans/Retro-Trans`. Keep the executable
beside its `_internal` folder. No Python, .NET, Wine, xdelta, CHD or Dolphin
installation is needed. If your file manager asks, choose **Run**. From a terminal:

```sh
tar -xzf Retro-Trans-Linux-x86_64-0.5.22.tar.gz
./Retro-Trans/Retro-Trans
```

Included: Automatic and manual xdelta patching, multi-file solutions, CHD and RVZ
conversion, Automatic/manual Dreamcast DCP, Z3 and experimental MX save tools,
and verified PS3 DLC folder patches. CHD/RVZ extraction asks first and retains
the extracted image beside the source. Original files and emulator data stay intact.

Vita original-PKG rebuilding and PKG-based hardware rePatch are unavailable on
Linux. Their buttons are disabled with an explanation. Use Windows for those
operations, or Apply xdelta with an already decrypted CPK and matching patch.
The bounded MX converter has the same experimental profile and prerequisites:
the reviewed game BOOT.BIN/ISO and official PPSSPP 1.20.4 Windows executable are
read as reference files when needed; the EXE is never launched. No game files,
keys or licenses are included. Gameplay compatibility is not established by
synthetic tests or startup checks.

Catalog and game-library updates work online and retain valid offline caches.
Linux app updates show a notice; download and extract a new package manually.
The Linux app never downloads or installs the Windows EXE. Settings and caches
are kept outside the installation folder, under `~/.cache/RetroTrans` (or
`$XDG_CACHE_HOME/RetroTrans`). **Open logs** opens local diagnostics.

Native tools are hash-verified. Runtime notices and exact distribution/source
provenance are in `_internal/retro_trans/resources/native/linux-x86_64/licenses`.
The DCP helper includes its pinned corresponding source and dependency notices
in `_internal/retro_trans/resources/native/dcp/linux-x64`.

Build with `scripts/build_linux.py` on native Ubuntu 24.04 after installing the
dependencies in `.github/workflows/linux.yml` and building the Linux DCP helper.
The workflow runs regression tests, packaged conversion/startup checks, and a
network-disabled container check without Python or installed patching engines.
Windows release assets and the existing v0.5.22 tag are preserved.
