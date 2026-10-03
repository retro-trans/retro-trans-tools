# Marionette Handler 2 v0.1.17 solution import

Reviewed on 2026-10-03 for [the published v0.1.17 release](https://github.com/retro-trans/Marionnete-Handler-2/releases/tag/v0.1.17).
The release's v1 manifest describes two independent raw-track patches. A
complete Dreamcast disc requires both patched tracks, the remaining tracks,
and the CUE. The central catalog adds the explicit `japan-disc` solution so
Retro Trans 0.4.1 can recognize the disc when its CUE or folder is selected.

The exact published `BUILD-MANIFEST.json` has SHA-256
`9353bbd223acb3d0cb5562d3fa56c23a8b9c505fa9a6c576045c3b22bc27e21e`.
Its original fields, binary identities, patch identities, and asset URLs are
preserved. Only the catalog copy gains schema v2 solution metadata and the
`solution_import` provenance record. Published release assets are unchanged.

| Component edition | Output filename | Published patch |
| --- | --- | --- |
| Japan / Track 3 raw MODE1/2352 | Marionette Handler 2 (Japan) (Track 03).bin | Marionette-Handler-2-Japan-Track3-English-0.1.17.xdelta |
| Japan / Track 17 raw MODE1/2352 | Marionette Handler 2 (Japan) (Track 17).bin | Marionette-Handler-2-Japan-Track17-English-0.1.17.xdelta |

The solution copies tracks 01, 02, and 04 through 16, plus
`Marionette Handler 2 (Japan).cue`. All 16 unchanged files have complete byte
sizes and SHA-256 identities recorded in `solutions[0].copy_files` in the
catalog. The CUE references the declared output filenames; it is copied
without rewriting. Original and translated game binaries remain local.

Local verification applied both published xdelta patches to the exact source
tracks and checked all 18 files in the completed disc folder. Track 03's output
SHA-256 was `7e1758188a0a5d7bd9d5359e07165b88f77b6f521e096b518d5bdc93729faadd`;
Track 17's was `e466decab869f6b5e65d5256e91f2e78e01272dfbfb2a65f79a097850c98eab3`.
The completed set was recognized as version 0.1.17.

The import also re-downloads and validates the public manifest, patches,
checksums, and validation report, confirms that all prior catalog identities
are preserved, and checks that a subsequent catalog refresh retains exactly
the reviewed solution. Future game releases should publish schema v2 directly.
