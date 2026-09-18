"""Build and validate standard game releases. Game binaries never leave disk.

python -m retro_trans.release build config.json --out release-directory
python -m retro_trans.release validate release-directory
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from .core import PatchError, safe_name, sha256_file, engine_context, encode, decode, check_cancel
from .catalog import validate_manifest, atomic_json


def build_release(config_path, output, cancel=None, progress=None, cache=None):
    config_path = Path(config_path).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    output = Path(output).absolute()
    if output.exists():
        raise PatchError("Release directory already exists. Use a new directory; published versions are immutable.")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {k: config[k] for k in ("game_id", "game_name", "platform", "version", "source_commit")}
    manifest.update(schema_version=1, patches=[])
    inputs = []
    digests = {}
    names = set()
    # Validate all config paths and names before any expensive encoding.
    for row in config["patches"]:
        name = safe_name(row["patch"])
        if not name.lower().endswith(".xdelta") or name.casefold() in names:
            raise PatchError("Each patch needs a unique .xdelta filename.")
        names.add(name.casefold())
        source = (config_path.parent / row["source"]).resolve()
        target = (config_path.parent / row["target"]).resolve()
        if not source.is_file() or not target.is_file():
            raise PatchError("A configured source or target file does not exist.")
        for path in (source, target):
            if path not in digests:
                digests[path] = (sha256_file(path, cancel, progress), path.stat().st_size)
        entry = {k: row[k] for k in ("patch", "edition", "language", "source_version", "source_format", "target_format")}
        entry.update(source_sha256=digests[source][0], source_bytes=digests[source][1],
                     target_sha256=digests[target][0], target_bytes=digests[target][1],
                     patch_sha256="0" * 64, patch_bytes=0)
        manifest["patches"].append(entry)
        inputs.append((source, target))
    validate_manifest(manifest)
    largest = max(p["target_bytes"] for p in manifest["patches"])
    if shutil.disk_usage(output.parent).free < largest * 2 + 64 * 1024 * 1024:
        raise PatchError("Not enough space to encode and verify this release.")
    with tempfile.TemporaryDirectory(prefix=".release-build-", dir=str(output.parent)) as temporary:
        stage = Path(temporary)
        with engine_context(cache=cache, cancel=cancel, progress=progress) as engine:
            for entry, (source, target) in zip(manifest["patches"], inputs):
                delta = stage / entry["patch"]
                encode(engine, source, target, delta, cancel, progress)
                decoded = stage / "verification.part"
                decode(engine, source, delta, decoded, entry["target_bytes"], cancel, progress)
                if decoded.stat().st_size != entry["target_bytes"] or sha256_file(decoded, cancel, progress) != entry["target_sha256"]:
                    raise PatchError("Patch round-trip verification failed: " + entry["patch"])
                # Check inputs again in case either changed during encoding.
                if sha256_file(source, cancel) != entry["source_sha256"] or sha256_file(target, cancel) != entry["target_sha256"]:
                    raise PatchError("A release input changed during the build.")
                decoded.unlink()
                entry["patch_sha256"] = sha256_file(delta, cancel)
                entry["patch_bytes"] = delta.stat().st_size
        atomic_json(stage / "BUILD-MANIFEST.json", manifest)
        atomic_json(stage / "VALIDATION.json", {"schema_version": 1, "manifest_sha256": sha256_file(stage / "BUILD-MANIFEST.json"),
            "patches": [{"patch": p["patch"], "roundtrip_verified": True, "target_sha256": p["target_sha256"]} for p in manifest["patches"]]})
        checksums = ["{}  {}".format(sha256_file(p), p.name) for p in sorted(stage.iterdir())]
        (stage / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")
        validate_directory(stage)
        check_cancel(cancel)
        # Reserve the final directory exclusively; never merge/overwrite builds.
        output.mkdir()
        try:
            for path in stage.iterdir():
                os.rename(path, output / path.name)
        except BaseException:
            shutil.rmtree(output)
            raise
    return manifest


def validate_directory(directory):
    directory = Path(directory)
    manifests = list(directory.glob("BUILD-MANIFEST*.json"))
    if len(manifests) != 1 or manifests[0].name != "BUILD-MANIFEST.json":
        raise PatchError("Release requires exactly one BUILD-MANIFEST.json.")
    manifest = validate_manifest(json.loads(manifests[0].read_text(encoding="utf-8")))
    expected = {p["patch"] for p in manifest["patches"]}
    present = {p.name for p in directory.iterdir() if p.suffix.lower() in (".xdelta", ".vcdiff")}
    if expected != present:
        raise PatchError("Release patch assets do not exactly match the manifest.")
    for p in manifest["patches"]:
        path = directory / p["patch"]
        if path.is_symlink() or not path.is_file() or path.stat().st_size != p["patch_bytes"] or sha256_file(path) != p["patch_sha256"].lower():
            raise PatchError("Patch integrity check failed: " + p["patch"])
    sums_path = directory / "SHA256SUMS.txt"
    checksums = {}
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        parts = line.split("  ", 1)
        if len(parts) != 2 or len(parts[0]) != 64:
            raise PatchError("Invalid SHA256SUMS.txt.")
        name = safe_name(parts[1])
        if name in checksums:
            raise PatchError("Duplicate checksum entry.")
        checksums[name] = parts[0]
        path = directory / name
        if not path.is_file() or path.is_symlink() or sha256_file(path) != parts[0]:
            raise PatchError("Release checksum failed: " + name)
    if not (expected | {"BUILD-MANIFEST.json", "VALIDATION.json"}) <= checksums.keys():
        raise PatchError("Missing required release checksums.")
    validation = json.loads((directory / "VALIDATION.json").read_text(encoding="utf-8"))
    rows = validation.get("patches", [])
    if validation.get("manifest_sha256") != sha256_file(manifests[0]) or len(rows) != len(expected):
        raise PatchError("Validation report does not match this manifest.")
    reported = {p.get("patch"): p for p in rows}
    for p in manifest["patches"]:
        row = reported.get(p["patch"], {})
        if row.get("roundtrip_verified") is not True or row.get("target_sha256") != p["target_sha256"]:
            raise PatchError("Missing successful round-trip report: " + p["patch"])
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("config")
    build.add_argument("--out", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("directory")
    args = parser.parse_args()
    try:
        if args.command == "build":
            build_release(args.config, args.out)
            print("Verified release built:", args.out)
        else:
            validate_directory(args.directory)
            print("Release manifest, checksums, and validation report agree.")
    except (PatchError, OSError, ValueError, KeyError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
