import copy
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from retro_trans import ps3_dlc as dlc
from retro_trans.core import PatchError, Cancelled


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def edat(number, body):
    cid = 'JP0700-NPJB00520_00-SRWZ3OF1DLC%05d' % number
    header = bytearray(128); header[:4] = b'NPD\0'; header[16:16 + len(cid)] = cid.encode()
    return bytes(header) + body


def fixture(root, count=2):
    source = root / 'original'; source.mkdir()
    base = root / 'game'; base.mkdir()
    (base / 'EBOOT.BIN').write_bytes(b'english executable')
    (base / 'TPACKPS3.CPK').write_bytes(b'english fonts')
    iso = root / 'game.iso'; iso.write_bytes(b'verified ISO')
    data = {'schema': dlc.SCHEMA, 'game_id': 'srw-z3-jigoku-ps3', 'name': 'Test DLC', 'version': '0.9.4',
            'disc_id': 'BLJS10256', 'dlc_title_id': 'NPJB00520',
            'base': {'version': '0.9.4', 'iso': identity(iso.read_bytes()),
                     'files': {p.name: identity(p.read_bytes()) for p in base.iterdir()}}, 'packs': []}
    for n in range(301, 301 + count):
        original, target = edat(n, b'Japanese'), edat(n, b'English translation')
        name = 'DLC%04d' % n
        (source / (name + '.EDAT')).write_bytes(original)
        data['packs'].append({'file': name + '.EDAT', 'content_id': 'JP0700-NPJB00520_00-SRWZ3OF1DLC%05d' % n,
                              'source': identity(original), 'target': identity(target),
                              'patch': dict(name=name + '.xdelta', **identity(target))})
    return data, source, base, iso


def bundle(root, data, extra=None, corrupt=False):
    target = root / 'patch.zip'
    with zipfile.ZipFile(target, 'w') as z:
        z.writestr(dlc.PROFILE, json.dumps(data))
        for row in data['packs']:
            raw = edat(int(row['file'][3:7]), b'English translation')
            z.writestr(row['patch']['name'], b'x' * len(raw) if corrupt else raw)
        if extra:
            z.writestr(extra, b'not permitted')
    return target


@contextmanager
def fake_engine(*args, **kwargs):
    yield Path('unused-engine')


def fake_decode(engine, source, delta, target, *args):
    shutil.copyfile(delta, target)


class DlcTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.data, self.source, self.base, self.iso = fixture(self.root)
        self.engine = patch.object(dlc, 'engine_context', fake_engine); self.engine.start()
        self.decode = patch.object(dlc, 'decode', side_effect=fake_decode); self.decoder = self.decode.start()

    def tearDown(self):
        self.decode.stop(); self.engine.stop(); self.tmp.cleanup()

    def apply(self, data=None, **kwargs):
        z = bundle(self.root, data or self.data)
        return dlc.apply(self.source, self.base, self.root / 'output', bundle=z, **kwargs)

    def test_subset_and_unrelated_files_preserved(self):
        (self.source / 'DLC0302.EDAT').unlink()
        (self.source / 'DLC9999.EDAT').write_bytes(b'leave me')
        (self.source / 'license.rap').write_bytes(b'private local license')
        before = {p.name: p.read_bytes() for p in self.source.iterdir()}
        output, message = self.apply()
        self.assertEqual({p.name for p in output.iterdir()}, {'DLC0301.EDAT', 'DLC-RESULT.json', 'INSTALL.txt'})
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.source.iterdir()})
        self.assertIn('Not installed', message)
        receipt = json.loads((output / 'DLC-RESULT.json').read_text())
        self.assertFalse(receipt['installed']); self.assertEqual(receipt['ignored_edat_files'], ['DLC9999.EDAT'])
        self.assertEqual(self.decoder.call_count, 1)

    def test_already_current_and_mixed_pack_versions(self):
        (self.source / 'DLC0301.EDAT').write_bytes(edat(301, b'English translation'))
        output, _ = self.apply()
        self.assertEqual(len(list(output.glob('*.EDAT'))), 2); self.assertEqual(self.decoder.call_count, 1)

    def test_iso_and_native_folder_dependencies(self):
        self.assertEqual(len(dlc.base_files(self.iso, self.data)), 1)
        native = self.base / 'PS3_GAME/USRDIR/DATA/TABATA'; native.mkdir(parents=True)
        shutil.move(self.base / 'EBOOT.BIN', self.base / 'PS3_GAME/USRDIR/EBOOT.BIN')
        shutil.move(self.base / 'TPACKPS3.CPK', native / 'TPACKPS3.CPK')
        self.assertEqual(len(dlc.base_files(self.base, self.data)), 2)

    def test_wrong_base_font_rejected_before_patching(self):
        (self.base / 'TPACKPS3.CPK').write_bytes(b'old Japanese font')
        with self.assertRaisesRegex(PatchError, 'Base executable/fonts'):
            self.apply()
        self.decoder.assert_not_called(); self.assertFalse((self.root / 'output').exists())

    def test_known_modified_dlc_stops_entire_job(self):
        (self.source / 'DLC0302.EDAT').write_bytes(edat(302, b'modified'))
        with self.assertRaisesRegex(PatchError, 'Unsupported or modified'):
            self.apply()
        self.decoder.assert_not_called()

    def test_content_id_and_preserved_header_checked(self):
        (self.source / 'DLC0301.EDAT').write_bytes(edat(302, b'Japanese'))
        with self.assertRaisesRegex(PatchError, 'content ID/header'):
            self.apply()

    def test_output_existing_and_inside_source_rejected(self):
        z = bundle(self.root, self.data)
        out = self.root / 'output'; out.mkdir(); (out / 'keep').write_text('safe')
        for target in (out, self.source / 'new'):
            with self.assertRaises(PatchError):
                dlc.apply(self.source, self.base, target, bundle=z)
        self.assertEqual((out / 'keep').read_text(), 'safe')

    def test_cancel_leaves_no_output(self):
        cancel = threading.Event(); cancel.set()
        with self.assertRaises(Cancelled):
            self.apply(cancel=cancel)
        self.assertFalse((self.root / 'output').exists())

    def test_bad_output_and_source_change_leave_no_output(self):
        def bad(engine, source, delta, target, *args):
            target.write_bytes(b'bad decode')
        self.decoder.side_effect = bad
        with self.assertRaisesRegex(PatchError, 'Translated DLC checksum'):
            self.apply()
        self.assertFalse((self.root / 'output').exists())
        def mutate(engine, source, delta, target, *args):
            fake_decode(engine, source, delta, target)
            source.write_bytes(edat(int(source.stem[3:]), b'changed during patch'))
        self.decoder.side_effect = mutate
        with self.assertRaisesRegex(PatchError, 'DLC input changed'):
            self.apply()
        self.assertFalse((self.root / 'output').exists())

    def test_archive_rejects_extra_license_traversal_and_corruption(self):
        for extra in ('work.bin', '../escape', 'LICENSE.RAP'):
            z = bundle(self.root, self.data, extra=extra)
            with self.assertRaises(PatchError):
                dlc.open_bundle(z)
        z = bundle(self.root, self.data, corrupt=True)
        with self.assertRaisesRegex(PatchError, 'delta checksum'):
            dlc.apply(self.source, self.base, self.root / 'output', bundle=z)
        self.decoder.assert_not_called()

    def test_strict_profile_paths_duplicates_and_sizes(self):
        bads = []
        for key, value in (('file', '../escape.EDAT'), ('file', 'CON.EDAT'), ('content_id', 'wrong')):
            data = copy.deepcopy(self.data); data['packs'][0][key] = value; bads.append(data)
        data = copy.deepcopy(self.data); data['packs'].append(data['packs'][0]); bads.append(data)
        data = copy.deepcopy(self.data); data['base']['files'].pop('TPACKPS3.CPK'); bads.append(data)
        data = copy.deepcopy(self.data); data['packs'][0]['source']['bytes'] = True; bads.append(data)
        for data in bads:
            with self.assertRaises(PatchError):
                dlc.validate(data)
        with self.assertRaisesRegex(PatchError, 'Duplicate JSON'):
            dlc.read_profile(b'{"schema":1,"schema":2}')

    def test_duplicate_native_locations_rejected(self):
        nested = self.source / 'USRDIR/DLC'; nested.mkdir(parents=True)
        shutil.copyfile(self.source / 'DLC0301.EDAT', nested / 'DLC0301.EDAT')
        with self.assertRaisesRegex(PatchError, 'Duplicate DLC pack'):
            dlc.select_packs(self.source, self.data)

    def test_output_race_preserves_new_existing_folder(self):
        def raced(engine, source, delta, target, *args):
            fake_decode(engine, source, delta, target)
            (self.root / 'output').mkdir(exist_ok=True)
            (self.root / 'output/keep').write_text('safe')
        self.decoder.side_effect = raced
        with self.assertRaisesRegex(PatchError, 'Output appeared'):
            self.apply()
        self.assertEqual((self.root / 'output/keep').read_text(), 'safe')

    def test_published_discovery_is_registered_repo_only(self):
        z = bundle(self.root, self.data)
        profile = self.root / dlc.PROFILE
        with zipfile.ZipFile(z) as archive:
            raw = archive.read(dlc.PROFILE)
        profile.write_bytes(raw)
        repo = 'retro-trans/SRW-Z3'; zip_name = 'SRW-Z3-v0.9.4' + dlc.SUFFIX
        def asset(name, path):
            return {'name': name, 'size': path.stat().st_size, 'digest': 'sha256:' + identity(path.read_bytes())['sha256'],
                    'browser_download_url': 'https://github.com/' + repo + '/releases/download/v0.9.4/' + name}
        class Client:
            def releases(s, selected, cancel):
                self.assertEqual(selected, repo)
                return [{'tag_name': 'v0.9.4', 'assets': [asset(dlc.PROFILE, profile), asset(zip_name, z)]}]
            def download(s, item, *args):
                return profile if item.name == dlc.PROFILE else z
        library = {'games': [{'game_id': self.data['game_id'], 'repo': repo,
                              'package_ids': [{'platform': 'PS3', 'kind': 'title-id', 'id': 'BLJS10256'}]}]}
        with patch('retro_trans.game_library.load', return_value=library):
            found, found_raw = dlc.discover(self.source, self.base, client=Client())
        self.assertEqual(found, z); self.assertEqual(found_raw, raw)

    def test_profile_zip_mismatch_rejected(self):
        z = bundle(self.root, self.data)
        with self.assertRaisesRegex(PatchError, 'profiles differ'):
            dlc.open_bundle(z, b'other profile')

    def test_publication_registration_requires_every_content_id(self):
        from retro_trans.game_library_builder import validate_release
        path = self.root / dlc.PROFILE; path.write_text(json.dumps(self.data))
        ids = [{'platform': 'PS3', 'kind': 'title-id', 'id': value} for value in ('BLJS10256', 'NPJB00520')]
        library = {'schema_version': 1, 'vita_releases': [], 'games': [dict(
            game_id=self.data['game_id'], name='Test', repo='retro-trans/SRW-Z3', package_ids=ids)]}
        with self.assertRaisesRegex(PatchError, 'every DLC content ID'):
            validate_release(path, 'retro-trans/SRW-Z3', library)
        ids.extend(dict(platform='PS3', kind='content-id', id=r['content_id']) for r in self.data['packs'])
        validate_release(path, 'retro-trans/SRW-Z3', library)

    def catalog_client(self):
        from test_catalog import record
        from test_catalog_builder import ReleaseClient
        item = record(); item['tag'] = 'v' + self.data['version']
        item['manifest'].update(version=self.data['version'], game_id=self.data['game_id'], platform='PS3')
        for row in item['manifest']['patches']:
            row.update(target_format='iso', target_bytes=self.data['base']['iso']['bytes'],
                       target_sha256=self.data['base']['iso']['sha256'])
        client = ReleaseClient(item)
        z = bundle(self.root, self.data)
        with zipfile.ZipFile(z) as archive:
            raw = archive.read(dlc.PROFILE)
        client.files[dlc.PROFILE] = raw
        client.files['Test' + dlc.SUFFIX] = z.read_bytes()
        client.files['DLC-VALIDATION.json'] = json.dumps(dict(
            profile_sha256=hashlib.sha256(raw).hexdigest(), roundtrips=2, all_passed=True)).encode()
        self.refresh_assets(client)
        return client

    @staticmethod
    def refresh_assets(client):
        client.files['SHA256SUMS.txt'] = ''.join(hashlib.sha256(v).hexdigest() + '  ' + k + '\n'
            for k, v in client.files.items() if k != 'SHA256SUMS.txt').encode()
        client.assets = [dict(name=k, size=len(v), digest='sha256:' + hashlib.sha256(v).hexdigest(),
                             browser_download_url=client.prefix + k) for k, v in client.files.items()]

    def test_catalog_validates_and_preserves_dlc_extras_and_ps3_routes(self):
        from retro_trans.catalog_builder import build_catalog
        from retro_trans.catalog import Catalog, assert_immutable
        client = self.catalog_client()
        previous = dict(schema_version=1, releases=[])
        result = build_catalog(previous, client)
        self.assertEqual(result['releases'][0]['manifest'], client.record['manifest'])
        self.assertIn('ps3_dlc', result['releases'][0])
        self.assertEqual(build_catalog(result, client), result)
        assert_immutable(Catalog(result), Catalog(result))
        changed = copy.deepcopy(result)
        changed['releases'][0]['ps3_dlc']['profile']['sha256'] = 'a' * 64
        with self.assertRaisesRegex(PatchError, 'published DLC metadata'):
            assert_immutable(Catalog(result), Catalog(changed))
        del client.files[dlc.PROFILE]; self.refresh_assets(client)
        with self.assertRaises(PatchError):
            build_catalog(result, client)

    def test_catalog_rejects_incompatible_base_or_false_proof(self):
        from retro_trans.catalog_builder import build_catalog
        for error in ('base', 'proof', 'checksum', 'zip'):
            client = self.catalog_client()
            if error == 'base':
                data = copy.deepcopy(self.data); data['base']['iso']['sha256'] = 'a' * 64
                z = bundle(self.root, data)
                client.files['Test' + dlc.SUFFIX] = z.read_bytes()
                with zipfile.ZipFile(z) as archive:
                    client.files[dlc.PROFILE] = archive.read(dlc.PROFILE)
            elif error == 'proof':
                client.files['DLC-VALIDATION.json'] = b'{}'
            elif error == 'zip':
                client.files['Test' + dlc.SUFFIX] = bundle(self.root, self.data, corrupt=True).read_bytes()
            self.refresh_assets(client)
            if error == 'checksum':
                client.files['SHA256SUMS.txt'] = b''.join(line for line in
                    client.files['SHA256SUMS.txt'].splitlines(keepends=True) if dlc.PROFILE.encode() not in line)
                for a in client.assets:
                    if a['name'] == 'SHA256SUMS.txt':
                        a['size'] = len(client.files[a['name']]); a['digest'] = 'sha256:' + hashlib.sha256(client.files[a['name']]).hexdigest()
            with self.subTest(error=error), self.assertRaises(PatchError):
                build_catalog(dict(schema_version=1, releases=[]), client)


if __name__ == '__main__':
    unittest.main()
