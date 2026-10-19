import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from retro_trans.catalog_builder import build_catalog, main
from retro_trans.core import Cancelled, GitHubClient, PatchError
from test_catalog import record
from test_catalog_builder import ReleaseClient
from test_vita_repatch import fixture


EMPTY = dict(schema_version=1, releases=[])


def named_client(repo):
    row = record()
    row['repo'] = 'retro-trans/' + repo
    return ReleaseClient(row)


class BatchClient(GitHubClient):
    def __init__(self, *clients):
        self.clients = clients

    def repositories(self):
        return list(dict.fromkeys(c.record['repo'] for c in self.clients))

    def releases(self, repo):
        return [r for c in self.clients if c.record['repo'] == repo for r in c.releases(repo)]

    def open(self, url):
        for client in self.clients:
            if url.startswith(client.prefix):
                return client.open(url)
        raise AssertionError('Unexpected download')


def add_asset(client, name, raw):
    client.files[name] = raw
    client.assets = [a for a in client.assets if a['name'] != name]
    client.assets.append(dict(name=name, size=len(raw),
        digest='sha256:' + hashlib.sha256(raw).hexdigest(), browser_download_url=client.prefix + name))


def generic_vita_client():
    row = record()
    row.update(repo='retro-trans/Cross-Ange', tag='v0.1.13')
    row['manifest'].update(version='0.1.13', game_id='cross-ange', platform='PS Vita')
    client = ReleaseClient(row)
    data, _, targets = fixture()
    data.update(title_id='PCSG00597', build='0.1.13', auth=None, minimum_app_version='0.5.14',
        package=dict(bytes=1234, sha256='1'*64, content_id='JP0700-PCSG00597_00-' + 'A'*16))
    component = data['files'][1]
    delta = targets[component['path']]
    component['path'] = 'cpk/Ange.cpk'
    component['patch']['name'] = 'VITA-Cross-Ange-archive.xdelta'
    data['files'] = [component]
    credits = b'credit picture'
    data['extras'] = [dict(path='sce_sys/manual/025.png', asset=dict(
        name='VITA-credits.png', bytes=len(credits), sha256=hashlib.sha256(credits).hexdigest()))]
    raw = json.dumps(data).encode()
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('VITA-REPATCH.json', raw)
        bundle.writestr(component['patch']['name'], delta)
        bundle.writestr('VITA-credits.png', credits)
    add_asset(client, 'VITA-REPATCH.json', raw)
    add_asset(client, 'Cross-Ange-Vita-rePatch-patches.zip', archive.getvalue())
    return client


class RefreshIsolationTests(unittest.TestCase):
    def test_generic_asset_only_vita_extras_and_credits_are_validated(self):
        client = generic_vita_client()
        result = build_catalog(EMPTY, client)
        entry = result['releases'][0]
        self.assertEqual(entry['vita_repatch']['title_id'], 'PCSG00597')
        self.assertEqual(entry['vita_min_app_version'], '0.5.16')
        self.assertEqual(entry['manifest'], client.record['manifest'])
        self.assertEqual(build_catalog(result, client), result)
        self.assertEqual(set(entry['assets']), {p['patch'] for p in entry['manifest']['patches']})

    def test_generic_zip_still_rejects_bad_credits_and_undeclared_licenses(self):
        for failure in ('missing', 'corrupt', 'license'):
            client = generic_vita_client()
            name = 'Cross-Ange-Vita-rePatch-patches.zip'
            original = zipfile.ZipFile(io.BytesIO(client.files[name]))
            rebuilt = io.BytesIO()
            with zipfile.ZipFile(rebuilt, 'w') as bundle:
                for item in original.namelist():
                    if failure == 'missing' and item == 'VITA-credits.png':
                        continue
                    bundle.writestr(item, b'wrong' if failure == 'corrupt' and item == 'VITA-credits.png'
                                    else original.read(item))
                if failure == 'license':
                    bundle.writestr('work.bin', b'not allowed')
            add_asset(client, name, rebuilt.getvalue())
            with self.subTest(failure=failure), self.assertRaises(PatchError):
                build_catalog(EMPTY, client)

    def test_generic_profile_and_zip_identities_remain_immutable(self):
        for name in ('VITA-REPATCH.json', 'Cross-Ange-Vita-rePatch-patches.zip'):
            client = generic_vita_client()
            previous = build_catalog(EMPTY, client)
            add_asset(client, name, client.files[name] + b'\n')
            with self.subTest(name=name), self.assertRaisesRegex(PatchError, 'identity changed'):
                build_catalog(previous, client)

    def test_checksum_listed_supplemental_files_are_downloaded_and_verified(self):
        for failure in (None, 'missing', 'corrupt', 'digest', 'unsafe', 'large'):
            client = ReleaseClient()
            name = 'credits-extras.zip'
            raw = b'bounded non-executable extra'
            add_asset(client, name, raw)
            sums = client.files['SHA256SUMS.txt'] + (hashlib.sha256(raw).hexdigest() + '  ' + name + '\n').encode()
            add_asset(client, 'SHA256SUMS.txt', sums)
            if failure == 'missing':
                client.assets = [a for a in client.assets if a['name'] != name]
            elif failure == 'corrupt':
                client.files[name] = b'changed'
            elif failure == 'digest':
                next(a for a in client.assets if a['name'] == name)['digest'] = 'sha256:' + '0'*64
            elif failure == 'unsafe':
                add_asset(client, 'SHA256SUMS.txt', sums.replace(name.encode(), b'../work.bin'))
            elif failure == 'large':
                next(a for a in client.assets if a['name'] == name)['size'] = 64*1024**2 + 1
            with self.subTest(failure=failure):
                if failure:
                    with self.assertRaises(PatchError):
                        build_catalog(EMPTY, client)
                else:
                    self.assertEqual(len(build_catalog(EMPTY, client)['releases']), 1)

    def test_bad_new_release_does_not_block_a_good_release_in_either_order(self):
        for order in (False, True):
            bad, good = named_client('bad'), named_client('good')
            del bad.files['VALIDATION.json']
            bad.assets = [a for a in bad.assets if a['name'] != 'VALIDATION.json']
            clients = (good, bad) if order else (bad, good)
            rejected = []
            result = build_catalog(EMPTY, BatchClient(*clients), rejections=rejected)
            self.assertEqual([r['repo'] for r in result['releases']], ['retro-trans/good'])
            self.assertEqual(rejected[0]['repo'], 'retro-trans/bad')
            self.assertEqual(rejected[0]['action'], 'skipped')
            with self.assertRaises(PatchError):
                build_catalog(EMPTY, BatchClient(*clients))

    def test_rejected_known_release_keeps_its_previous_record(self):
        bad, good = named_client('bad'), named_client('good')
        previous = build_catalog(EMPTY, bad)
        saved = copy.deepcopy(previous)
        bad.files[bad.record['manifest']['patches'][0]['patch']] = b'corrupt'
        rejected = []
        result = build_catalog(previous, BatchClient(bad, good), rejections=rejected)
        self.assertIn(saved['releases'][0], result['releases'])
        self.assertEqual(previous, saved)
        self.assertEqual(rejected[0]['action'], 'retained')
        self.assertEqual(len(result['releases']), 2)

    def test_conflicting_binary_identity_is_quarantined_before_catalog_mutation(self):
        known, good = named_client('known'), named_client('good')
        previous = build_catalog(EMPTY, known)
        row = record(source='1.1', target='1.2')
        row['repo'] = 'retro-trans/changed'
        row['manifest']['patches'][0]['source_sha256'] = 'f'*64
        changed = ReleaseClient(row)
        rejected = []
        result = build_catalog(previous, BatchClient(changed, good), rejections=rejected)
        self.assertEqual(len(result['releases']), 2)
        self.assertEqual(rejected[0]['repo'], 'retro-trans/changed')
        self.assertNotIn('retro-trans/changed', [r['repo'] for r in result['releases']])

    def test_repository_error_is_reported_without_losing_cached_entries(self):
        bad, good = named_client('bad'), named_client('good')
        previous = build_catalog(EMPTY, bad)
        batch = BatchClient(bad, good)
        original = batch.releases
        def releases(repo):
            if repo == 'retro-trans/bad':
                raise PatchError('Repository download failed')
            return original(repo)
        batch.releases = releases
        rejected = []
        result = build_catalog(previous, batch, rejections=rejected)
        self.assertIn(previous['releases'][0], result['releases'])
        self.assertEqual(len(result['releases']), 2)
        self.assertIsNone(rejected[0]['tag'])

    def test_cancel_and_programming_errors_are_not_silently_skipped(self):
        for error in (Cancelled(), RuntimeError('bug')):
            with self.subTest(error=type(error).__name__), patch(
                    'retro_trans.catalog_builder.release_record', side_effect=error):
                with self.assertRaises(type(error)):
                    build_catalog(EMPTY, ReleaseClient(), rejections=[])

    def test_missing_known_manifest_is_reported_and_retained(self):
        client = ReleaseClient()
        previous = build_catalog(EMPTY, client)
        client.assets = [a for a in client.assets if a['name'] != 'BUILD-MANIFEST.json']
        rejected = []
        self.assertEqual(build_catalog(previous, client, rejections=rejected), previous)
        self.assertIn('manifest', rejected[0]['error'].lower())

    def test_cli_writes_partial_report_and_verified_catalog(self):
        bad, good = named_client('bad'), named_client('good')
        bad.files['VALIDATION.json'] = b'{}'
        with tempfile.TemporaryDirectory() as temporary:
            output, report = Path(temporary)/'catalog.json', Path(temporary)/'report.json'
            output.write_text(json.dumps(EMPTY))
            args = ['catalog_builder', '--output', str(output), '--continue-on-error', '--report', str(report)]
            with patch('sys.argv', args), patch('retro_trans.catalog_builder.GitHubClient',
                    return_value=BatchClient(bad, good)), patch('sys.stdout', io.StringIO()), patch('sys.stderr', io.StringIO()):
                main()
            self.assertEqual(json.loads(report.read_text())['status'], 'partial')
            self.assertEqual(len(json.loads(output.read_text())['releases']), 1)

    def test_cli_report_cannot_overwrite_catalog(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/'catalog.json'
            output.write_bytes(b'keep')
            with patch('sys.argv', ['builder', '--output', str(output), '--report', str(output)]), patch('sys.stderr', io.StringIO()):
                with self.assertRaises(SystemExit):
                    main()
            self.assertEqual(output.read_bytes(), b'keep')


if __name__ == '__main__':
    unittest.main()
