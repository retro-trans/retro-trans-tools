# GameCube and Wii RVZ images

The Windows 0.5.21 test build supports RVZ in **Automatic** and **Apply xdelta**.
The bundled official DolphinTool converts discs; Dolphin itself is not launched
and no separate Dolphin installation is needed. The official tool requires
Windows 10 1903 or later, x64, and the current [Microsoft Visual C++ v14 x64
runtime](https://aka.ms/vc14/vc_redist.x64.exe). Mac RVZ conversion is not included
in this build; existing Mac ISO/CHD workflows remain available.

## Automatic

1. Browse to the original RVZ, or select it from the files beside the app.
2. Approve extraction into a new `game-unpacked` child folder beside the RVZ.
   The original RVZ and completed ISO are kept. Scanning never extracts a disc.
3. The app selects the ISO and identifies it by the catalog's complete ISO hash.
   A renamed file works; a different edition or modified original does not.
4. Choose the target version and a new output filename. RVZ is the default for
   an RVZ-derived GameCube/Wii ISO; choose **Original format** to save an ISO.
5. Click **Patch**. The ISO is reused rather than extracted again. Every patch
   step is verified before any compressed output is created.

RVZ output is lossless, with no scrubbing: the app compresses the verified ISO,
extracts the result again, and compares its complete SHA-256 before publishing
the new output. Catalog hashes continue to describe ISO bytes. Patches and game
release manifests do not need to change for different RVZ compression settings.

Allow space beside the input for the retained ISO, and on the output drive for
up to three target ISO sizes plus compression overhead and 64 MiB reserve.
Failed or cancelled operations remove private unfinished files; a completed
retained extraction remains available for another attempt. Existing folders and
output files are refused. Declining extraction leaves the original selected;
select it again to retry. No game data is uploaded.

## Apply xdelta

Leave **Unpack CHD/RVZ input before patching** checked for an ISO-based patch.
After the extraction finishes, choose **Original format** or **RVZ** and click
Patch. Manual mode retains xdelta checks; it does not add a catalog identity or
an expected release-output hash. The RVZ round trip verifies that compression
preserved the resulting ISO, independently of translation correctness.

Turn the checkbox off only for a patch explicitly made against the compressed
RVZ bytes themselves, and use **Original format**. RVZ output conversion is for
GameCube/Wii ISOs; it is not offered for Dreamcast, Vita or grouped track sets.

For command-line batch use, the explicit command authorizes temporary extraction:

```text
Retro-Trans.exe --automatic-binary original.rvz --output English.rvz --format rvz --target Latest
```

Use `--format original` for the catalog's original output format. This command
uses the bundled/cached catalog and refuses unknown input, ambiguous matches,
existing outputs or already-current images. Refresh the catalog in the app
first when a new game release is missing.

## Engine and verification

The converter is unmodified official DolphinTool 2609a. The reproducible
`scripts/bundle_rvz.py` pins the official archive and executable SHA-256 values;
the runtime verifies the bundle before executing it. Original notices and exact
corresponding-source URLs are included in `licenses/dolphin-tool` in the Windows
ZIP and `RVZ-NOTICE.txt` inside the app. No game files or Dolphin GUI are bundled.

References: [official Dolphin release](https://dolphin-emu.org/download/),
[RVZ header definitions](https://github.com/dolphin-emu/dolphin/blob/409881c34357d0f105fd473167d15ab0bd9c1628/Source/Core/DiscIO/WIABlob.h),
[converter source](https://github.com/dolphin-emu/dolphin/blob/409881c34357d0f105fd473167d15ab0bd9c1628/Source/Core/DolphinTool/ConvertCommand.cpp).

Native tests use generated GameCube/Wii-like disc bytes and real converter/xdelta
processes. Game-specific real-RVZ and packaged-build evidence is recorded in the
build validation notes; conversion is not game execution or hardware testing.
