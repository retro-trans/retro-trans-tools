# PS3 DLC translation (local development, not released)

The **PS3 DLC** tab creates translated copies of installed DLC EDAT files.
It never installs, reads/downloads licenses, decrypts content, unpacks PKGs,
modifies console/emulator data, or provides missing DLC.

## User flow

1. Select the original DLC folder. Supported layouts: direct `.EDAT` files,
   a title folder with `USRDIR/DLC`, or `<DLC title ID>/USRDIR/DLC` beneath the
   selected folder. Scanning is bounded, not recursive.
2. Select the matching English **base ISO**, or use **Base game folder** for
   an extracted game. ISO size/SHA-256 must match. Folder input checks the
   executable AND font archive; a version label or manifest alone is insufficient.
3. Select the reviewed ZIP in **Local patch**. Once a compatible release is
   published, leave this blank for public Z3 discovery.
4. Choose a new output folder outside the inputs; click **Create DLC copy**.
5. Review `DLC-RESULT.json` and `INSTALL.txt`. Only present recognized packs
   are produced. Current packs are verified/copied. Unknown EDATs are reported
   and left alone; modified recognized files and duplicates stop the whole job.

The output is flat: selected EDATs, receipt and instructions. Install the
original licensed DLC normally first. Close the game/emulator, back up the
affected installed EDATs, then copy ONLY generated EDATs into the existing
`dev_hdd0/game/<DLC title ID>/USRDIR/DLC`. Z3 uses `NPJB00520`. Do not replace
the whole title directory or remove metadata, licenses, other DLC or saves.
Physical PS3 DLC gameplay remains unverified.

When updating the base game, refresh only its old installation cache
(`BLJS10256_DATA` for Z3), not the DLC or savedata. Never removed automatically.

## Publisher contract

- `PS3-DLC.json`: `retro-trans-ps3-dlc-v1`, stable game/disc/DLC IDs, numeric
  version, exact base ISO/executable/font identities, and each pack's content
  ID plus original/target/delta sizes and SHA-256 hashes.
- One flat `*-PS3-DLC-patches.zip`: identical profile and exactly its deltas.
  No scripts, licenses, complete game files, nested paths or undeclared extras.
- `DLC-VALIDATION.json`: profile SHA-256, complete roundtrip count and
  `all_passed: true`. Document hardware/public-download limitations separately.
- Include all three in the main release's canonical `SHA256SUMS.txt`. Retain
  `BUILD-MANIFEST.json` and `VALIDATION.json`. Local `DLC-SHA256SUMS.txt` is not
  a substitute for the canonical release checksum gate.
- Catalog validation checks every delta, matching release/version/base ISO,
  and roundtrip proof. It retains immutable `ps3_dlc` profile/ZIP metadata
  without changing disc routes. The base ISO must be a target in this release.
- Register both title IDs and all DLC content IDs. Pre-publication command:
  `python -m retro_trans.game_library_builder --validate-release path/to/PS3-DLC.json --repo retro-trans/SRW-Z3`.

First client discovery queries only the registered Z3 public stable releases
on demand, never the whole organization. No implicit sign-in or private
catalog export. Other-game DLC discovery and PKG input are not implemented.
Local ZIPs need no release; an uncached xdelta engine can still need download.

The published app does not yet have this tab. Publish a compatible tools
version before advertising integration. Implementation does not authorize
an app/game release or push. Keep all previous downloads immutable.

Synthetic tests cover subsets/current/mixed input, source/base/output mismatch,
cancellation, unsafe ZIPs, output races, input mutation, discovery, registration
and catalog checks. The game project's opt-in runner verifies real xdelta
outputs against 29 preserved local packs. These are not gameplay tests.
