# Dreamcast DCP patches

Windows **0.5.19** adds a **DCP** tab and command-line application.
Windows **0.5.20** adds **Automatic DCP** discovery and download, including both
Black/Matrix AD discs. Browse to the original Japanese CUE/BIN set (keep all
tracks together), select the version, choose a new folder and click Patch.
Every source track is hash-checked again on Patch, and the downloaded package's
embedded metadata must match the catalog before the existing verified DCP
apply/rebuild path runs. Experimental releases are clearly labelled and require
an explicit publisher opt-in; binary/xdelta prereleases are not imported.

Automatic discovery uses `DCP-AUTOMATIC.json` and exact original raw-track
fingerprints, not a fictitious binary patch. Renamed descriptor/track files are
accepted when the descriptor remains valid. Initial Black/Matrix checks cover
original CUE input; alternate layouts and CHD inputs remain available through the
local DCP tab. Scanning never extracts a CHD. Existing binary/solution catalog
records are unchanged; older clients ignore the separate DCP catalog records.

It uses Universal Dreamcast Patcher **2.1.8**, pinned to commit
`8b352f959bcc56ab39174c9e311b7ab7f0d522a2`, through a separate GPL process.
Existing Automatic/xdelta routes remain available.
The published Mac 0.5.18 and Android 0.1.0-test1 builds do not include DCP.

## Apply

1. Choose **DCP** and select your source `.gdi`, `.cue` or `.chd`. Keep all
   companion tracks together.
2. Select one `.dcp` package and a **new output folder**.
3. Select **GDI**, **CUE/BIN** or **CHD**, then **Apply DCP**.

For a CHD input, the app asks before extracting. It keeps the completed
extraction beside the CHD, selects its GDI, and waits for another click before
patching. Scanning does not extract CHDs. Allow **12 GB** free beside the input
and output. Inputs and existing output folders are never overwritten.

An upgrade DCP is built against a particular previous version; choose that
version as its source. A full DCP usually requires the original Japanese disc.
The filename alone does not establish compatibility.

The engine applies filesystem deltas and **rebuilds** the disc. Its raw tracks
can differ from track-level xdelta output even when every game file is identical.
Retro Trans re-extracts every rebuilt output and checks identical CD audio
content and sample alignment. Redump/TOSEC conversion can change silent padding;
the validation receipt records full track hashes as well. Packages with Retro Trans metadata
in the ZIP comment additionally verify the complete source and target game-file
trees and, when declared, boot-code invariants. The comment adds no files to the
game filesystem and remains compatible with ordinary DCP archives. Generic DCPs
without that metadata retain xdelta checks and a readable-output check; no
publisher output-hash guarantee is claimed.

GDI byte offsets are normalized into private copies before passing them to UDP
2.1.8, whose reader ignores the sixth GDI field. This is required for Rayblade's
published raw-track GDI. Ambiguous custom boot-sector track tables stop with an
explanation instead of making an automatic preservation choice.

## Command line

```text
python -m retro_trans.dcp source.gdi patch.dcp new-output --format GDI
```

`--allow-chd` explicitly permits extraction of a CHD source. No image or license
is uploaded. The process engine is bundled and works offline.

## Build the engine

Install .NET SDK 8 on the build machine. Preview the pinned build first:

```text
python scripts/bundle_dcp.py
python scripts/bundle_dcp.py --write
```

The build fetches the exact UDP tag, verifies the commit, and compiles the
unmodified core together with `integrations/dcp/Program.cs`. It creates a
self-contained helper: users need no separate .NET installation. Supported build
targets are `win-x64`, `linux-x64`, `osx-x64`, and `osx-arm64`, selected with
`--rid`. Windows packaging builds the helper if absent; Mac packagers must bundle
their matching RID first. The runtime checks all engine files against the bundle
manifest. Do not commit generated binaries, `.integration`, `bin` or `obj`.

The helper bundle includes the GPL license and `CORRESPONDING-SOURCE.zip`, with
the complete pinned upstream tree, process bridge and build script. Retain these
when distributing it. Upstream: https://github.com/DerekPascarella/UniversalDreamcastPatcher .
