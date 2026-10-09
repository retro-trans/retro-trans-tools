import copy
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

from retro_trans import vita_repatch as v
from retro_trans.core import Cancelled, PatchError, Asset


def ident(data):
    return dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def fixture():
    auth = bytes.fromhex('0800000000000021') + bytes(8) + bytes([1]) * 64 + bytes(64)
    eboot = bytearray(256)
    eboot[:4] = b'SCE\0'
    struct.pack_into('<Q', eboot, 0x38, 0x80)
    eboot[0x80:0x88] = auth[:8]
    originals = {'eboot.bin': b'original executable', 'DATA/STAGE/STG0001a.cpk': b'original stage'}
    targets = {'eboot.bin': bytes(eboot), 'DATA/STAGE/STG0001a.cpk': b'translated stage'}
    data = dict(schema=v.SCHEMA, title_id='PCSG00264', app_version='01.00', name='Test', build='test18',
                auth=dict(hex=auth.hex(), sha256=hashlib.sha256(auth).hexdigest()), files=[])
    for i, name in enumerate(originals):
        data['files'].append(dict(path=name, source=ident(originals[name]), target=ident(targets[name]),
                                 patch=dict(name='VITA-{}.xdelta'.format(i), **ident(targets[name]))))
    return data, originals, targets


@contextmanager
def fake_engine(*args, **kwargs):
    yield 'unused'


class VitaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source, self.package, self.output = self.root/'source', self.root/'patches', self.root/'output'
        self.source.mkdir(); self.package.mkdir()
        self.data, self.originals, self.targets = fixture()
        for row in self.data['files']:
            src = self.source/row['path']; src.parent.mkdir(parents=True, exist_ok=True)
            src.write_bytes(self.originals[row['path']])
            (self.package/row['patch']['name']).write_bytes(self.targets[row['path']])
        self.description = self.package/v.MANIFEST
        self.save()

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        self.description.write_text(json.dumps(self.data), encoding='utf-8')

    def apply(self, **kwargs):
        def decode(engine, source, delta, output, size, *args):
            output.write_bytes(delta.read_bytes())
        with patch.object(v, 'engine_context', fake_engine), patch.object(v, 'decode', side_effect=decode):
            return v.apply(self.source, self.output, self.description, **kwargs)

    def test_nested_overlay_auth_no_unrelated_copy(self):
        (self.source/'license.bin').write_bytes(b'private')
        self.assertEqual(self.apply(), self.output)
        tree = self.output/'rePatch/PCSG00264'
        for name, data in self.targets.items():
            self.assertEqual((tree/name).read_bytes(), data)
            self.assertEqual((self.source/name).read_bytes(), self.originals[name])
        self.assertEqual((tree/'self_auth.bin').read_bytes(), bytes.fromhex(self.data['auth']['hex']))
        self.assertFalse((tree/'license.bin').exists())
        self.assertEqual(len(list(tree.rglob('*.bin'))), 2)
        self.assertFalse(list(self.root.glob('.retro-vita-*')))

    def test_invalid_paths_and_payloads(self):
        for name in ('../eboot.bin', '/eboot.bin', 'DATA/../x.cpk', 'DATA\\x.cpk',
                     'DATA/NUL.cpk', 'DATA/x.cpk:stream', 'DATA/x./y.cpk', 'sce_sys/work.bin',
                     'DATA//x.cpk', 'DATA/x\0.cpk', 'DATA/CON/x.cpk'):
            data = copy.deepcopy(self.data); data['files'][1]['path'] = name
            with self.subTest(name=name), self.assertRaises(PatchError):
                v.validate(data)

    def test_invalid_auth_and_conflicts(self):
        for offset in (8, 80, 96, 143):
            data = copy.deepcopy(self.data)
            raw = bytearray.fromhex(data['auth']['hex']); raw[offset] = 1
            data['auth'] = dict(hex=raw.hex(), sha256=hashlib.sha256(raw).hexdigest())
            with self.assertRaises(PatchError): v.validate(data)
        data = copy.deepcopy(self.data)
        data['files'][1]['path'] = 'eboot.bin'
        with self.assertRaises(PatchError): v.validate(data)
        data = copy.deepcopy(self.data)
        data['files'][1]['patch']['name'] = data['files'][0]['patch']['name']
        with self.assertRaises(PatchError): v.validate(data)
        data['schema'] = 'future'
        with self.assertRaises(PatchError): v.validate(data)

    def test_bad_source_or_delta_no_output(self):
        for path in (self.source/'eboot.bin', self.package/'VITA-0.xdelta'):
            old = path.read_bytes(); path.write_bytes(b'bad')
            with self.assertRaises(PatchError): self.apply()
            self.assertFalse(self.output.exists())
            path.write_bytes(old)

    def test_existing_or_overlapping_output(self):
        self.output.mkdir(); (self.output/'keep').write_text('keep')
        with self.assertRaises(PatchError): self.apply()
        self.assertEqual((self.output/'keep').read_text(), 'keep')
        for out in (self.source/'new', self.source, self.package/'new', self.root/'missing/new'):
            self.output = out
            with self.assertRaises(PatchError): self.apply()

    def test_mismatching_executable_auth_never_published(self):
        raw = bytearray.fromhex(self.data['auth']['hex']); raw[0] ^= 1
        self.data['auth'] = dict(hex=raw.hex(), sha256=hashlib.sha256(raw).hexdigest()); self.save()
        with self.assertRaises(PatchError): self.apply()
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob('.retro-vita-*')))

    def test_decode_failure_and_source_mutation_never_published(self):
        def fail(*args): raise PatchError('engine failure')
        with patch.object(v, 'engine_context', fake_engine), patch.object(v, 'decode', side_effect=fail):
            with self.assertRaises(PatchError): v.apply(self.source, self.output, self.description)
        def mutate(engine, source, delta, dest, size, *args):
            dest.write_bytes(delta.read_bytes()); source.write_bytes(b'changed concurrently')
        with patch.object(v, 'engine_context', fake_engine), patch.object(v, 'decode', side_effect=mutate):
            with self.assertRaises(PatchError): v.apply(self.source, self.output, self.description)
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob('.retro-vita-*')))

    def test_cancel_before_and_during_decode(self):
        event = threading.Event(); event.set()
        with self.assertRaises(Cancelled): self.apply(cancel=event)
        event.clear()
        def stop(*args): event.set(); raise Cancelled('stopped')
        with patch.object(v, 'engine_context', fake_engine), patch.object(v, 'decode', side_effect=stop):
            with self.assertRaises(Cancelled):
                v.apply(self.source, self.output, self.description, cancel=event)
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob('.retro-vita-*')))

    def test_wrong_output_hash(self):
        self.data['files'][1]['target'] = ident(b'wrong expected data'); self.save()
        with self.assertRaises(PatchError): self.apply()
        self.assertFalse(self.output.exists())

    def test_metadata_limits(self):
        for raw in (b'not json', b'{}', b'x' * (v.MAX_METADATA + 1)):
            with self.assertRaises(PatchError): v.read_description(raw)

    def test_reparse_rejected(self):
        actual = Path.lstat
        def lstat(path):
            if path == self.source/'DATA':
                class Info:
                    st_mode = stat_mode = 0o040755
                    st_file_attributes = 0x400
                return Info()
            return actual(path)
        with patch.object(Path, 'lstat', lstat), self.assertRaises(PatchError): self.apply()

    def test_online_profile_verified_and_unpublished_help(self):
        raw = self.description.read_bytes()
        prefix = 'https://github.com/{}/releases/download/{}/'.format(v.REPO, v.TAG)
        assets = [dict(name=v.MANIFEST, size=len(raw), digest='sha256:'+hashlib.sha256(raw).hexdigest(),
                       browser_download_url=prefix+v.MANIFEST)]
        for row in self.data['files']:
            p = row['patch']
            assets.append(dict(name=p['name'], size=p['bytes'], digest='sha256:'+p['sha256'],
                               browser_download_url=prefix+p['name']))
        class Client:
            def json(inner, *args): return dict(tag_name=v.TAG, assets=assets)
            def download(inner, asset, *args): return self.description
        data, package, found = v.online_description(Client())
        self.assertEqual(data, self.data); self.assertIsNone(package)
        self.assertEqual(len(found), 3)
        assets.pop(0)
        with self.assertRaisesRegex(PatchError, 'not published yet'): v.online_description(Client())

    def test_online_rejects_redirected_or_bad_asset(self):
        class Client:
            def json(inner, *args):
                return dict(tag_name=v.TAG, assets=[dict(name=v.MANIFEST,
                    browser_download_url='https://evil.example/patch.json')])
        with self.assertRaises(PatchError): v.online_description(Client())


if __name__ == '__main__':
    unittest.main()
