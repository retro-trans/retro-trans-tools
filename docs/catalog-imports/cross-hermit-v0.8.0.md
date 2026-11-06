# Cross Hermit v0.8.0 Automatic import

Register `cross-hermit` as a Windows PC project ID for `retro-trans/cross-hermit`. An official product serial has not been established; the project ID does not invent one. The complete source ISO hash determines compatibility.

The existing v0.8.0 release gained a canonical BUILD-MANIFEST.json, VALIDATION.json and bare `Cross-Hermit-English-0.8.0.xdelta`. The bare delta is identical to the file inside the existing ISO patch ZIP. The canonical checksum list retains all original package/updater entries and adds the three standard assets. No original/full translated game image is published. Existing game, ISO, xdelta and updater payloads are unchanged.

The catalog builder now accepts checksummed supplemental ZIPs up to 256 MiB; other supported extras remain bounded to 64 MiB. Every extra is streamed and checked against its expected size and hash. This lets the existing 110 MB Cross Hermit packages remain fully checked. Regression coverage includes a ZIP larger than 64 MiB, truncated bytes, over-limit ZIP/metadata and unsupported file types. All 45 focused catalog tests passed.

[Hosted refresh](https://github.com/retro-trans/retro-trans-tools/actions/runs/42190093593) validated the published standard assets and added the original-to-0.8.0 route. [Hosted Checks](https://github.com/retro-trans/retro-trans-tools/actions/runs/42189826153) passed. Existing release records, withdrawn routes and binary identities are preserved.

An anonymous clean-cache Automatic run against the public catalog recognized the original ISO, downloaded the published bare xdelta, and produced the exact 770,318,336-byte target with SHA-256 `87ad84b9a0fb92657f19d5db2a91e361d8e7f7a2b57a6e31852fa7e3a25d54e2`. It recognized that result as current with zero further patch operations. The published Windows Retro-Trans.exe v0.5.21 independently passed its `--automatic-binary` command with a second clean patch cache. Both runs preserved the original; no game was launched.

Existing clients select Automatic, Refresh catalog, the original ISO, Latest and Original format. No application update or release is needed. Manual Apply xdelta remains available. [Verification records](https://github.com/retro-trans/cross-hermit/blob/main/docs/validation/retro-trans-automatic.json).
