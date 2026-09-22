"""Real offline chdman/xdelta round trips using synthetic disc bytes only."""
import hashlib
import os
from pathlib import Path
import struct
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from retro_trans import chd
from retro_trans.catalog import Catalog, apply_plan, recognize, scan_root
from retro_trans.core import Cancelled, PatchError, manual_patch


@unittest.skipUnless(os.name == 'nt', 'Bundled Windows x64 engines')
class ChdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory()
        cls.base = Path(cls.fixture.name)
        cls.original = bytes(range(256)) * 2048
        cls.translated = cls.original[:8192] + b'English translation!' + cls.original[8212:]
        cls.iso = cls.base / 'source.iso'
        cls.iso.write_bytes(cls.original)
        cls.target = cls.base / 'target.iso'
        cls.target.write_bytes(cls.translated)
        cls.delta = cls.base / 'translation.xdelta'
        manual_patch(cls.iso, cls.target, cls.delta, create=True, cache=cls.base / 'cache')
        with chd.engine_context() as engine:
            chd.run(engine, ['createdvd', '-i', cls.iso, '-o', cls.base / 'dvd.chd', '-c', 'zlib'], 'Fixture DVD')
            chd.run(engine, ['createcd', '-i', cls.iso, '-o', cls.base / 'cd.chd'], 'Fixture CD')
        p = {'patch': cls.delta.name, 'edition': 'original', 'language': 'en', 'source_version': 'original',
             'source_format': 'iso', 'target_format': 'iso', 'patch_sha256': hashlib.sha256(cls.delta.read_bytes()).hexdigest(),
             'patch_bytes': cls.delta.stat().st_size}
        for name, data in (('source', cls.original), ('target', cls.translated)):
            p.update({name + '_bytes': len(data), name + '_sha256': hashlib.sha256(data).hexdigest(),
                      name + '_sha1': hashlib.sha1(data).hexdigest()})
        cls.record = {'repo': 'retro-trans/test', 'tag': 'v1.0', 'manifest': {
            'schema_version': 1, 'game_id': 'chd-test', 'game_name': 'CHD test', 'platform': 'PS2', 'version': '1.0',
            'source_commit': 'a' * 40, 'patches': [p]}, 'assets': {
                cls.delta.name: 'https://github.com/retro-trans/test/releases/download/v1.0/' + cls.delta.name}}

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.cat = Catalog({'schema_version': 1, 'releases': [self.record]})
        self.downloads = []
        owner = self
        class Local:
            def download(self, asset, *args):
                owner.downloads.append(asset.name)
                return owner.delta
        self.client = Local()

    def tearDown(self):
        self.temporary.cleanup()

    def plan(self, source=None):
        return self.cat.plan(recognize(source or self.iso, self.cat)[0])

    def assert_clean(self):
        self.assertEqual(list(self.root.glob('.retro-*')), [])

    def test_dvd_header_hint_recognition_needs_no_extraction(self):
        source = self.root / 'renamed.data'
        source.write_bytes((self.base / 'dvd.chd').read_bytes())
        self.assertTrue(chd.is_chd(source))
        with patch('retro_trans.chd.prepared_source', side_effect=AssertionError('unnecessary extraction')):
            self.assertEqual(recognize(source, self.cat)[0].version, 'original')
        (self.root / 'bad.chd').write_bytes(b'bad')
        self.assertEqual([p.name for p, n in scan_root(self.root, self.cat)], ['renamed.data'])

    def test_sha256_only_and_cd_recognition_hash_extracted_bytes(self):
        import copy
        record = copy.deepcopy(self.record)
        for field in ('source_sha1', 'target_sha1'):
            record['manifest']['patches'][0].pop(field)
        cat = Catalog({'schema_version': 1, 'releases': [record]})
        with patch('retro_trans.chd.cache_directory', return_value=self.root / 'cache'):
            for name in ('dvd.chd', 'cd.chd'):
                self.assertEqual(recognize(self.base / name, cat)[0].version, 'original')
        self.assertEqual(list((self.root / 'cache/chd').iterdir()), [])

    def test_chd_inputs_patch_to_verified_iso_and_chd_offline(self):
        with patch('retro_trans.core.GitHubClient.open', side_effect=AssertionError('network used')):
            for name in ('dvd.chd', 'cd.chd'):
                source = self.base / name
                before = source.read_bytes()
                for packed in (False, True):
                    output = self.root / (name + ('.patched.chd' if packed else '.iso'))
                    apply_plan(source, output, self.plan(), self.cat, self.client,
                               cache=self.root / 'cache', chd_output=packed)
                    with chd.prepared_source(output, self.root) as (disc, layout):
                        self.assertEqual(disc.read_bytes(), self.translated)
                    if packed:
                        self.assertEqual(chd.inspect_chd(output).kind, chd.inspect_chd(source).kind)
                self.assertEqual(source.read_bytes(), before)
        self.assert_clean()

    def test_iso_to_chd_and_manual_extraction(self):
        output = self.root / 'from-iso.chd'
        apply_plan(self.iso, output, self.plan(), self.cat, self.client, cache=self.root / 'cache', chd_output=True)
        for packed in (False, True):
            target = self.root / ('manual.chd' if packed else 'manual.iso')
            digest = manual_patch(self.base / 'dvd.chd', self.delta, target,
                                  cache=self.root / 'cache', chd_output=packed)
            self.assertEqual(digest, hashlib.sha256(self.translated).hexdigest())
            with chd.prepared_source(target, self.root) as (disc, layout):
                self.assertEqual(disc.read_bytes(), self.translated)
        self.assert_clean()

    def test_chained_upgrade_compresses_once_and_recognizes_patched_chd(self):
        import copy
        final = self.translated[:10000] + b'Next version!' + self.translated[10013:]
        target = self.root / 'latest.iso'
        target.write_bytes(final)
        delta = self.root / 'upgrade.xdelta'
        manual_patch(self.target, target, delta, create=True, cache=self.root / 'cache')
        record = copy.deepcopy(self.record)
        record['tag'] = 'v1.1'
        record['manifest']['version'] = '1.1'
        p = record['manifest']['patches'][0]
        p.update(patch=delta.name, source_version='1.0', patch_bytes=delta.stat().st_size,
                 patch_sha256=hashlib.sha256(delta.read_bytes()).hexdigest())
        for name, data in (('source', self.translated), ('target', final)):
            p.update({name + '_bytes': len(data), name + '_sha256': hashlib.sha256(data).hexdigest(),
                      name + '_sha1': hashlib.sha1(data).hexdigest()})
        record['assets'] = {delta.name: 'https://github.com/retro-trans/test/releases/download/v1.1/' + delta.name}
        cat = Catalog({'schema_version': 1, 'releases': [self.record, record]})
        source = self.base / 'dvd.chd'
        original = recognize(source, cat)[0]
        self.assertEqual(cat.plan(original, 'Next version only').target.version, '1.0')
        plan = cat.plan(original)
        self.assertEqual(len(plan.edges), 2)
        owner = self
        class Local:
            def download(self, asset, *args):
                return delta if asset.name == delta.name else owner.delta
        output = self.root / 'latest.chd'
        with patch.object(chd, 'compress_verified', wraps=chd.compress_verified) as compress:
            apply_plan(source, output, plan, cat, Local(), cache=self.root / 'cache', chd_output=True)
            compress.assert_called_once()
        self.assertEqual(recognize(output, cat)[0].version, '1.1')
        with chd.prepared_source(output, self.root) as (binary, layout):
            self.assertEqual(binary.read_bytes(), final)
        self.assert_clean()

    def test_header_hint_cannot_authorize_wrong_source_or_downloads(self):
        wrong = self.root / 'wrong.chd'
        with chd.engine_context() as engine:
            chd.run(engine, ['createdvd', '-i', self.target, '-o', wrong, '-c', 'zlib'], 'Wrong source')
        data = bytearray(wrong.read_bytes())
        data[64:84] = hashlib.sha1(self.original).digest()  # Spoof the quick hint.
        wrong.write_bytes(data)
        plan = self.plan(wrong)
        with self.assertRaisesRegex(PatchError, 'changed|matches'):
            apply_plan(wrong, self.root / 'output.iso', plan, self.cat, self.client, cache=self.root / 'cache')
        self.assertEqual(self.downloads, [])
        self.assertFalse((self.root / 'output.iso').exists())
        self.assert_clean()

    def test_bad_header_parent_and_metadata_rejected(self):
        source = (self.base / 'dvd.chd').read_bytes()
        broken = self.root / 'broken.chd'
        cases = []
        data = bytearray(source); data[104] = 1; cases.append(data)
        data = bytearray(source); struct.pack_into('>I', data, 12, 4); cases.append(data)
        data = bytearray(source); struct.pack_into('>Q', data, 48, len(source) + 1); cases.append(data)
        data = bytearray(source); struct.pack_into('>I', data, 60, 0); cases.append(data)
        for data in cases + [source[:40]]:
            broken.write_bytes(data)
            with self.assertRaises(chd.ChdError):
                chd.inspect_chd(broken)

    def test_multitrack_and_audio_rejected(self):
        for mode, tracks in (('MODE1/2048', 2), ('AUDIO', 1)):
            data = self.root / (mode.split('/')[0] + '.bin')
            data.write_bytes(bytes(2352 * 32 if mode == 'AUDIO' else 2048 * 32))
            cue = self.root / 'source.cue'
            cue.write_text('FILE "' + data.name + '" BINARY\n  TRACK 01 ' + mode + '\n    INDEX 01 00:00:00\n' +
                           ('  TRACK 02 MODE1/2048\n    INDEX 01 00:00:16\n' if tracks == 2 else ''))
            output = self.root / (str(tracks) + '.chd')
            with chd.engine_context() as engine:
                chd.run(engine, ['createcd', '-i', cue, '-o', output], 'Unsupported fixture')
            with self.assertRaises(chd.ChdError):
                chd.inspect_chd(output)

    def test_disk_space_and_cancel_leave_no_output(self):
        output = self.root / 'patched.chd'
        with patch('retro_trans.chd.shutil.disk_usage', return_value=SimpleNamespace(free=0)):
            with self.assertRaisesRegex(PatchError, 'free space'):
                apply_plan(self.base / 'dvd.chd', output, self.plan(), self.cat, self.client, chd_output=True)
        for phase in ('Extracting', 'Compressing', 'Verifying compressed'):
            cancel = threading.Event()
            def progress(message, fraction):
                if message.startswith(phase):
                    cancel.set()
            with self.assertRaises(Cancelled):
                apply_plan(self.base / 'dvd.chd', output, self.plan(), self.cat, self.client,
                           cache=self.root / 'cache', chd_output=True, cancel=cancel, progress=progress)
            self.assertFalse(output.exists())
            self.assert_clean()

    def test_existing_output_and_corrupt_engine_preserved(self):
        output = self.root / 'keep.chd'
        output.write_bytes(b'keep')
        with self.assertRaises(PatchError):
            apply_plan(self.base / 'dvd.chd', output, self.plan(), self.cat, self.client)
        self.assertEqual(output.read_bytes(), b'keep')
        broken = self.root / 'broken-engine.zip'
        broken.write_bytes(b'not the engine')
        with patch.object(chd, 'RESOURCE', broken), self.assertRaisesRegex(PatchError, 'engine failed verification'):
            with chd.prepared_source(self.base / 'dvd.chd', self.root):
                self.fail('Bad engine used')
        self.assert_clean()

    def test_compression_verification_failure_removes_all_output(self):
        actual = chd.sha256_file
        def wrong_hash(path, cancel=None, progress=None, message=''):
            return '0' * 64 if message == 'Verifying compressed CHD round trip' else actual(path, cancel, progress, message)
        with patch.object(chd, 'sha256_file', side_effect=wrong_hash):
            with self.assertRaisesRegex(PatchError, 'does not reproduce'):
                apply_plan(self.iso, self.root / 'bad.chd', self.plan(), self.cat, self.client,
                           cache=self.root / 'cache', chd_output=True)
        self.assertFalse((self.root / 'bad.chd').exists())
        self.assert_clean()

    def test_manual_raw_chd_bytes_mode_preserved(self):
        source = self.base / 'dvd.chd'
        raw_copy = self.root / 'copy.chd'
        delta = self.root / 'raw.xdelta'
        manual_patch(source, source, delta, create=True, cache=self.root / 'cache')
        manual_patch(source, delta, raw_copy, unpack_chd=False, cache=self.root / 'cache')
        self.assertEqual(raw_copy.read_bytes(), source.read_bytes())

    def test_single_cd_bin_output_includes_cue_and_refuses_existing_cue(self):
        output = self.root / 'translated.bin'
        manual_patch(self.base / 'cd.chd', self.delta, output, cache=self.root / 'cache')
        self.assertEqual(output.read_bytes(), self.translated)
        self.assertIn('FILE "translated.bin" BINARY', output.with_suffix('.cue').read_text())
        output.unlink()
        before = output.with_suffix('.cue').read_bytes()
        with self.assertRaisesRegex(PatchError, 'already exists'):
            manual_patch(self.base / 'cd.chd', self.delta, output, cache=self.root / 'cache')
        self.assertFalse(output.exists())
        self.assertEqual(output.with_suffix('.cue').read_bytes(), before)

    def test_raw_cd_modes_preserve_sector_bytes_and_layout(self):
        for mode in ('MODE1/2352', 'MODE2/2352'):
            name = mode.split('/')[0]
            original = self.root / (name + '.bin')
            original.write_bytes(bytes(2352 * 32))
            target = self.root / (name + '-target.bin')
            target.write_bytes(bytes(3000) + b'Translated' + bytes(2352 * 32 - 3010))
            delta = self.root / (name + '.xdelta')
            manual_patch(original, target, delta, create=True, cache=self.root / 'cache')
            cue = original.with_suffix('.cue')
            cue.write_text('FILE "' + original.name + '" BINARY\n  TRACK 01 ' + mode + '\n    INDEX 01 00:00:00\n')
            source = original.with_suffix('.chd')
            with chd.engine_context() as engine:
                chd.run(engine, ['createcd', '-i', cue, '-o', source], 'Raw CD fixture')
            output = self.root / (name + '-patched.chd')
            manual_patch(source, delta, output, cache=self.root / 'cache', chd_output=True)
            self.assertEqual(chd.inspect_chd(output).cue_mode, mode)
            with chd.prepared_source(output, self.root) as (binary, layout):
                self.assertEqual(binary.read_bytes(), target.read_bytes())

    def test_corrupted_chd_fails_before_patch_download(self):
        source = self.root / 'corrupt.chd'
        data = bytearray((self.base / 'dvd.chd').read_bytes())
        # Break the compressed hunk map while retaining the identity hint.
        data[-1] ^= 0xff
        source.write_bytes(data)
        with self.assertRaises(PatchError):
            apply_plan(source, self.root / 'bad.iso', self.plan(), self.cat, self.client, cache=self.root / 'cache')
        self.assertFalse((self.root / 'bad.iso').exists())
        self.assertEqual(self.downloads, [])
        self.assert_clean()

    def test_publish_race_preserves_binary_and_cleans_companion(self):
        output = self.root / 'race.bin'
        stage = self.root / 'stage'
        stage.mkdir()
        pending = stage / 'disc.bin'
        pending.write_bytes(b'new')
        actual = chd.publish_output
        def collide(temporary, destination):
            if destination.suffix == '.cue':
                actual(temporary, destination)
                output.write_bytes(b'existing')
            else:
                actual(temporary, destination)
        with patch.object(chd, 'publish_output', side_effect=collide), self.assertRaises(FileExistsError):
            chd.publish_disc(pending, output, chd.Disc('cd', 3, 2352, 'MODE1/2352'))
        self.assertEqual(output.read_bytes(), b'existing')
        self.assertFalse(output.with_suffix('.cue').exists())


if __name__ == '__main__':
    unittest.main()
