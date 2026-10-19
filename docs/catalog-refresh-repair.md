# Catalog refresh repair — 2026-10-19

The [failed scheduled run](https://github.com/retro-trans/retro-trans-tools/actions/runs/39201243950)
stopped with `Vita extras are not registered for this release.` Recent successful
runs were scoped manual validations, not proof that the full hourly scan worked.

The builder now validates generic Vita rePatch profiles and their exact ZIP
inventory, including Cross Ange's asset-only overlay and credits. Existing Z3
migration requirements and all hash/auth/path checks remain in place. Hourly
unscoped scans isolate a rejected release, preserve existing trusted records,
continue validating other releases and save visible warnings plus a JSON report.
Explicit scoped scans remain strict. Immutability is checked per candidate and
again before output; corrupt starting catalogs and cancellation still abort.

The live Cross Ange release has a second independent blocker: no standard
`VALIDATION.json`. Its custom CPK proof is retained, but is not manifest-bound
standard validation. Two replacement metadata files are prepared under
`../Cross Ange/work/output/catalog-repair-0.1.13/`: a new standard report and
SHA256SUMS.txt extended with that report's checksum. Both published deltas were
fully decoded against original components and matched the preserved English
0.1.13 output sizes and hashes. All game/patch/profile/ZIP bytes are unchanged.
The Cross Ange component packager also generates the standard report and runs
the shared validator, preventing the same omission on future exports.

Validation passed 276 tests (four platform skips), including 43 catalog tests.
A live two-repository batch skipped Cross Ange's missing report and continued;
a strict repeat using only the staged metadata accepted Cross Ange and the
healthy repository. All 74 old catalog records remain immutable; the candidate
adds Cross Ange as release 75. This is a sampled live validation, not a hosted
full-organization workflow run.

## Authorized deployment

1. Push the tools source/workflow/docs changes to main, preserving concurrent catalog commits.
2. Upload the prepared VALIDATION.json and updated SHA256SUMS.txt to the existing
   Cross Ange v0.1.13 release. Preserve its game version and all other assets.
3. Dispatch the catalog workflow without a repository filter. Check the hosted
   rejection report and the published catalog; do not mistake a partial scan for
   complete validation.

The user explicitly approved this deployment on 2026-10-19. No tools app or
game release is created. The original validation record describes the local
checks before deployment; hosted verification is recorded separately after
the full workflow completes.

See [validation record](catalog-refresh-repair-validation.json).
