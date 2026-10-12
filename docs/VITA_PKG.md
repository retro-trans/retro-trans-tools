# Profile-driven Vita patching

The **Automatic** tab recognizes original Vita PKGs and downloads their matching translation ZIP when you click **Patch**. Use the **Vita** tab for a local patch override or a **Hardware rePatch** overlay. Each release profile describes its game, exact source edition and patch inventory. Adding a game with a supported format requires a profile, not another game-specific panel or code registry.

## Vita3K PKG

This flow is available in the **0.5.11 Windows release** and newer.

1. In **Automatic**, browse to your original Vita `.pkg`, or use **Folder…** to find one. The title ID appears and **Matching license** replaces the output-format field. Browsing and scanning only inspect package headers.
2. Select your matching local NoNpDrm `work.bin` or `.rif` and choose a new **Translated PKG** filename.
3. Click **Patch**. The app checks the full original hash, finds a compatible release, downloads its translation ZIP and verifies the completed package. You do not need to choose a translation ZIP.
4. Install that PKG through Vita3K's **File → Install .pkg**, supplying the same license. Restart the game and verify the title-screen build version.

Automatic discovery checks Retro Trans repositories for published stable releases containing `VITA-PKG.json`, searches their ten most recent releases, and picks the newest profile matching the package's content ID, byte size and complete SHA-256. It verifies both the publisher's asset checksum and the ZIP's internal inventory. No package or license is uploaded. If several projects match, select the desired project's downloaded ZIP instead.

Public releases require no GitHub sign-in. Private releases require access: if GitHub CLI is installed and already signed in, the app uses that account automatically. It also accepts an existing `GH_TOKEN`/`GITHUB_TOKEN` environment variable. Credentials stay in memory, go only to the GitHub API, and are removed before asset redirects to another host. Sign-in, access, connection or missing-profile errors do not cause an unverified patch to run.

For offline use or a release that automatic discovery cannot access, open **Vita**, choose **Vita3K PKG**, download the game's `*-Vita-PKG-patches.zip` yourself and select it under **Local patch (optional)**. A local `VITA-PKG.json` with adjacent patches and extras also works. Leaving the field blank uses automatic discovery. A verified cached ZIP can be reused, but automatic discovery still checks GitHub release metadata for the newest matching version.

You do not need to install the original first or edit its archive manually. The app fetches the official Vita3K tool from its publisher, verifies its download, and performs both source decryption and output-installation verification in isolated temporary filesystems. It verifies every original file, patch, generated extra and installed output file before saving a new package and adjacent `.validation.json`. It never operates on your existing emulator installation or saves.

Windows can briefly hold an extracted game file while another program inspects it. Version 0.5.10 retries sharing/lock violations for up to 12 seconds during verification and workspace cleanup. Other errors still fail immediately. If cleanup also fails after a conversion or verification error, the original error is retained. If an output was already saved and verified before a persistent cleanup lock, the message explicitly says to keep that output instead of patching over it. The app does not stop your existing emulator.

License files stay local. The app does not download them from NoPayStation or other license databases, upload them, or include them in translation releases. A matching content ID alone is insufficient: original PFS authentication and successful decryption must also pass. Native installer diagnostics are discarded because upstream messages may contain keys.

The current PKG-output engine supports **PFS v5, image specification 1, key ID 0, PKG Vita key type 2**, ASCII native paths and the declared original package revision. Other encryption formats fail explicitly; they require an engine update. Cross Ange PCSG00597 is the first real-game installation test. Synthetic profiles for another title confirm that identity, component paths, file counts and extras are not hardcoded to it. Other games still need their own profile, native installation test and gameplay testing.

Needs Windows x64, at least 6 GB free temporary space, and internet for the official tool download (a verified cached download can be reused). The result is a custom emulator PKG, not Sony-signed or verified for installation on hardware. Installation/file checks do not establish gameplay compatibility. Mac PKG rebuilding is not enabled.

## Hardware rePatch

The existing SRW Z3 automatic profile remains the fallback when **Local patch** is blank. A local `VITA-REPATCH.json` or ZIP identifies another game's title, application version, changed files and sanitized executable authentication. Output instructions use that profile's title ID. New games using original PKG input must also declare `package` with `bytes`, `sha256` and `content_id`. Generic PKG extraction validates its outer and authenticated inner paths before invoking the native tool; the legacy Z3 package remains pinned to its original known hash.

The programmatic folder-input route still accepts already decrypted originals without a license. Hardware profiles must be independently verified for their own game; enabling generic metadata does not establish physical-console compatibility. See [hardware instructions](VITA_REPATCH.md).

## Publishing a PKG profile

Use schema **`retro-trans-vita-pkg-v1`**. No scripts, executable tools, original game assets, complete packages or licenses belong in the patch ZIP. The app supplies its own encryption implementation.

The profile fields are:

| Field | Meaning |
| --- | --- |
| `schema`, `engine` | `retro-trans-vita-pkg-v1`, `pfs-v5-pkg-key2` |
| `name`, `build` | Display name and `0.x.y` translated build version |
| `title_id`, `content_id` | Exact Vita title/content identity |
| `target`, `minimum_app_version` | `Vita3K`, `0.5.8` |
| `package` | Original PKG byte size and SHA-256 |
| `source_files` | Complete decrypted original game inventory: path, bytes, SHA-256 |
| `files` | Changed paths, exact source/target identities, patch name/bytes/SHA-256 |
| `extras` | New generated paths, flat asset name, bytes and SHA-256 |

The ZIP has an exact flat inventory: `VITA-PKG.json`, its declared `.xdelta` patches and its generated extras. No additional entries are permitted. Source and output paths are validated, including case collisions, file/folder conflicts, Windows reserved names and parent traversal. Extras cannot overwrite original files. PFS databases and license files cannot be supplied as translation assets.

Keep the standard `BUILD-MANIFEST.json` and component deltas so existing Retro Trans Automatic and Apply xdelta workflows remain compatible. The Vita profile is an additional release route. Every PKG conversion rechecks the package identity and all installed file hashes. Publishers should additionally record a complete native round trip and gameplay limits for every game/profile version.
