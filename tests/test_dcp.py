import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from retro_trans import dcp
from retro_trans.core import PatchError, Cancelled


class DcpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_frozen_mac_engine_links_stay_inside_app_and_keep_hash_checks(self):
        bundle = self.root/'Retro-Trans.app'
        module = bundle/'Contents/Resources/retro_trans/dcp.py'
        directory = module.parent/'resources/native/dcp/osx-x64'
        directory.mkdir(parents=True)
        target = bundle/'Contents/Frameworks/RetroTrans.Dcp'
        target.parent.mkdir(parents=True)
        target.write_bytes(b'synthetic engine')
        executable = directory/'RetroTrans.Dcp'
        try:
            executable.symlink_to(target)
        except OSError:
            self.skipTest('Symlink creation requires OS support')
        manifest = {'upstream_commit': dcp.UPSTREAM, 'files': {'RetroTrans.Dcp': {
            'bytes': target.stat().st_size, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}}}
        (directory/'engine.json').write_text(json.dumps(manifest), encoding='utf-8')
        with patch.object(dcp, '__file__', str(module)), patch.object(dcp.sys, 'platform', 'darwin'), \
                patch.object(dcp.sys, 'frozen', True, create=True), \
                patch.object(dcp.platform, 'machine', return_value='x86_64'), \
                patch('retro_trans.macos.app_bundle', return_value=bundle):
            self.assertEqual(dcp.engine(), executable)
            target.write_bytes(b'corrupt engine!!')
            with self.assertRaises(PatchError):
                dcp.engine()
            outside = self.root/'outside-engine'
            outside.write_bytes(b'synthetic engine')
            executable.unlink()
            executable.symlink_to(outside)
            with self.assertRaises(PatchError):
                dcp.engine()

    def package(self, name='patch.dcp', members=None, metadata=None):
        path = self.root / name
        with zipfile.ZipFile(path, 'w') as z:
            for n, v in (members or {'1ST_READ.BIN.xdelta': b'VCDIFF'}).items(): z.writestr(n, v)
            if metadata is not None: z.comment = json.dumps(metadata).encode()
        return path

    def disc(self, offsets=False):
        rows = ['3']
        for i in range(1, 4):
            name = f'Track {i}.bin'
            (self.root / name).write_bytes(bytes([i]) * 2352 + b'X' * 2352)
            rows.append(f'{i} {0 if i == 1 else 450 if i == 2 else 45000} {0 if i == 2 else 4} 2352 "{name}" {2352 if offsets else 0}')
        source = self.root / 'disc.gdi'
        source.write_text('\n'.join(rows), encoding='utf-8')
        return source

    def test_standard_and_verified_comments(self):
        p = self.package()
        self.assertEqual(dcp.inspect_patch(p)['metadata'], {})
        meta = {'retro_trans_dcp': 1, 'source_tree_sha256': 'a'*64, 'target_tree_sha256': 'b'*64}
        p = self.package('verified.dcp', metadata=meta)
        self.assertEqual(dcp.inspect_patch(p)['metadata'], meta)

    def test_rejects_traversal_duplicate_reserved_links_and_bad_hashes(self):
        for index, members in enumerate(({'../out': b'x'}, {'a/../../out': b'x'}, {'a/./out': b'x'},
                {'C:/out': b'x'}, {'/out': b'x'}, {'A': b'x', 'a': b'y'}, {'CON.txt': b'x'})):
            with self.subTest(members=members), self.assertRaises(PatchError):
                dcp.inspect_patch(self.package(str(index)+'.dcp', members))
        p = self.root / 'link.dcp'
        with zipfile.ZipFile(p, 'w') as z:
            row = zipfile.ZipInfo('link'); row.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(row, '../outside')
        with self.assertRaises(PatchError): dcp.inspect_patch(p)
        with self.assertRaises(PatchError):
            dcp.inspect_patch(self.package('bad.dcp', metadata={'retro_trans_dcp': 1, 'source_tree_sha256': 'no'}))

    def test_game_tree_identity_ignores_only_bootsector_and_orders_names(self):
        a = {'B': {'bytes': 2, 'sha256': 'b'*64}, 'A': {'bytes': 1, 'sha256': 'a'*64}}
        b = dict(reversed(list(a.items())))
        b['bootsector/IP.BIN'] = {'bytes': 32768, 'sha256': 'f'*64}
        self.assertEqual(dcp.tree_hash(a), dcp.tree_hash(b))
        b['A']['bytes'] = 3
        # Separate dictionaries must differ when payload identity changes.
        self.assertNotEqual(dcp.tree_hash({'A': {'bytes': 1}}), dcp.tree_hash(b))

    def test_gdi_offsets_trim_exactly_and_preserve_sources(self):
        source = self.disc(offsets=True)
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        gdi = dcp.prepare_gdi(source, self.root / 'owned')
        for i in range(1, 4):
            self.assertEqual((gdi.parent / f'track{i:02d}.bin').read_bytes(), b'X' * 2352)
        self.assertTrue(all(line.endswith(' 0') for line in gdi.read_text().splitlines()[1:]))
        for n, v in before.items(): self.assertEqual((self.root / n).read_bytes(), v)

    def test_zero_offsets_no_copy_missing_and_cancelled_inputs(self):
        source = self.disc()
        self.assertTrue(dcp.prepare_gdi(source, self.root/'unused').samefile(source))
        self.assertFalse((self.root/'unused').exists())
        (self.root/'Track 3.bin').unlink()
        with self.assertRaises(PatchError): dcp.prepare_gdi(source, self.root/'bad')
        self.disc(offsets=True)
        cancel = threading.Event(); cancel.set()
        with self.assertRaises(Cancelled): dcp.prepare_gdi(source, self.root/'cancel', cancel)

    def test_refuses_existing_output_and_unapproved_chd(self):
        source = self.disc(); delta = self.package()
        output = self.root/'existing'; output.mkdir(); (output/'keep').write_bytes(b'unchanged')
        with self.assertRaises(PatchError): dcp.apply(source, delta, output)
        self.assertEqual((output/'keep').read_bytes(), b'unchanged')
        chd = self.root/'game.chd'; chd.write_bytes(b'MComprHD')
        with patch('retro_trans.dcp.engine') as engine, self.assertRaises(PatchError):
            dcp.apply(chd, delta, self.root/'out')
        engine.assert_not_called()

    def test_wrong_version_rejected_before_native_patch_and_no_output(self):
        source = self.disc()
        delta = self.package(metadata={'retro_trans_dcp': 1, 'source_version': '0.7.11',
            'source_tree_sha256': 'a'*64, 'target_tree_sha256': 'b'*64})
        with patch('retro_trans.dcp.inspect_disc', return_value={'files': {}}), \
                patch('retro_trans.dcp.run') as native, self.assertRaisesRegex(PatchError, '0.7.11'):
            dcp.apply(source, delta, self.root/'out')
        native.assert_not_called()
        self.assertFalse((self.root/'out').exists())
        self.assertFalse(list(self.root.glob('.retro-trans-dcp-*')))

    def test_bad_rebuilt_payload_is_never_published(self):
        source = self.disc()
        delta = self.package(metadata={'retro_trans_dcp': 1, 'source_tree_sha256': dcp.tree_hash({}),
            'target_tree_sha256': 'b'*64})
        def native(command, request, *args):
            folder = Path(request['output'])/'game'; folder.mkdir()
            (folder/'disc.gdi').write_text('3', encoding='utf-8')
            return {'success': True, 'output': str(folder)}
        with patch('retro_trans.dcp.inspect_disc', return_value={'files': {}}), \
                patch('retro_trans.dcp.run', side_effect=native), self.assertRaisesRegex(PatchError, 'do not match'):
            dcp.apply(source, delta, self.root/'out')
        self.assertFalse((self.root/'out').exists())
        self.assertFalse(list(self.root.glob('.retro-trans-dcp-*')))

    def test_changed_audio_is_not_published_even_for_generic_dcp(self):
        source = self.disc(); delta = self.package()
        def native(command, request, *args):
            folder = Path(request['output'])/'game'; folder.mkdir()
            (folder/'disc.gdi').write_text('3', encoding='utf-8')
            return {'success': True, 'output': str(folder)}
        before = {'files': {}, 'audio_tracks': {'2': {'bytes': 16, 'sha256': 'a'*64}}}
        after = {'files': {}, 'audio_tracks': {'2': {'bytes': 16, 'sha256': 'b'*64}}}
        with patch('retro_trans.dcp.inspect_disc', side_effect=[before, after]), \
                patch('retro_trans.dcp.run', side_effect=native), self.assertRaisesRegex(PatchError, 'audio'):
            dcp.apply(source, delta, self.root/'out')
        self.assertFalse((self.root/'out').exists())
        self.assertFalse(list(self.root.glob('.retro-trans-dcp-*')))

    def test_audio_identity_accepts_only_silent_padding_with_sample_alignment(self):
        a, b = self.root/'a.raw', self.root/'b.raw'
        a.write_bytes(bytes(8) + b'\x01\x02\x03\x04' + bytes(16))
        b.write_bytes(bytes(12) + b'\x01\x02\x03\x04' + bytes(20))
        self.assertEqual(dcp.audio_identity(a), dcp.audio_identity(b))
        b.write_bytes(bytes(12) + b'\x01\x02\x03\x05' + bytes(20))
        self.assertNotEqual(dcp.audio_identity(a), dcp.audio_identity(b))
        b.write_bytes(bytes(13) + b'\x01\x02\x03\x04' + bytes(20))
        self.assertNotEqual(dcp.audio_identity(a), dcp.audio_identity(b))


if __name__ == '__main__': unittest.main()
