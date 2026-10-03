import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from retro_trans.catalog import Catalog, apply_plan, assert_immutable, recognize, scan_root, validate_manifest
from retro_trans.catalog_builder import build_catalog
from retro_trans.core import Cancelled, GitHubClient, PatchError
from retro_trans.release import build_release, validate_directory
from retro_trans.solutions import SolutionSource, publish_directory


def content(track, version):
    return (bytes(range(256)) * (400 + track)) + ('track {} version {}'.format(track, version)).encode()


def grouped_record(source='original', target='1.1', copies=False):
    patches = []
    for track in (3, 17):
        p = dict(patch='track{}-{}-{}.xdelta'.format(track, source, target), edition='Track ' + str(track),
                 language='en', source_version=source, source_format='bin', target_format='bin',
                 patch_sha256=hashlib.sha256(b'delta').hexdigest(), patch_bytes=5)
        for side, version in (('source', source), ('target', target)):
            raw = content(track, version)
            p[side + '_sha256'], p[side + '_bytes'] = hashlib.sha256(raw).hexdigest(), len(raw)
        patches.append(p)
    solution = dict(id='japan-disc', name='Complete English disc', edition='Japan', language='en',
                    files=[dict(edition='Track ' + str(t), output_name='track{}.bin'.format(t)) for t in (3, 17)])
    if copies:
        solution['copy_files'] = [dict(name='disc.cue', bytes=3, sha256=hashlib.sha256(b'cue').hexdigest())]
    manifest = dict(schema_version=2, game_id='multi-game', game_name='Multi Game', platform='Dreamcast',
                    version=target, source_commit='a' * 40, patches=patches, solutions=[solution])
    return dict(repo='retro-trans/multi-game', tag='v' + target, manifest=manifest,
                assets={p['patch']: 'https://github.com/retro-trans/multi-game/releases/download/v{}/{}'.format(target, p['patch']) for p in patches})


def make_catalog(*records):
    return Catalog(dict(schema_version=1, releases=list(records)))


class SolutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        for track in (3, 17):
            (self.root / 'renamed{}.bin'.format(track)).write_bytes(content(track, 'original'))
        self.cat = make_catalog(grouped_record(), grouped_record('1.1', '1.2'))

    def tearDown(self):
        self.temporary.cleanup()

    def test_group_recognition_browsing_and_all_route_modes(self):
        matches = scan_root(self.root, self.cat)
        self.assertEqual(len(matches), 1)
        source = matches[0][1]
        self.assertIsInstance(source, SolutionSource)
        self.assertEqual(source.version, 'original')
        for selected in (self.root, self.root / 'renamed3.bin'):
            self.assertEqual(recognize(selected, self.cat)[0].family, source.family)
        latest = self.cat.plan(source)
        self.assertEqual(latest.target.version, '1.2')
        self.assertEqual(len(latest.edges), 4)
        self.assertIn('original → 1.1 → 1.2', latest.details)
        self.assertEqual(self.cat.plan(source, 'Next version only').target.version, '1.1')
        self.assertEqual(self.cat.plan(source, '1.1').target.version, '1.1')
        (self.root / 'disc.cue').write_bytes(b'cue')
        self.assertEqual(len(recognize(self.root / 'disc.cue', self.cat)), 1)
        (self.root / 'renamed3.bin').write_bytes(content(3, '1.1'))
        mixed = recognize(self.root, self.cat)[0]
        self.assertEqual(mixed.version, 'mixed versions')
        self.assertEqual(len(self.cat.plan(mixed, 'Next version only').edges), 1)
        for track in (3, 17):
            (self.root / 'renamed{}.bin'.format(track)).write_bytes(content(track, '1.2'))
        current = recognize(self.root, self.cat)[0]
        self.assertEqual(self.cat.plan(current).edges, ())
        with self.assertRaises(PatchError):
            self.cat.plan(current, '1.1')

    def test_missing_duplicate_unknown_and_nested_files(self):
        nested = self.root / 'nested'
        nested.mkdir()
        track = self.root / 'renamed17.bin'
        track.rename(nested / track.name)
        partial = recognize(self.root, self.cat)[0]
        self.assertIn('incomplete', partial.label)
        with self.assertRaisesRegex(PatchError, 'track17.bin'):
            self.cat.plan(partial)
        track.write_bytes(b'unknown')
        self.assertTrue(recognize(self.root, self.cat)[0].problems)
        track.write_bytes(content(17, 'original'))
        (self.root / 'duplicate.bin').write_bytes(content(17, 'original'))
        with self.assertRaisesRegex(PatchError, 'Multiple matching'):
            self.cat.plan(recognize(self.root, self.cat)[0])
        (self.root / 'renamed3.bin').unlink()
        track.unlink()
        (self.root / 'duplicate.bin').unlink()
        self.assertEqual(scan_root(self.root, self.cat), [])

    def test_missing_unchanged_files_and_unreachable_latest(self):
        cat = make_catalog(grouped_record(copies=True))
        with self.assertRaisesRegex(PatchError, 'disc.cue'):
            cat.plan(recognize(self.root, cat)[0])
        (self.root / 'disc.cue').write_bytes(b'cue')
        self.assertEqual(len(cat.plan(recognize(self.root, cat)[0]).edges), 2)
        newer = grouped_record('1.2', '1.3')
        cat = make_catalog(grouped_record(), newer)
        plan = cat.plan(recognize(self.root, cat)[0])
        self.assertEqual(plan.target.version, '1.1')
        self.assertIn('latest published: 1.3', plan.summary)
        self.assertFalse(plan.latest_reachable)

    def test_identical_component_versions_need_no_reverse_patch(self):
        first, second = grouped_record(), grouped_record('1.1', '1.2')
        unchanged = second['manifest']['patches'][0]
        unchanged['target_sha256'] = unchanged['source_sha256']
        unchanged['target_bytes'] = unchanged['source_bytes']
        cat = make_catalog(first, second)
        (self.root / 'renamed3.bin').write_bytes(content(3, '1.1'))
        source = recognize(self.root, cat)[0]
        self.assertEqual(source.found['Track 3'][1].version, '1.2')
        plan = cat.plan(source, '1.1')
        self.assertEqual(len(plan.edges), 1)
        self.assertEqual(plan.parts[0][2].edges, ())
        self.assertEqual(cat.plan(source, 'Next version only').target.version, '1.1')

    def test_browsed_track_is_only_hashed_once(self):
        from retro_trans.catalog import file_hashes
        path = self.root / 'renamed3.bin'
        with patch('retro_trans.catalog.file_hashes', wraps=file_hashes) as hashing:
            recognize(path, self.cat)
        self.assertEqual(sum(call.args[0] == path for call in hashing.call_args_list), 1)

    def test_automatic_backend_refuses_applying_only_one_group_component(self):
        source = recognize(self.root, self.cat)[0]
        path, node = source.found['Track 3']
        with self.assertRaisesRegex(PatchError, 'complete folder'):
            apply_plan(path, self.root / 'partial.bin', self.cat.plan(node), self.cat)

    def test_manifest_rejections_and_immutability(self):
        for failure in ('v1', 'missing', 'path', 'reserved', 'duplicate', 'copy_collision', 'copy_hash', 'legacy'):
            row = grouped_record(copies=True)
            m = row['manifest']
            s = m['solutions'][0]
            if failure == 'v1':
                m['schema_version'] = 1
            elif failure == 'missing':
                s['files'][0]['edition'] = 'missing'
            elif failure == 'path':
                s['files'][0]['output_name'] = '../escape.bin'
            elif failure == 'reserved':
                s['files'][0]['output_name'] = 'CON.bin'
            elif failure == 'duplicate':
                s['files'][0]['output_name'] = 'TRACK17.BIN'
            elif failure == 'copy_collision':
                s['copy_files'][0]['name'] = 'track3.bin'
            elif failure == 'copy_hash':
                s['copy_files'][0]['sha256'] = 'bad'
            with self.subTest(failure=failure), self.assertRaises(PatchError):
                validate_manifest(m, legacy=failure == 'legacy')
        changed = copy.deepcopy(self.cat.data)
        changed['releases'][0]['manifest']['solutions'][0]['files'][0]['output_name'] = 'different.bin'
        with self.assertRaisesRegex(PatchError, 'solution'):
            assert_immutable(self.cat, Catalog(changed))
        removed = copy.deepcopy(self.cat.data)
        for r in removed['releases']:
            r['manifest'].pop('solutions')
            r['manifest']['schema_version'] = 1
        with self.assertRaisesRegex(PatchError, 'solution'):
            assert_immutable(self.cat, Catalog(removed))

    def test_solution_withdrawal_and_component_changes(self):
        previous = make_catalog(grouped_record())
        data = copy.deepcopy(previous.data)
        withdrawn = data['releases'].pop()
        withdrawn['reason'] = 'Withdrawn complete solution.'
        data['withdrawn_releases'] = [withdrawn]
        current = Catalog(data)
        assert_immutable(previous, current)
        self.assertEqual(scan_root(self.root, current), [])
        changed = grouped_record('1.1', '1.2')
        changed['manifest']['solutions'][0]['files'][1]['edition'] = 'different'
        changed['manifest']['patches'][1]['edition'] = 'different'
        with self.assertRaisesRegex(PatchError, 'components'):
            make_catalog(grouped_record(), changed)

    def test_cancellation_low_disk_source_change_and_output_race(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            scan_root(self.root, self.cat, cancel)
        plan = self.cat.plan(recognize(self.root, self.cat)[0])
        client = Mock()
        with patch('retro_trans.solutions.shutil.disk_usage', return_value=Mock(free=0)):
            with self.assertRaisesRegex(PatchError, 'free space'):
                apply_plan(self.root, self.root / 'out', plan, self.cat, client)
        (self.root / 'renamed17.bin').write_bytes(b'changed')
        with self.assertRaisesRegex(PatchError, 'changed'):
            apply_plan(self.root, self.root / 'out', plan, self.cat, client)
        client.download.assert_not_called()
        stage, output = self.root / 'stage', self.root / 'existing'
        stage.mkdir()
        (stage / 'file.bin').write_bytes(b'final')
        output.mkdir()
        with self.assertRaises(FileExistsError):
            publish_directory(stage, output)
        self.assertEqual(list(output.iterdir()), [])
        self.assertTrue((stage / 'file.bin').exists())


@unittest.skipUnless(os.name == 'nt', 'Bundled xdelta engine is Windows x64')
class SolutionRoundTrips(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.inputs = self.root / 'inputs'
        self.inputs.mkdir()
        for track in (3, 17):
            for version in ('original', '1.1', '1.2'):
                (self.root / '{}-{}.bin'.format(track, version)).write_bytes(content(track, version))
            (self.inputs / 'renamed{}.bin'.format(track)).write_bytes(content(track, 'original'))
        (self.inputs / 'audio.bin').write_bytes(b'audio' * 8192)
        (self.inputs / 'disc.cue').write_bytes(b'FILE "track3.bin" BINARY\nFILE "audio.bin" BINARY\nFILE "track17.bin" BINARY\n')
        (self.inputs / 'private.txt').write_text('Do not copy unrelated files')
        records, self.deltas = [], {}
        for source, target in (('original', '1.1'), ('1.1', '1.2')):
            config = grouped_record(source, target)['manifest']
            for p, track in zip(config['patches'], (3, 17)):
                p['source'], p['target'] = '{}-{}.bin'.format(track, source), '{}-{}.bin'.format(track, target)
            config['solutions'][0]['copy_files'] = [dict(name=name, source='inputs/' + name) for name in ('audio.bin', 'disc.cue')]
            config_file = self.root / (target + '.json')
            config_file.write_text(json.dumps(config), encoding='utf-8')
            directory = self.root / ('release-' + target)
            manifest = build_release(config_file, directory, cache=self.root / 'cache')
            self.assertEqual(validate_directory(directory), manifest)
            self.assertEqual(manifest['schema_version'], 2)
            self.assertNotIn(str(self.root), json.dumps(manifest))
            self.assertNotIn('source', manifest['solutions'][0]['copy_files'][0])
            record = grouped_record(source, target)
            record['manifest'] = manifest
            records.append(record)
            self.deltas.update({p.name: p for p in directory.glob('*.xdelta')})
        self.cat = make_catalog(*records)
        self.client = Mock()
        self.client.download.side_effect = lambda asset, *args: self.deltas[asset.name]

    def tearDown(self):
        self.temporary.cleanup()

    def apply(self, output='out', catalog=None, cancel=None, progress=None):
        catalog = catalog or self.cat
        source = recognize(self.inputs, catalog)[0]
        return apply_plan(self.inputs, self.root / output, catalog.plan(source), catalog,
                          self.client, self.root / 'cache', cancel, progress)

    def test_offline_real_xdelta_chains_copy_cue_audio_and_recognize_result(self):
        # One component is already current: it must be copied, not omitted.
        (self.inputs / 'renamed3.bin').write_bytes(content(3, '1.2'))
        with patch('retro_trans.core.GitHubClient.open', side_effect=AssertionError('Network used')):
            result = self.apply()
        self.assertEqual({p.name for p in result.iterdir()}, {'track3.bin', 'track17.bin', 'audio.bin', 'disc.cue'})
        for track in (3, 17):
            self.assertEqual((result / 'track{}.bin'.format(track)).read_bytes(), content(track, '1.2'))
        self.assertEqual((self.inputs / 'renamed17.bin').read_bytes(), content(17, 'original'))
        self.assertEqual((result / 'disc.cue').read_bytes(), (self.inputs / 'disc.cue').read_bytes())
        self.assertEqual(self.cat.plan(recognize(result, self.cat)[0]).edges, ())
        self.assertEqual(list(self.root.glob('.retro-trans-solution-*')), [])
        with self.assertRaises(PatchError):
            self.apply()

    def test_second_component_failure_and_cancel_leave_no_partial_folder(self):
        from retro_trans.core import decode
        def fail_second(engine, source, delta, output, *args):
            if 'track17-' in delta.name:
                raise PatchError('Second component failed')
            return decode(engine, source, delta, output, *args)
        with patch('retro_trans.solutions.decode', side_effect=fail_second):
            with self.assertRaisesRegex(PatchError, 'Second component'):
                self.apply()
        self.assertFalse((self.root / 'out').exists())
        self.assertEqual(list(self.root.glob('.retro-trans-solution-*')), [])
        cancel = threading.Event()
        def progress(message, fraction):
            if 'track17.bin • Step' in message:
                cancel.set()
        with self.assertRaises(Cancelled):
            self.apply(cancel=cancel, progress=progress)
        self.assertFalse((self.root / 'out').exists())
        self.assertEqual(list(self.root.glob('.retro-trans-solution-*')), [])

    def test_corrupt_intermediate_and_unchanged_file_rejected(self):
        data = copy.deepcopy(self.cat.data)
        data['releases'][-1]['manifest']['patches'][-1]['target_sha256'] = '0' * 64
        with self.assertRaisesRegex(PatchError, 'Intermediate'):
            self.apply(catalog=Catalog(data))
        self.assertFalse((self.root / 'out').exists())
        self.client.download.reset_mock()
        (self.inputs / 'audio.bin').write_bytes(b'wrong' * 8192)
        with self.assertRaisesRegex(PatchError, 'verification failed'):
            self.apply()
        self.client.download.assert_not_called()
        self.assertFalse((self.root / 'out').exists())

    def test_remote_catalog_import_of_grouped_release(self):
        directory = self.root / 'release-1.1'
        files = {p.name: p.read_bytes() for p in directory.iterdir()}
        prefix = 'https://github.com/retro-trans/multi-game/releases/download/v1.1/'
        class Client(GitHubClient):
            def releases(self, repo):
                return [dict(tag_name='v1.1', assets=[dict(name=k, size=len(v), browser_download_url=prefix+k,
                    digest='sha256:' + hashlib.sha256(v).hexdigest()) for k, v in files.items()])]
            def open(self, url):
                return io.BytesIO(files[url[len(prefix):]])
        data = build_catalog(dict(schema_version=1, releases=[]), Client(), ['retro-trans/multi-game'])
        catalog = Catalog(data)
        self.assertEqual(len(catalog.solutions), 1)
        self.assertEqual(len(catalog.plan(recognize(self.inputs, catalog)[0]).edges), 2)


if __name__ == '__main__':
    unittest.main()
