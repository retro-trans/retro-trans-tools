# Project preferences

- Keep the app compact and native. Include `retro_trans.__version__` in the main window title, including test builds.
- Warn users patching PS3 games to remove the related old installation data before playing. Clearly distinguish installation data from saved games; never remove it automatically.
- Ask before unpacking a CHD. Keep the completed ISO/BIN in a new child folder beside the CHD and select that extracted file, so patching does not unpack the source again. Scanning must not silently unpack CHDs.
- Do not create or publish a release after routine changes. Release creation, publishing, and pushing require the user's explicit request; local builds and tests are fine.
