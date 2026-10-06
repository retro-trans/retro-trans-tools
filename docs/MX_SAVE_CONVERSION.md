# MX save conversion: experimental implementation

The app now writes **PS2 ↔ PSP manual-save test candidates** from the compact
Save conversion tab. It includes a CLI, authenticated PSP mode-3 reads, native
record packing, PPSSPP plaintext output, PS2 PSU export, verified ZIPs, backups
and an audit. The user reported that the first PS2 -> PSP save loads and plays
in PPSSPP. **PS2 loading and a full save/reload cycle are still unverified.**
This is an opt-in experimental feature in Retro Trans 0.5.0, not a general
whole-campaign converter. The existing Z3 workflow remains available.

## Scope and decisions

The first profile accepts the measured early Hugo/Cerberus checkpoint from a
fresh PS2 English PSP-stage port campaign and PSP English 0.4.9. Profile v2
targets PS2 0.1.18, while accepting the earlier fresh 0.1.14 manual sample as a
source/template with the same layout. It checks
exact campaign flag/history identities, five campaign words, two completed
maps, nine reviewed units, thirteen/fourteen reviewed pilots and their allocation
masks. Old marker-less PS2 saves, stock campaigns, later checkpoints, other
parties and system/battle saves are refused. The user explicitly selects the
experimental build profile; the unchanged game ID alone cannot establish it.

The source supplies all transferred progression. The destination save supplies
container metadata and icons only. Party order and duplicate pilots remain;
no funds, EXP or upgrade scaling is applied. Native record padding is cleared;
shared serialized state arrays and names are preserved. Options reset to the
test profile's settings (PS2 word 0x11b, PSP word 0x3ec43), rather than treating
the incompatible settings layouts as interchangeable. The 157-byte PSP music
array is initialized from the reviewed game executable's own assignments.
PSP music choices have no PS2 representation and are disclosed as omitted.

All mapped favorite bits are preserved in both directions. The previous
single-favorite restriction and choice control were removed after reviewing
`E:/Projects/SRW MX/tools/ps2_favorites.py` and its 0.1.18 implementation. The
game already stores a full bitmask; its new three-choice selector requires no
new savedata extension. The UI now has one **PSP difficulty on PS2** checkbox.
For PSP → PS2 it defaults to checked; unticking selects PS2 Original. For
PS2 → PSP, Check saves reads the source's stored mode and displays it in the
read-only checkbox. PSP output uses the PSP game's fixed difficulty. In Both
directions the checkbox controls only PS2 output. Reports include source and
destination modes and whether difficulty changes; funds are never rescaled.
A single-favorite legacy source stays single; three picks
and larger inherited masks remain intact. No additional favorites or bonuses
are invented.

PS2's native mask at settings object +0x5e8 serializes at player block +0x1008.
The block begins at full-save offset 0xb800, so the file field is **0xc808**,
not 0x1008 from the start of the file. PSP uses this same file field, backed by
object +0x688. The 22 ID identities match the PS2 fixed title rows at 0x4771f0
and PSP pointer table at 0x28a2f0, including the PS2 abbreviations for titles 2
and 16. New Game's 18 selectable IDs omit 2, 4, 13 and 16; that does not reduce
the full mask's representation. The source mask is copied without truncation.

Only a selected manual slot is converted. System/gallery/unlocks are not
migrated or silently replaced by another campaign's system state. Their
interaction with the candidate still needs in-game testing. Use an isolated
emulator profile/card; this limitation appears before writing and in the report.

## Use

Follow [MX import instructions](../retro_trans/resources/MX-SAVE-CONVERSION.txt).
The UI has Check saves / Convert saves, direction, PS2 slot selection and
the difficulty checkbox. Game-file paths and slot selection are in an expandable
section. The preview lists every retained favorite series. Editing an
input or option invalidates the check.
Check saves performs no output writes. The CLI mirrors this workflow:

```powershell
python -m retro_trans.mx_converter --ps2 "path/to/BISLPS-25345S01" --psp "path/to/ULJS000410000" --psp-game "path/to/MX.iso" --ppsspp "path/to/PPSSPPWindows64.exe" --direction ps2-to-psp --output "new/output/folder" --experimental
```

Add `--write` to create outputs. Use `--direction psp-to-ps2` or
`--direction both` to produce PS2 output with all favorites. The obsolete
`--favorite` option was removed. `--balance keep|original|psp` controls PS2 output.
PS2 input also accepts a read-only card plus `--ps2-slot BISLPS-25345S01`, or a PSU.
The older `python -m retro_trans.mx_saves` command remains read-only inspection.

## Integrity and dependencies

There are no new runtime packages. AES-CBC and CMAC use Windows CNG through
ctypes. Mode-3 input verifies the game-keyed DATA.BIN MAC and both portable SFO
hashes before decryption. It does not claim to recreate the device-fuse hash
for a physical PSP. The independently verified private decoder agrees with
the new engine on both supplied manual and system files (system conversion is
still rejected). NIST AES/CMAC known-answer tests cover the crypto primitive.

No game/KIRK keys, real saves, game executables or icons are bundled. The
experimental provider reads keys in memory from these hash-identified local files:

- Original PSP BOOT.BIN SHA-256: `31b4cae68ef11693cc32c3b50aa471e8bfc65e2f68ea32ca99d43ed5e6a5ee17`.
- English 0.4.9 BOOT.BIN SHA-256: `f8b70ca3914817704b39d69ecd543b054f12707ec1de49a1cce0ef90c3461093`.
- PPSSPP 1.20.4 Windows x64 EXE SHA-256: `27d3edbb06dc623dab60877d3e3a975aef4034c7d4fac464e92fd4998864d2ec`.

Plain ISO9660 images can supply BOOT.BIN without extracting the entire ISO.
The translation's reviewed serializer and initialization code matches the
original in the inspected regions. Unknown executables are rejected.
Plaintext PSP input requires internally consistent plaintext SFO metadata;
it has no cryptographic authentication. PSP output clears the encryption params
and DATA.BIN MAC and updates the display text; it is explicitly PPSSPP-only.

PS2 output regenerates both native checksums and the known MXBD balance extension.
The EMS/PSU container uses 512-byte entries and 1024-byte file padding, with
read-back validation. Format reference: Ross Ridge's public-domain
[mymc ps2save.py](https://github.com/ps2dev/mymc/blob/master/ps2save.py).
The card reader validates geometry/chains but does not check or generate ECC;
no live memory card is ever written.

New output folders are required outside source roots. Inputs are snapshotted,
checked again after staging, backed up, and recorded by SHA-256. Disk checks,
exclusive creation, verified ZIP read-back and cancellation cleanup protect the
outputs. The app does not install saves or publish releases.

## Local source evidence

The supplied fresh PS2 S01 has Original balance, 31,600 funds, nine units and
fourteen pilot records. The PSP manual slot has 8,200 funds, nine units and
thirteen pilots; favorites are Nadesico: Prince of Darkness, Zeta Gundam and
Gundam ZZ. Both have two completed maps and nine turns. PS2 contains an allocated
duplicate pilot 170; the converter preserves it. The PS2 system save has a
different balance setting and is deliberately not merged with the manual slot.
These are local observations, not assertions that arbitrary matched counters
prove full gameplay compatibility. Real source files remain ignored and local.

## Native layout evidence

Addresses below are evidence for the inspected executables, not a claim that all
regional or translated builds are compatible. Fields are little endian.

| Scenario file offset | Native representation |
| --- | --- |
| `0x0000`, `0x0004` | Unit and pilot counts; capacities 128 and 256 |
| `0x0008..0x0017`, `0x0018..0x0037` | Serialized manager bitsets; semantics require mapping |
| `0x0400` | Auxiliary unit-manager data |
| `0x0600..0x0dff` | 128 auxiliary records, 16 bytes each |
| `0x1400` | 128 unit records, stride `0x40`; ID is the first 16-bit field |
| `0x3400` | 256 pilot records, stride `0x60`; ID is the first 16-bit field |
| `0xb800` | Player/campaign section |
| `0xbc00..0xbc0f` | 16 campaign flag bytes |
| `0xbc10..0xbf8f` | 896 additional flag bytes |
| `0xbf90..0xbfa3` | Five campaign words; chapter is at `0xbf9c` |
| `0xbfa4..0xc0a3` | 128 location-history pairs |
| `0xc0a4..0xc140` | PSP-only 157-byte array; nonzero in the supplied sample |
| `0xc808` | Favorite-series bitmask |
| `0xc810`, `0xc814`, `0xc818` | Completed-map count, turns, funds |
| `0xd000` | Settings tail; bit layouts differ by platform |

PS2 scenario serialization calls unit serializer `0x30d880`, player serializer
`0x335650`, and settings serializer `0x3359c0`. Load calls are `0x30eec0`,
`0x335af0`, and `0x335eb0`. PSP serializers are `0x180b50`, `0x573e8`, and
`0x5781c`; player loading begins at `0x57a38`.

Native PS2 and PSP properties 1–19 have matching unit and pilot record packing,
confirmed by the executable-based verification below. That does not yet prove
their complete semantics, IDs, filters or limits align.
In particular, the byte at pilot record `+0x0c` must **not** be described as
pilot level. Property 7 is serialized as a 32-bit value at `+8`; do not rescale it
based on differences in the sample values. Party order and slot references must
be preserved together.

The record codec preserves unsigned wire bits. Both native loaders sign-extend
pilot property 17, so its stored `0xffff` must not be treated as a positive
gameplay value of 65,535 by a later semantic converter.

There is a measured platform difference outside the individual records: PS2's
scenario loader restores four words of the pilot bitset, whereas PSP restores
eight. Nonzero bits in scenario bytes `0x28..0x37` therefore cannot be promised
to survive a PSP → PS2 load. These bytes are zero in both supplied new manual
saves. The fresh PS2 sample's duplicate pilot ID is present in two allocated
slots (`0x3fff` pilot mask versus PSP's `0x1fff`); do not silently deduplicate it.

The PSP-only array is initialized by code beginning around `0x54770` and used at
`0xc7f44`, `0x15fcec` and related addresses. Its defaults match the supplied PSP save. The writer reads the reviewed
initializer from the user's executable; it never imports destination progression.

PSP prologue scenario IDs are 67/68; the PS2 port uses 66/67. The additional
PSP scenario uses ID 66; its PS2-port counterpart uses 68. IDs elsewhere are not
a blanket +1/−1 transform. Group order, history, flags and protagonist/route
must be mapped against the port's campaign tables.

## Reproduce native layout verification

The development-only verifier uses Unicorn 2.1.4 and requires locally owned
executables. It refuses executables whose hashes differ from the two reviewed
builds; no game data or keys are distributed with it.

The PS2 0.1.18 ELF is also reviewed (SHA-256
`533760d188e7af1333021e2ac50ec1b8b702b86e2c2576fea44dc7f76070ebff`). Its inspected
party and player serializers/loaders are byte-for-byte unchanged from 0.1.14.
The favorite verifier checks the 22 title identities and executes both games'
native field load/store instructions for 840 masks per platform: all single
bits, all 816 selectable triples, and larger inherited masks (1,680 round trips).

```powershell
python scripts/verify_mx_native_favorites.py --ps2-elf "path/to/0.1.18/SLPS_253.45" --psp-elf "path/to/BOOT.BIN" --report "new-favorites-report.json"
```

This verifier accepts the same optional `--dependencies` directory. The report
contains identities and counts, never game bytes. Field execution does not
substitute for a PCSX2 memory-card load/save/reload test.

```powershell
python scripts/verify_mx_native_layout.py --ps2-elf "path/to/SLPS_253.45" --psp-elf "path/to/BOOT.BIN" --report "new-report.json"
```

`--dependencies` may point to an isolated directory containing Unicorn instead
of installing it into the application environment. The app has no new runtime
dependency. The report path must be new.

The check supplies 16 deterministic sets of synthetic property values, runs the
native scenario serializers, checks the Python codec's decoding and encoding,
and compares both native loaders' property writes. It covers all 128 unit and
256 pilot records: 6,144 codec record checks and 225,280 loader property checks.
It separately exercises the pilot-bitset difference. Synthetic fixtures in
`tests/test_mx_records.py` came from this native execution, not real save files.

Native property getters/setters and PSP value filters are mocked at their
interfaces. This verifies packing and unpacking only. It does not verify ID
meaning, native clamping, compatibility of complete saves, or continued play.

## Confirmed PS2 integrity primitive

Scenario length is `0xd400`; system length is `0x21c00`. At length N:

- N−8: `0x78945612 + sum_u32(payload[N−1024:N−8])`, modulo 2^32.
- N−4: `0x78945612 + sum_u32(payload[0:N−1024])`, modulo 2^32.
- N−32: three words `0x4442584d`, extension version 1, mode 0 or 1.

An all-zero extension means absent. Unknown versions, modes or padding cannot be
overwritten. `with_balance` operates only on already identified PS2-port bytes;
it changes the recognized extension and checksums, preserving everything else.
It is not a campaign migration or cross-platform conversion entry point.

## Remaining game acceptance

On 2026-10-06, the user reported playing the first converted PSP save in PPSSPP
successfully. This is user-reported loading/play evidence for that candidate;
it does not establish a completed next-battle/save/reload cycle. Local Windows
UI automation previously failed with access denied. The new PS2 candidate has
not yet been tested in-game.
Do not describe file-integrity tests or native packing checks as gameplay tests.
The test package's instructions list comparisons for protagonist/robot, route,
party, funds, EXP, PP, kills, upgrades, skills, parts, favorites and inventory.
Expand the profile only after mapping and testing other protagonists, stage
boundaries, system-state interactions and non-default settings.

The original emulator installations, settings and saves have not been edited.
`scripts/launch_mx_test.py` opens the local converter without a startup scan or
update check; it remains the entry point for separately named experimental
test EXEs. The standard 0.5.0 app includes the same opt-in MX converter.
