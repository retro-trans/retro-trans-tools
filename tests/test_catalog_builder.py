import copy
import hashlib
import io
import json
import unittest

from retro_trans.catalog_builder import build_catalog
from retro_trans.core import GitHubClient, PatchError
from test_catalog import record


class ReleaseClient(GitHubClient):
    def __init__(self):
        self.record = record()
        manifest = json.dumps(self.record["manifest"]).encode()
        report = json.dumps({"schema_version": 1, "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
            "patches": [{"patch": self.record["manifest"]["patches"][0]["patch"],
                "roundtrip_verified": True, "target_sha256": self.record["manifest"]["patches"][0]["target_sha256"]}]}).encode()
        self.files = {"BUILD-MANIFEST.json": manifest, "VALIDATION.json": report,
            self.record["manifest"]["patches"][0]["patch"]: b"delta"}
        self.files["SHA256SUMS.txt"] = "".join(hashlib.sha256(v).hexdigest() + "  " + k + "\n" for k, v in self.files.items()).encode()
        self.prefix = "https://github.com/retro-trans/test/releases/download/v1.1/"
        self.assets = [{"name": name, "size": len(data), "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
            "browser_download_url": self.prefix + name} for name, data in self.files.items()]

    def repositories(self):
        return ["retro-trans/test"]

    def releases(self, repo):
        return [{"tag_name": "v1.1", "assets": self.assets}]

    def open(self, url):
        return io.BytesIO(self.files[url[len(self.prefix):]])


class CatalogBuilderTests(unittest.TestCase):
    def test_verified_standard_release_import(self):
        result = build_catalog({"schema_version": 1, "releases": []}, ReleaseClient())
        self.assertEqual(len(result["releases"]), 1)
        self.assertEqual(result["releases"][0]["manifest"]["version"], "1.1")
        self.assertEqual(build_catalog(result, ReleaseClient()), result)

    def test_scoped_refresh_preserves_other_records_and_validates_selected_assets(self):
        client = ReleaseClient()
        other = record(edition="kept")
        other["repo"] = "retro-trans/kept"
        other["assets"] = {k: v.replace("retro-trans/test/", "retro-trans/kept/") for k, v in other["assets"].items()}
        previous = {"schema_version": 1, "releases": [other]}
        saved = copy.deepcopy(previous)
        def no_discovery():
            raise AssertionError("Scoped refresh must not enumerate unrelated repositories")
        client.repositories = no_discovery
        result = build_catalog(previous, client, repositories=["retro-trans/test"])
        self.assertIn(other, result["releases"])
        self.assertEqual(len(result["releases"]), 2)
        self.assertEqual(previous, saved)
        client.files[client.record["manifest"]["patches"][0]["patch"]] = b"corrupt"
        with self.assertRaises(PatchError):
            build_catalog(previous, client, repositories=["retro-trans/test"])

    def test_missing_extra_and_corrupt_assets_rejected(self):
        for failure in ("missing", "extra", "corrupt", "report", "url"):
            client = ReleaseClient()
            if failure == "missing":
                client.assets = [a for a in client.assets if a["name"] != "VALIDATION.json"]
            elif failure == "extra":
                client.assets.append({"name": "unlisted.xdelta"})
            elif failure == "corrupt":
                client.files[client.record["manifest"]["patches"][0]["patch"]] = b"wrong"
            elif failure == "report":
                client.files["VALIDATION.json"] = b"{}"
            else:
                client.assets[0]["browser_download_url"] = client.prefix.replace("v1.1", "v9.9") + "BUILD-MANIFEST.json"
            with self.subTest(failure=failure), self.assertRaises(PatchError):
                build_catalog({"schema_version": 1, "releases": []}, client)

    def test_changed_historical_identity_rejected_without_mutating_previous(self):
        old = {"schema_version": 1, "releases": [record(legacy=True)]}
        saved = copy.deepcopy(old)
        client = ReleaseClient()
        for asset in client.assets:
            if asset["name"].endswith(".xdelta"):
                asset["digest"] = "sha256:" + "0" * 64
        with self.assertRaises(PatchError):
            build_catalog(old, client)
        self.assertEqual(old, saved)

    def test_withdrawn_records_preserved_without_downloading_removed_assets(self):
        retired = record(edition="retired")
        retired["reason"] = "Edition discontinued."
        previous = {"schema_version": 1, "releases": [], "withdrawn_releases": [retired]}
        saved = copy.deepcopy(previous)
        result = build_catalog(previous, ReleaseClient())
        self.assertEqual(result["withdrawn_releases"], saved["withdrawn_releases"])
        self.assertEqual(previous, saved)
        self.assertEqual(len(result["releases"]), 1)


if __name__ == "__main__":
    unittest.main()
