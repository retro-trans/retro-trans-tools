# Vita3K: small patches and local PKG rebuilding

## SRW Z3: Jigoku-hen

Use **Retro Trans 0.5.17 or newer** for the 0.9.2 Vita3K package. Version 0.5.16's
profile-size limit is too small for Z3's complete file-verification inventory.

1. In **Automatic**, select the original Japanese **PCSG00264 v01.00 PKG** and
   that game's matching **work.bin/.rif**.
2. Choose a new English PKG output and click **Patch**. Keep internet available
   and allow at least **12 GB free on the output drive** for temporary files.
   Every file is checked before
   saving, including a second isolated native installation.
3. Back up saves, close the game, then use **Vita3K → File → Install .pkg** to
   install the result with the same matching license. Check version **0.9.2**.

For a local override, select `SRW-Z3-v0.9.2-Vita-PKG-patches.zip` under
**Vita → Vita3K PKG → Local patch**. Do not select the separate hardware
rePatch bundle. Neither bundle contains a complete game or license. The PKG
is for Vita3K, not Sony-signed hardware installation; installation checks do
not establish gameplay compatibility. PS3 and hardware rePatch are separate
downloads and are not prerequisites for this route.

## Cross Ange

Use **Retro Trans 0.5.16**'s **Automatic** tab. It downloads about **5.4 MB of translation patches**, decrypts your original game locally, applies the CPK/metadata patches and credits, then rebuilds and verifies an English PKG on your computer. The package-size whole-PKG xdelta route remains withdrawn.

1. Select your original Japanese **PCSG00597 v01.00 `.pkg`** in **Automatic**.
2. Select **Cross Ange's matching `work.bin`** (or compatible NoNpDrm `.rif`). A license from another game will not work. **This flow needs the license during patching and installation.** No license is included or downloaded.
3. Choose a **new Translated PKG filename** and click **Patch**. Allow at least **6 GB free** for temporary extraction, rebuilding and verification. The tools also download the official Vita3K runtime on first use; this is separate from the 5.4 MB translation bundle.
4. Wait for the output to pass a second isolated Vita3K installation and complete file checks. Your original PKG, license, existing emulator data and saves are preserved.
5. Back up existing saves and close the game. In your own Vita3K, use **File → Install .pkg** for the new English package and supply the same matching license when asked. Restart and check **v0.1.13** in the title footer; translation credits are on manual page 25.

Cross Ange is public; downloads do not require GitHub sign-in. Other private releases require existing GitHub CLI sign-in with repository access. Automatic discovers the matching `VITA-PKG.json` and `Cross-Ange-English-0.1.13-Vita-PKG-patches.zip` independently of the public binary catalog. For offline/local testing, select that ZIP under **Vita → Vita3K PKG → Local patch (optional)** with the original PKG and matching license.

Download the Windows build from [Retro Trans Tools releases](https://github.com/retro-trans/retro-trans-tools/releases/latest). The rebuilt PKG is intended for Vita3K; it is not Sony-signed or verified for hardware installation. Full gameplay and proofreading remain outstanding. Hardware uses the separate rePatch bundle.

## Generic release profiles

Use retro-trans-vita-pkg-v1 in VITA-PKG.json. Declare exact original PKG and decrypted inventory identities, component deltas and bounded generated extras. Publish the identical profile separately and inside a flat *-Vita-PKG-patches.zip. The engine rejects undeclared paths, license assets, incorrect content/license identities, wrong inventories and mismatched complete output files. Only Windows PFS-v5/key-type-2 conversion is currently verified. Download/check data remain local; no original/derived license keys or raw native diagnostics are logged. Manual CPK patching and hardware rePatch remain separate routes.

In 0.5.17 the JSON limit is 256 KiB (previously 128 KiB). Profiles needing the
larger limit must declare `minimum_app_version: "0.5.17"`. The 64 MiB ZIP limit
and all inventory, path and hash checks remain unchanged.
