"""One-time, reviewed SRW-Z history import; never used by the runtime updater.

SHA-1 identities below are published in the release notes. Newer SHA-256
identities are published in the v0.9.79 README and v0.9.83 build manifest.
Output sizes are read from the actual VCDIFF windows, not guessed from names.
"""
import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from retro_trans.core import Asset, GitHubClient, engine_context
from retro_trans.catalog import Catalog, RESOURCE_DIR, atomic_json

SHA1 = {
    "original": "e8dbe37e88afe8f82d48889b0775274ccde3cf99",
    "0.9.0": "bd4973d51ce6f5f47db46a2c52550fe4e7ed83a1",
    "0.9.6": "feae9bda4a2cd74925b189b0da1719c8ad807313",
    "0.9.38": "6eac149b2e78263272a4af647545df084c035f6e",
    "0.9.50": "40d557f0815b2de7e76cbad52a023381dcfb73f3",
    "0.9.66": "f79dcdddd78822fccd12f2ba7b9b6d4429a524d9",
    "0.9.68": "3409248a5d76b1617f80771b7100b14d6522242f",
    "0.9.72": "ffa3afe9c7dc700f6bffc9d863091a0d619972e3",
    "0.9.79": "608e1612327c97b79d3113524b18bfcbcec4d5bc",
}
SHA256 = {
    ("original", "original"): "ddbedefc0061213c50928fb213a7fb277c0345f01dab7386adc0383638a78cd2",
    ("original", "0.9.72"): "c76797b6c991a45a5002ce3cfa173594dafaff1a1ac64dfdc23763545e6f4029",
    ("original", "0.9.79"): "fc61ac8796c7ac6d1639af23a5bc0f758a2f75d5b3ee76b328bac374dae5f371",
    ("original", "0.9.83"): "98a5b419e197752bd2070f9e8edf5b6fcd5184c21f235551370063ece4049ecb",
    ("best", "original"): "950e2759d0d7482387d97d6df31325d9e352097a23e0bb4724073d1538d8cf77",
    ("best", "0.9.79"): "29b1d7bb69255c144e5250f43c21c9c53d9c605d41bb494c3f888e77b8cab989",
    ("best", "0.9.83"): "dddba2fe77e62772c007bef792f0c7a98fdc0da974e834c9abc260c1ffddf24d",
}


def main():
    client = GitHubClient()
    cache = Path(__file__).resolve().parents[1] / ".test-cache"
    releases = client.releases("retro-trans/SRW-Z")
    sizes = {("original", "original"): 3758358528, ("best", "original"): 3755081728}
    records = []
    with engine_context(client, cache) as engine:
        for release in reversed(releases):
            version = release["tag_name"].lstrip("v")
            if version not in SHA1 and version != "0.9.83":
                raise RuntimeError("Review new release before importing: " + version)
            manifest = {"schema_version": 1, "game_id": "srw-z", "game_name": "Super Robot Wars Z",
                "platform": "PS2", "version": version, "patches": []}
            assets = {}
            for a in release["assets"]:
                if not a["name"].endswith(".xdelta"):
                    continue
                edition = "best" if "-Best-" in a["name"] else "original"
                upgrade = re.search(r"(\d+\.\d+\.\d+)-to-v?(\d+\.\d+\.\d+)", a["name"])
                source_version = upgrade.group(1) if upgrade else "original"
                if upgrade and upgrade.group(2) != version:
                    raise RuntimeError("Review mismatched version: " + a["name"])
                digest = a.get("digest") or ""
                if not digest.startswith("sha256:"):
                    raise RuntimeError("Missing GitHub SHA-256: " + a["name"])
                asset = Asset(a["name"], a["browser_download_url"], a["size"], digest[7:])
                path = client.download(asset, cache)
                proc = subprocess.run([str(engine), "printhdrs", str(path)], capture_output=True, check=True)
                header = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
                output_size = sum(int(n) for n in re.findall(r"VCDIFF target window length:\s+(\d+)", header))
                if not output_size:
                    raise RuntimeError("Could not inspect VCDIFF windows.")
                sizes[(edition, version)] = output_size
                p = {"patch": a["name"], "edition": edition, "language": "en", "source_version": source_version,
                    "source_format": "iso", "target_format": "iso", "patch_sha256": asset.sha256,
                    "patch_bytes": asset.size, "target_bytes": output_size}
                for side, v in (("source", source_version), ("target", version)):
                    if edition == "original" and v in SHA1:
                        p[side + "_sha1"] = SHA1[v]
                    if (edition, v) in SHA256:
                        p[side + "_sha256"] = SHA256[(edition, v)]
                manifest["patches"].append(p)
                assets[a["name"]] = asset.url
                print(version, edition, source_version, output_size)
            records.append({"repo": "retro-trans/SRW-Z", "tag": release["tag_name"], "legacy": True,
                "provenance": release["html_url"], "manifest": manifest, "assets": assets})
    for r in records:
        for p in r["manifest"]["patches"]:
            p["source_bytes"] = sizes[(p["edition"], p["source_version"])]
    data = {"schema_version": 1, "releases": records}
    catalog = Catalog(data)
    atomic_json(RESOURCE_DIR / "catalog.json", data)
    print("Imported", len(catalog.nodes), "binary identities and", len(catalog.edges), "patches.")


if __name__ == "__main__":
    main()
