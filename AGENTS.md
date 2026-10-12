# Project preferences

- Keep the app compact and native. Include `retro_trans.__version__` in the main window title, including test builds.
- Warn users patching PS3 games to remove the related old installation data before playing. Clearly distinguish installation data from saved games; never remove it automatically.
- Ask before unpacking a CHD. Keep the completed ISO/BIN in a new child folder beside the CHD and select that extracted file, so patching does not unpack the source again. Scanning must not silently unpack CHDs.
- Do not create or publish a release after routine changes. Release creation, publishing, and pushing require the user's explicit request; local builds and tests are fine.
- Keep Vita options generic: choose Vita3K PKG or hardware rePatch, and identify games and source revisions from reviewed release profiles. Add new game profiles instead of game-specific UI options. Users provide their own PKG and matching local work.bin/.rif; do not automatically download licenses or bundle them in releases.
- In Vita3K PKG mode, leave Local patch blank to identify the original PKG and download its matching Retro Trans release ZIP automatically. Keep a local ZIP/JSON override. Private downloads may use the user's existing GitHub CLI sign-in; credentials stay in memory, are sent only to the GitHub API and are stripped from cross-host redirects.
- Retry transient Windows sharing locks for Vita file verification and owned workspace cleanup. Cleanup must preserve an earlier verification/conversion/cancellation exception, never operate outside the current generated workspace and never terminate a user's existing emulator.
- Automatic must recognize original Vita PKGs, reveal the matching license input and create a translated Vita3K PKG using automatic release ZIP discovery on Patch. Browsing and folder scans only inspect headers; retain the Vita tab for hardware rePatch and local patch overrides.
