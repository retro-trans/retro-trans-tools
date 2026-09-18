"""Fetch standard release manifests and publish a complete immutable catalog."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import urllib.parse

from .core import GitHubClient, PatchError, Asset, safe_name
from .catalog import Catalog, RESOURCE_DIR, assert_immutable, atomic_json, validate_manifest
from .release import validate_directory


def release_record(repo, release, client):
    tag = release["tag_name"]
    assets = {a["name"]: a for a in release["assets"]}
    manifests = [name for name in assets if name.startswith("BUILD-MANIFEST") and name.endswith(".json")]
    if not manifests:
        return None
    if manifests != ["BUILD-MANIFEST.json"]:
        raise PatchError("New releases require exactly one canonical BUILD-MANIFEST.json: " + repo + " " + tag)
    with tempfile.TemporaryDirectory(prefix="catalog-validation-") as temporary:
        directory = Path(temporary)
        def fetch(name):
            safe_name(name)
            if name not in assets:
                raise PatchError("Missing release asset: " + name)
            a = assets[name]
            url = a["browser_download_url"]
            expected = "https://github.com/{}/releases/download/{}/{}".format(
                repo, urllib.parse.quote(tag, safe=""), urllib.parse.quote(name))
            if url != expected:
                raise PatchError("Unexpected release download URL.")
            return a, url
        def read_verified(name):
            a, url = fetch(name)
            raw = client.read(url)
            if len(raw) != a["size"] or (a.get("digest") and a["digest"] != "sha256:" + hashlib.sha256(raw).hexdigest()):
                raise PatchError("Release asset integrity mismatch: " + name)
            return raw
        raw = read_verified("BUILD-MANIFEST.json")
        manifest = validate_manifest(json.loads(raw))
        if {p["patch"] for p in manifest["patches"]} != {n for n in assets if n.lower().endswith((".xdelta", ".vcdiff"))}:
            raise PatchError("Uploaded patches do not exactly match the manifest.")
        (directory / "BUILD-MANIFEST.json").write_bytes(raw)
        for name in ("SHA256SUMS.txt", "VALIDATION.json"):
            (directory / name).write_bytes(read_verified(name))
        for patch in manifest["patches"]:
            a, url = fetch(patch["patch"])
            if a["size"] != patch["patch_bytes"] or (a.get("digest") and a["digest"] != "sha256:" + patch["patch_sha256"]):
                raise PatchError("Published asset disagrees with manifest: " + patch["patch"])
            path = client.download(Asset(patch["patch"], url, a["size"], patch["patch_sha256"]), directory / "cache")
            shutil.copyfile(path, directory / patch["patch"])
        validate_directory(directory)
    return {"repo": repo, "tag": tag, "manifest": manifest,
            "assets": {p["patch"]: assets[p["patch"]]["browser_download_url"] for p in manifest["patches"]}}


def build_catalog(previous, client=None):
    client = client or GitHubClient()
    old = Catalog(previous)
    records = {(r["repo"], r["tag"]): copy.deepcopy(r) for r in previous["releases"]}
    for repo in client.repositories():
        if repo == "retro-trans/retro-trans-tools":
            continue
        for release in client.releases(repo):
            key = (repo, release["tag_name"])
            existing = records.get(key)
            assets = {a["name"]: a for a in release["assets"]}
            # Legacy metadata has been reviewed/imported once. Still check that
            # the remote patch bytes have not been replaced or removed.
            if existing and existing.get("legacy"):
                for p in existing["manifest"]["patches"]:
                    asset = assets.get(p["patch"])
                    if not asset or asset["size"] != p["patch_bytes"] or (asset.get("digest") and asset["digest"] != "sha256:" + p["patch_sha256"]):
                        raise PatchError("A historical release asset changed: " + p["patch"])
                continue
            record = release_record(repo, release, client)
            if record:
                records[key] = record
    result = {"schema_version": 1, "releases": [records[k] for k in sorted(records)]}
    assert_immutable(old, Catalog(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(RESOURCE_DIR / "catalog.json"))
    args = parser.parse_args()
    path = Path(args.output)
    try:
        previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"schema_version": 1, "releases": []}
        result = build_catalog(previous)
        atomic_json(path, result)
        print("Catalog validated:", len(result["releases"]), "releases")
    except (PatchError, OSError, ValueError, KeyError) as exc:
        parser.exit(1, "Catalog unchanged: " + str(exc) + "\n")


if __name__ == "__main__":
    main()
