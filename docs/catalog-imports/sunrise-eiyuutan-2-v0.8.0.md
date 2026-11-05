# Sunrise Eiyuutan 2 v0.8.0

Register the Japanese PS2 disc ID SLPS-25070 for `retro-trans/Sunrise-Eiyuutan-2` and import the standard original-to-English v0.8.0 route. The initial game release had a nonstandard provenance manifest; its metadata is corrected without replacing the published patch, target bytes, version or original source tag.

The game publisher retains the initial provenance and full-disc verification as BUILD-PROVENANCE.json and DISC-VALIDATION.json. The new canonical BUILD-MANIFEST.json, manifest-bound VALIDATION.json and SHA256SUMS.txt pass shared publication validation. Hosted [Refresh patch catalog run 42031724993](https://github.com/retro-trans/retro-trans-tools/actions/runs/42031724993) succeeds.

The catalog grows from 110 to 111 binary releases. Every prior binary release, DCP route and withdrawn record remains equal to its earlier JSON value. Catalog routing, game-library and catalog-builder suites pass 46 focused tests. No app code, executable version, update release or user settings are changed.

A fresh Retro Trans 0.5.20 cache and the real original ISO pass live catalog refresh, full-hash recognition, Latest planning, downloading the existing public patch, applying it through the app's bundled engine, full target verification and recognition as already-current v0.8.0. The run takes 109.656 seconds; the accompanying JSON records the exact patch and output hashes. This exercises the backend rather than GUI clicks or CHD conversion. Gameplay status remains independent.
