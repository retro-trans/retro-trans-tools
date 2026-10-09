import copy
import hashlib
import io
import json
import unittest
import zipfile

from retro_trans.catalog_builder import build_catalog
from retro_trans.core import GitHubClient, PatchError
from test_catalog import record


class ReleaseClient(GitHubClient):
    def __init__(self, release=None):
        self.record = copy.deepcopy(release) if release else record()
        manifest = json.dumps(self.record["manifest"]).encode()
        report = json.dumps({"schema_version": 1, "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
            "patches": [{"patch": p["patch"], "roundtrip_verified": True,
                         "target_sha256": p["target_sha256"]} for p in self.record['manifest']['patches']]}).encode()
        self.files = {"BUILD-MANIFEST.json": manifest, "VALIDATION.json": report}
        self.files.update({p['patch']: b'delta' for p in self.record['manifest']['patches']})
        self.files["SHA256SUMS.txt"] = "".join(hashlib.sha256(v).hexdigest() + "  " + k + "\n" for k, v in self.files.items()).encode()
        self.prefix = 'https://github.com/{}/releases/download/{}/'.format(self.record['repo'], self.record['tag'])
        self.assets = [{"name": name, "size": len(data), "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
            "browser_download_url": self.prefix + name} for name, data in self.files.items()]

    def repositories(self):
        return [self.record['repo']]

    def releases(self, repo):
        return [{"tag_name": self.record['tag'], "assets": self.assets}]

    def open(self, url):
        return io.BytesIO(self.files[url[len(self.prefix):]])


class CatalogBuilderTests(unittest.TestCase):
    def vita_client(self):
        from retro_trans import vita_repatch as vita
        from test_vita_repatch import fixture
        item = record()
        item['repo'], item['tag'] = vita.REPO, vita.TAG
        item['manifest']['version'] = vita.TAG.lstrip('v')
        client = ReleaseClient(item)
        data, _, targets = fixture()
        extra = {vita.MANIFEST: json.dumps(data).encode()}
        extra.update({row['patch']['name']: targets[row['path']] for row in data['files']})
        client.files.update(extra)
        client.assets.extend(dict(name=name, size=len(raw), digest='sha256:'+hashlib.sha256(raw).hexdigest(),
                                  browser_download_url=client.prefix+name) for name, raw in extra.items())
        return client

    def test_vita_extras_verified_separately_and_preserve_disc_routes(self):
        client = self.vita_client()
        previous = dict(schema_version=1, releases=[])
        result = build_catalog(previous, client)
        entry = result['releases'][0]
        self.assertEqual(entry['manifest'], client.record['manifest'])
        self.assertEqual(entry['vita_repatch']['title_id'], 'PCSG00264')
        self.assertEqual(build_catalog(result, client), result)
        self.assertFalse(any(name.startswith('VITA-') for name in entry['assets']))

    def test_vita_missing_corrupt_undeclared_and_changed_extras_rejected(self):
        for error in ('missing', 'corrupt', 'unlisted', 'auth', 'removed', 'changed'):
            client = self.vita_client()
            previous = build_catalog(dict(schema_version=1, releases=[]), client)
            if error == 'missing':
                client.assets = [a for a in client.assets if a['name'] != 'VITA-0.xdelta']
            elif error == 'corrupt':
                client.files['VITA-0.xdelta'] = b'wrong'
            elif error == 'unlisted':
                client.assets.append(dict(name='VITA-unlisted.xdelta'))
            elif error == 'removed':
                client.assets = [a for a in client.assets if a['name'] != 'VITA-REPATCH.json']
            else:
                data = json.loads(client.files['VITA-REPATCH.json'])
                if error == 'auth':
                    data['auth']['hex'] = '01'*144
                else:
                    data['build'] = 'replacement'
                raw = json.dumps(data).encode()
                client.files['VITA-REPATCH.json'] = raw
                asset = next(a for a in client.assets if a['name'] == 'VITA-REPATCH.json')
                asset.update(size=len(raw), digest='sha256:'+hashlib.sha256(raw).hexdigest())
            with self.subTest(error=error), self.assertRaises(PatchError):
                build_catalog(previous, client)

    def add_vita_zip(self, client, extra=False):
        from retro_trans import vita_repatch as vita
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, raw in client.files.items():
                if name == vita.MANIFEST or name.startswith('VITA-') and name.endswith('.xdelta'):
                    archive.writestr(name, raw)
            if extra:
                archive.writestr('work.bin', b'not allowed')
        raw = output.getvalue()
        client.files[vita.ARCHIVE] = raw
        client.assets = [a for a in client.assets if a['name'] != vita.ARCHIVE]
        client.assets.append(dict(name=vita.ARCHIVE, size=len(raw),
            digest='sha256:'+hashlib.sha256(raw).hexdigest(), browser_download_url=client.prefix+vita.ARCHIVE))

    def test_vita_archive_additive_and_immutable(self):
        from retro_trans import vita_repatch as vita
        client = self.vita_client()
        previous = build_catalog(dict(schema_version=1, releases=[]), client)
        self.add_vita_zip(client)
        current = build_catalog(previous, client)
        entry = current['releases'][0]
        self.assertEqual(entry['vita_repatch'], previous['releases'][0]['vita_repatch'])
        self.assertEqual(entry['assets'], previous['releases'][0]['assets'])
        self.assertEqual(entry['vita_archive']['url'], client.prefix+vita.ARCHIVE)
        self.assertEqual(build_catalog(current, client), current)
        client.assets = [a for a in client.assets if a['name'] != vita.ARCHIVE]
        with self.assertRaisesRegex(PatchError, 'ZIP was removed'):
            build_catalog(current, client)
        self.add_vita_zip(client, extra=True)
        with self.assertRaisesRegex(PatchError, 'ZIP identity changed'):
            build_catalog(current, client)
        with self.assertRaisesRegex(PatchError, 'exactly the described'):
            build_catalog(previous, client)

    def reviewed_solution(self):
        from test_solutions import grouped_record
        imported = grouped_record(copies=True)
        published = copy.deepcopy(imported)
        published['manifest']['schema_version'] = 1
        del published['manifest']['solutions']
        client = ReleaseClient(published)
        imported['solution_import'] = dict(schema_version=1,
            manifest_sha256=hashlib.sha256(client.files['BUILD-MANIFEST.json']).hexdigest(),
            reason='Reviewed complete two-track disc with verified unchanged files.')
        return client, dict(schema_version=1, releases=[imported])

    def test_vita_zip_only_migration_preserves_disc_and_profile_identities(self):
        from retro_trans import vita_repatch as vita
        client = self.vita_client()
        self.add_vita_zip(client)
        previous = build_catalog(dict(schema_version=1, releases=[]), client)
        names = [a['name'] for a in client.assets if a['name'].startswith('VITA-') and a['name'].endswith('.xdelta')]
        for name in names:
            client.assets = [a for a in client.assets if a['name'] != name]
            del client.files[name]
            current = build_catalog(previous, client)
            self.assertEqual(current, previous)
        self.assertEqual(current['releases'][0]['vita_min_app_version'], '0.5.4')
        client.files[vita.ARCHIVE] = b'corrupt'
        with self.assertRaises(PatchError):
            build_catalog(previous, client)

    def test_reviewed_v1_solution_survives_refresh_with_all_asset_checks(self):
        client, previous = self.reviewed_solution()
        saved = copy.deepcopy(previous)
        self.assertEqual(build_catalog(previous, client), previous)
        self.assertEqual(previous, saved)
        client.files[client.record['manifest']['patches'][0]['patch']] = b'wrong'
        with self.assertRaises(PatchError):
            build_catalog(previous, client)
        self.assertEqual(previous, saved)

    def test_reviewed_solution_rejects_changed_manifest_and_invalid_evidence(self):
        for problem in ('manifest', 'digest', 'reason', 'schema'):
            client, previous = self.reviewed_solution()
            if problem == 'manifest':
                client.files['BUILD-MANIFEST.json'] += b'\n'
                for asset in client.assets:
                    if asset['name'] == 'BUILD-MANIFEST.json':
                        raw = client.files[asset['name']]
                        asset.update(size=len(raw), digest='sha256:' + hashlib.sha256(raw).hexdigest())
            else:
                field, value = {'digest': ('manifest_sha256', '0' * 64),
                                'reason': ('reason', ''), 'schema': ('schema_version', 99)}[problem]
                previous['releases'][0]['solution_import'][field] = value
            with self.subTest(problem=problem), self.assertRaises(PatchError):
                build_catalog(previous, client)

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
