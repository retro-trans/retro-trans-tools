# Vita3K: small patches and local PKG rebuilding

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
