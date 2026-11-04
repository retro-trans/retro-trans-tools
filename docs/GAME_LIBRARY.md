# Central game library

`retro_trans/resources/game-library.json` is the registry for **all consoles and
PC**, using `schema/game-library-v1.schema.json`. The app bundles it, refreshes
its public raw JSON when Vita discovery is needed, and caches it for one hour.
Invalid/unavailable updates retain the last valid copy. There is no fallback
that searches every repository or release.

## Required for every new game release

1. Register the stable `game_id`, repository, and relevant platform, region,
   edition and disc/package IDs in the central library **before publishing**.
   Reuse unchanged IDs; a new version does not require a duplicate game entry.
2. Include applicable `package_ids` in the local builder configuration and
   `BUILD-MANIFEST.json`, or `DCP-AUTOMATIC.json`. Every platform in the release
   needs an ID. Vita-only profiles already declare their exact content ID in
   `VITA-PKG.json`/`VITA-REPATCH.json`; register that ID in the library.
3. Run the publication gate below. The builder checks registration before
   reading game files or generating patches. Hosted catalog refresh rejects new
   binary/DCP releases without registration. Vita library refresh rejects
   unregistered content IDs.
4. After publishing normal assets, refresh the library/catalog. The hourly and
   manually dispatched **Refresh patch catalog** workflow updates verified
   records together. New IDs require a reviewed source change. Failed library
   refreshes preserve the published library. Corrected bytes need a new version.

Each ID has string fields `platform`, `kind`, and `id`:

| Platform | Kind | ID |
| --- | --- | --- |
| PS Vita | `vita-content-id` | Full PKG content ID with publisher/product suffix |
| PS1, PS2, PSP | `disc-id` | Actual disc serial/title ID; include each edition/disc |
| PS3 / other packaged consoles | `title-id` or `content-id` | Actual title/product/package ID |
| Dreamcast / other disc consoles | `product-id` | Actual product number |
| PC / Steam | `steam-app-id` | Steam application ID |
| PC / other stores | `gog-product-id` or `store-product-id` | Store product ID |
| Any platform without an official ID | `project` | Stable project-defined ID |

Platforms are not a closed list; use the manifest's platform spelling. The
platform is part of the identity. Registration does not add an engine for an
unsupported format. IDs locate games; complete hashes determine compatibility.
Other platforms retain their existing exact-hash binary/DCP catalog routes.

The initial library contains all 23 catalog projects. Where reviewed historical
metadata lacks an official ID, `kind: "project"` explicitly records the existing
game ID. Add verified official IDs later; never invent serials. Existing release
manifests and patch bytes stay unchanged.

## Maintainer commands

```powershell
python -m retro_trans.game_library_builder --check
python -m retro_trans.game_library_builder --validate-release path/to/manifest.json --repo retro-trans/Your-Game
python -m retro_trans.release build release-local.json --out release-v1.2.0 --library path/to/game-library.json
python -m retro_trans.release validate release-v1.2.0 --for-publication --repo retro-trans/Your-Game --library path/to/game-library.json
python -m retro_trans.game_library_builder
```

Use a reviewed library checkout. Paired synthetic examples are
`examples/release-config.json`, `examples/multi-file-release-config.json`, and
`examples/game-library.json`; they use project IDs, not fabricated serials.
Only maintainers/CI query registered Vita projects' releases. The generator
checks visibility, stable versions, profile hashes, IDs, URLs, sizes and
publisher hashes. It downloads small profiles, not ZIPs, games or licenses.
Clients still verify downloaded ZIPs, embedded profiles, components and outputs.

## Vita requests

Direct entries contain exact original PKG sizes/hashes and profile/ZIP asset
IDs/hashes. The app filters by content ID, mode and size, hashes the source and
selects the newest exact match before downloading.

An uncached route needs **one raw JSON fetch and two asset requests** (profile
and ZIP), with zero repository/release-list API requests regardless of library
size. First-time Vita3K acquisition separately needs one version lookup and a
runtime download. Repeating a route within an hour with valid cached assets
needs no discovery/download requests. App startup checks are separate.

Unknown IDs/hashes stop with a message and allow a local ZIP override. They
never cause an organization scan. Legacy Z3 hardware fallback remains one
explicit known release, not a general search.

## Private projects

Keep private records out of the public library. Create a separate local library
with the game's registered IDs, then use authorized GitHub CLI sign-in:

```powershell
python -m retro_trans.game_library_builder --library private-game-library.json --allow-private --output path/to/app-cache/game-library.private.json
```

Put the output in the app's cache directory. It is merged locally, never uploaded
or saved into the public cache. Keep it outside public source control. The public
builder refuses private repositories. Credentials remain in memory and are
removed from cross-host redirects. A local ZIP works without private-library
setup. Private releases are not automatically included in the public catalog.

## Historical releases

`package_ids` is additive to schema v1/v2. Historical manifests stay readable
without rewriting bytes. Normal directory validation can inspect them; new
builds and `--for-publication` require registration. Hosted refresh exempts only
already reviewed catalog records. Another old release needs a reviewed import,
not an automatic bypass of registration.
