# Combined-source xdelta releases

Retro Trans 0.5.23 adds manifest schema 3. Each combined patch declares
`combined_source: {"method": "concat", "files": [...]}`. The ordered list has
2–16 distinct flat filenames with exact `bytes` and `sha256` values. Its total
must equal `source_bytes`, and concatenated bytes must match `source_sha256`.
The manifest requires `min_app_version: "0.5.23"` or a later supported version.
There is no filename-based guessing of file order, recursive search, or shell
command execution. Combined-source releases cannot also declare v2 output
solutions. Source nodes are input-only; ordinary translated targets remain
single files, allowing existing version recognition and incremental routes.

Choose a component with Browse, or its containing folder with Folder. Missing,
ambiguous, changed or symbolic-link components block the operation. The app
does not write a combined file while scanning. Patch checks space, streams and
verifies each component, checks the aggregate source, then uses the normal
verified xdelta chain. Temporary files are cleaned on every exit. The output
must be a new file, and every original and user save remains untouched.

The local release builder accepts `source_files` instead of `source`:

```json
"source_files": [
  {"name": "kiwame.exe", "source": "private/original/kiwame.exe"},
  {"name": "kiwame.tpatch", "source": "private/original/kiwame.tpatch"}
]
```

Only names, sizes, hashes and order enter the public manifest. Private paths,
combined binaries and complete game outputs stay local. Optional private
`patch_source` imports an existing delta without re-encoding; it must still
decode to the exact declared target. All source components are checked again
before the builder publishes its local output directory.

Publish the compatible app before game metadata using schema 3. Older apps
reject schema 3 and retain their last valid catalog. Register package IDs and
run the normal publication gate. Never replace issued patch bytes or change
a known source definition. Use a new game version when target bytes change.

For Apathy, official updates still require a newly verified release. Original
Steam build 10331351 uses the two-file source; a public English 0.8.0 executable
uses an ordinary incremental delta. An external development `package.nw` layout
is not that public embedded executable and must be migrated separately. The
patcher creates a new executable; installation in Steam is a separate step.
