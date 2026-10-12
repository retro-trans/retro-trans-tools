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
import zipfile
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
        # CI may provide an 8.3 temp path (RUNNER~1); compare the same canonical
        # paths used by the backend when injecting reparse-point test metadata.
        self.root = Path(self.temp.name).resolve()
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

    def asset_only(self):
        self.data['files'] = self.data['files'][1:]
        self.data['auth'] = None
        self.data['title_id'] = 'PCSG00597'
        raw = b'Translation credits and font attribution'
        self.data['extras'] = [dict(path='sce_sys/font-license.txt',
            asset=dict(name='VITA-font-license.txt',**ident(raw)))]
        (self.package/'VITA-font-license.txt').write_bytes(raw)
        self.save()
        return raw

    def test_asset_only_overlay_keeps_original_executable_and_copies_credits(self):
        raw = self.asset_only()
        self.apply()
        tree = self.output/'rePatch/PCSG00597'
        self.assertEqual((tree/'sce_sys/font-license.txt').read_bytes(),raw)
        self.assertFalse((tree/'eboot.bin').exists())
        self.assertFalse((tree/'self_auth.bin').exists())
        self.assertEqual((self.source/'eboot.bin').read_bytes(),self.originals['eboot.bin'])
        record = json.loads((self.output/'VERIFIED.json').read_text())
        self.assertIsNone(record['sanitized_auth_sha256'])
        self.assertEqual(record['files']['sce_sys/font-license.txt'],ident(raw))

    def test_asset_only_zip_contains_and_verifies_added_files(self):
        raw = self.asset_only()
        archive = self.make_zip()
        self.description = archive
        self.apply()
        self.assertEqual((self.output/'rePatch/PCSG00597/sce_sys/font-license.txt').read_bytes(),raw)

    def test_added_file_hash_failure_never_publishes(self):
        self.asset_only()
        (self.package/'VITA-font-license.txt').write_bytes(b'corrupt')
        with self.assertRaises(PatchError): self.apply()
        self.assertFalse(self.output.exists())

    def test_added_file_paths_collisions_and_size_are_rejected(self):
        self.asset_only()
        for name in ('work.bin','sce_sys/a.rif','eboot.bin','DATA/x.cpk','../credits.txt',
                     self.data['files'][0]['path']):
            data = copy.deepcopy(self.data);data['extras'][0]['path']=name
            with self.subTest(path=name),self.assertRaises(PatchError): v.validate(data)
        data = copy.deepcopy(self.data);data['extras'][0]['asset']['name']=v.MANIFEST
        with self.assertRaises(PatchError): v.validate(data)
        data = copy.deepcopy(self.data);data['extras'][0]['asset']['bytes']=8*1024**2+1
        with self.assertRaises(PatchError): v.validate(data)
        data = copy.deepcopy(self.data);data['extras'] *= 2
        with self.assertRaises(PatchError): v.validate(data)

    def test_auth_requires_an_executable_and_executable_requires_auth(self):
        data = copy.deepcopy(self.data);data['auth']=None
        with self.assertRaises(PatchError): v.validate(data)
        data = copy.deepcopy(self.data);data['files']=data['files'][1:]
        with self.assertRaises(PatchError): v.validate(data)

    def test_pkg_without_local_profile_uses_generic_repatch_discovery(self):
        @contextmanager
        def discovered(source,client,cache,cancel,progress,profile):
            self.assertIs(profile,v)
            self.assertEqual(source,self.root/'original.pkg')
            yield self.data,self.package,None
        @contextmanager
        def decrypted(*args,**kwargs):
            yield self.source
        def decode(engine,source,delta,dest,size,*args): dest.write_bytes(delta.read_bytes())
        with patch('retro_trans.vita_downloads.automatic_description',discovered), \
             patch('retro_trans.vita_pkg.decrypted_source',decrypted), \
             patch.object(v,'engine_context',fake_engine),patch.object(v,'decode',side_effect=decode):
            v.apply(self.root/'original.pkg',self.output,work_bin=self.root/'work.bin')
        self.assertTrue((self.output/'rePatch/PCSG00264/eboot.bin').exists())

    def test_legacy_z3_fallback_is_limited_to_missing_profile_for_z3(self):
        @contextmanager
        def absent(*args,**kwargs):
            raise PatchError('No automatic Vita translation was found for PCSG00264.')
            yield
        @contextmanager
        def legacy(*args,**kwargs): yield self.data,self.package,None
        with patch('retro_trans.vita_downloads.automatic_description',absent), \
             patch('retro_trans.vita_downloads.package_content',return_value='JP0700-PCSG00264_00-'+('X'*16)), \
             patch.object(v,'description_context',legacy):
            with v.pkg_description('original.pkg',client=object()) as result:
                self.assertEqual(result[0],self.data)
        with patch('retro_trans.vita_downloads.automatic_description',absent), \
             patch('retro_trans.vita_downloads.package_content',return_value='JP0700-PCSG00597_00-'+('X'*16)), \
             self.assertRaises(PatchError),v.pkg_description('original.pkg',client=object()): pass

    def test_future_required_app_version_rejected(self):
        self.data['minimum_app_version']='0.99.99'
        with self.assertRaisesRegex(PatchError,'newer app'):v.validate(self.data)

    def test_hardware_profile_for_another_game(self):
        self.data['title_id']='PCSE12345';self.save()
        self.apply()
        self.assertTrue((self.output/'rePatch/PCSE12345/eboot.bin').is_file())
        guide=(self.output/'README-INSTALL.txt').read_text()
        self.assertIn('ux0:rePatch/PCSE12345',guide)
        self.assertNotIn('PCSG00264',guide)

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

    def make_zip(self, extra=None, missing=None, corrupt=None):
        path = self.package / v.ARCHIVE
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
            for file in (self.description,) + tuple(self.package/r['patch']['name'] for r in self.data['files']) + tuple(
                    self.package/r['asset']['name'] for r in self.data.get('extras',[])):
                if file.name != missing:
                    archive.writestr(file.name, b'corrupt' if file.name == corrupt else file.read_bytes())
            if extra:
                archive.writestr(*extra)
        return path

    def test_local_zip_applies_and_cleans_up(self):
        archive = self.make_zip()
        with v.archive_description(archive) as (data, directory, assets):
            self.assertEqual(data, self.data)
            self.assertIsNone(assets)
            self.assertEqual(len(list(directory.iterdir())), 3)
        self.assertFalse(directory.exists())
        self.description = archive
        self.test_nested_overlay_auth_no_unrelated_copy()

    def test_zip_rejects_unsafe_missing_extra_duplicate_and_corrupt_entries(self):
        for extra in ('../escape', '/absolute', 'folder/file', 'work.bin',
                      'vita-0.xdelta', 'VITA-0.xdelta', 'CON.xdelta'):
            with self.subTest(extra=extra):
                archive = self.make_zip(extra=(extra, b'bad'))
                with self.assertRaises(PatchError), v.archive_description(archive):
                    pass
        for kwargs in (dict(missing='VITA-0.xdelta'), dict(missing=v.MANIFEST),
                       dict(corrupt='VITA-0.xdelta')):
            with self.subTest(kwargs=kwargs), self.assertRaises(PatchError):
                with v.archive_description(self.make_zip(**kwargs)):
                    pass

    def test_zip_rejects_links_bad_profile_oversize_and_cancel(self):
        link = zipfile.ZipInfo('link')
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        with self.assertRaises(PatchError), v.archive_description(self.make_zip(extra=(link, b'outside'))):
            pass
        archive = self.make_zip()
        different = copy.deepcopy(self.data); different['build'] = 'different'
        with self.assertRaises(PatchError), v.archive_description(archive, different):
            pass
        with patch.object(v, 'MAX_ARCHIVE', 10), self.assertRaises(PatchError), v.archive_description(archive):
            pass
        cancelled = threading.Event(); cancelled.set()
        with self.assertRaises(Cancelled), v.archive_description(archive, cancel=cancelled):
            pass
        archive.write_bytes(b'not a zip')
        with self.assertRaises(PatchError), v.archive_description(archive):
            pass

    def test_online_prefers_zip_and_uses_requested_cache(self):
        archive = self.make_zip()
        prefix = 'https://github.com/{}/releases/download/{}/'.format(v.REPO, v.TAG)
        files = [self.description, archive] + list(self.package.glob('*.xdelta'))
        assets = [dict(name=p.name, size=p.stat().st_size,
                       digest='sha256:'+v.sha256_file(p), browser_download_url=prefix+p.name) for p in files]
        downloaded = []
        cache = self.root/'cache'
        class Client:
            def json(inner, *args): return dict(tag_name=v.TAG, assets=assets)
            def download(inner, asset, selected_cache, *args):
                self.assertEqual(selected_cache, cache)
                downloaded.append(asset.name)
                return self.package/asset.name
        with v.description_context(client=Client(), cache=cache) as (data, folder, individual):
            self.assertEqual(data, self.data)
            self.assertTrue((folder/'VITA-0.xdelta').is_file())
            self.assertIsNone(individual)
        self.assertEqual(downloaded, [v.MANIFEST, v.ARCHIVE])
        self.assertFalse(folder.exists())
        # ZIP mode must not depend on individual assets, even malformed ones.
        assets[:] = [a for a in assets if not a['name'].endswith('.xdelta')]
        assets.append(dict(name='VITA-ignored.xdelta'))
        downloaded.clear()
        with v.description_context(client=Client(), cache=cache) as (data, folder, individual):
            self.assertEqual(data, self.data)
            self.assertTrue((folder/'VITA-0.xdelta').is_file())
        self.assertEqual(downloaded, [v.MANIFEST, v.ARCHIVE])
        archive.write_bytes(b'corrupt')
        with self.assertRaises(PatchError), v.description_context(client=Client(), cache=cache):
            pass

    def test_zip_only_online_apply_without_individual_assets(self):
        archive = self.make_zip()
        prefix = 'https://github.com/{}/releases/download/{}/'.format(v.REPO, v.TAG)
        assets = [dict(name=p.name, size=p.stat().st_size, digest='sha256:'+v.sha256_file(p),
                       browser_download_url=prefix+p.name) for p in (self.description, archive)]
        fetched = []
        class Client:
            def json(inner, *args): return dict(tag_name=v.TAG, assets=assets)
            def download(inner, asset, *args):
                fetched.append(asset.name)
                return self.package/asset.name
        def decode(engine, source, delta, output, size, *args):
            output.write_bytes(delta.read_bytes())
        with patch.object(v, 'engine_context', fake_engine), patch.object(v, 'decode', side_effect=decode):
            v.apply(self.source, self.output, client=Client())
        self.assertEqual(fetched, [v.MANIFEST, v.ARCHIVE])
        for name, raw in self.targets.items():
            self.assertEqual((self.output/'rePatch/PCSG00264'/name).read_bytes(), raw)


if __name__ == '__main__':
    unittest.main()
