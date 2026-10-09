# Getting work.bin for SRW Z3 on PS Vita

This guide helps you get the matching license file from your own game for
**Retro Trans → Vita rePatch**.

The workflow is: **original PKG + matching work.bin → Create rePatch → copy to Vita**.
This guide does not provide game packages or license files.

## What you need

- Your own copy of **SRW Z3 Jigoku-hen**, Vita title ID **PCSG00264**.
- A modified Vita with **NoNpDrm enabled** and **VitaShell** available.
- A PC and a way to transfer files from VitaShell, such as USB or FTP.
- Your matching original digital PKG for the patching step.

If NoNpDrm is not set up, follow its
[official installation instructions](https://github.com/TheOfficialFloW/NoNpDrm#installation)
first. Reboot after enabling the plugin. Do not replace your existing plugin
configuration wholesale.

## 1. Generate the license

Launch your owned game once with NoNpDrm enabled, then close it.
In VitaShell, open:

```text
ux0:nonpdrm/license/app/PCSG00264/
```

Find this file:

```text
6488b73b912a753a492e2714e9b38bc7.rif
```

This is the generated NoNpDrm license. Use the **app** folder, not an additional
content/DLC license. See the
[official license-export instructions](https://github.com/TheOfficialFloW/NoNpDrm#creating-the-fake-license).

## 2. Copy it to your PC

Using VitaShell's USB or FTP transfer, **copy** that file to a private folder
on your PC. Leave the original on the Vita unchanged.

For USB, select the storage device currently mounted as `ux0:`. Its PC drive
will show `nonpdrm/license/app/PCSG00264/`, without the `ux0:` prefix.

Rename the **PC copy** to:

```text
work.bin
```

Enable file-name extensions in Windows File Explorer so the result is exactly
`work.bin`, not `work.bin.rif` or `work.bin.txt`. Do not open and resave it in a
text editor.

Right-click the file and open **Properties**. Its **Size** should be exactly
**512 bytes**; ignore the larger “Size on disk” value. The filename and size
alone do not prove it matches your PKG—Retro Trans performs further checks.

## Already have a NoNpDrm backup?

A correctly prepared backup may already contain the generated license at:

```text
PCSG00264/sce_sys/package/work.bin
```

Use it only if it is the **NoNpDrm replacement**. The original PlayStation Store
`work.bin` is account-bound and contains your account ID; it is not the input
this workflow expects. See the
[NoNpDrm explanation](https://github.com/TheOfficialFloW/NoNpDrm#sharing-digital-applications).

## 3. Use it in Retro Trans

1. Download [Retro Trans](https://github.com/retro-trans/retro-trans-tools/releases/latest)
   for an x64 Windows 10/11 PC. Use version **0.5.4 or later** for the ZIP-only release.
2. Open **Vita rePatch** and select your original **PKG** and the copied **work.bin**.
3. Choose a new output folder on a drive with at least **6 GB free**.
4. Leave **Local patch** blank to use the published SRW Z3 v0.9.0 Vita profile.
5. Keep internet access available, click **Create rePatch**, and wait for successful
   verification. Retro Trans checks the license/package identity and decrypted
   game files; it does not modify your input files.
6. Follow the generated `README-INSTALL.txt`. With the game closed and your saves
   and previous overlay backed up, copy the output's `rePatch/PCSG00264` folder
   to `ux0:rePatch/PCSG00264`. Keep the original game installed and use a compatible
   rePatch plugin. Do not overwrite the original application or merge old mods.

The supported package is **PCSG00264 v01.00**, exactly **2,338,423,472 bytes**, with
SHA-256:

```text
3a13c11c0097ea8faa864c03add89cf7fb6e9c10bce352396ce105df884ac2fd
```

Another region, update package, repacked PKG, or cartridge dump is not a substitute
for that input. A license must match the package's full content identity, not
just have the same filename.

See the [full Retro Trans Vita guide](https://github.com/retro-trans/retro-trans-tools/blob/main/docs/VITA_REPATCH.md)
for installation, privacy details and current testing limitations. This creates
a physical-Vita overlay, not a Vita3K installer.

## Troubleshooting

- **The license folder is missing:** confirm NoNpDrm is enabled, reboot, and launch
  the correct game again. Check `ux0:` in VitaShell rather than guessing a PC
  drive letter. Do not create an empty replacement file.
- **The file is not 512 bytes:** copy the original exported `.rif` again without
  editing it. Check that Windows has not added another extension.
- **Retro Trans rejects the license:** confirm it is the generated NoNpDrm
  license for your matching game, not the original account-bound license or a
  DLC license. Renaming an unrelated file will not make it compatible.
- **Retro Trans rejects the PKG:** use the exact supported original package
  identified above. Do not disable validation or substitute another game's license.

## Keep the license private

Do not upload `work.bin`, your `.rif` file, an encoded license, or a process dump
to GitHub, chat, or a bug report. Share the error message only, with private paths
redacted. License files are not included in our releases.

`work.bin` and `self_auth.bin` are different files. Retro Trans generates the
reviewed `self_auth.bin` from patch metadata; you do not need to provide a personal
auth dump. Do not manually add `work.bin` to the generated rePatch folder.
