import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from retro_trans import vita_translation as v, vita_pfs as p
from retro_trans.core import PatchError, Cancelled


def identity(raw):
    return dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())


def fixture(title='PCSG00597'):
    original = {'eboot.bin':b'original executable','sce_sys/param.sfo':b'original metadata'}
    patch_data = b'patch fixture'
    extra = b'font attribution'
    data = dict(schema=v.SCHEMA,name='Translation fixture',build='0.1.13',title_id=title,
        content_id='JP0700-'+title+'_00-CROSSANGEGAME000',target='Vita3K',minimum_app_version='0.5.8',
        engine='pfs-v5-pkg-key2',package=identity(b'original package'),
        source_files=[dict(path=name,**identity(raw)) for name,raw in original.items()],
        files=[dict(path='sce_sys/param.sfo',source=identity(original['sce_sys/param.sfo']),
                    target=identity(b'\0PSFtranslated'),patch=dict(name='translation.xdelta',**identity(patch_data)))],
        extras=[dict(path='sce_sys/font-license.txt',name='font-license.txt',**identity(extra))])
    return data, {'translation.xdelta':patch_data,'font-license.txt':extra}


class TranslationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data,self.assets = fixture()

    def archive(self, extra=None):
        path = self.root/'patches.zip'
        with zipfile.ZipFile(path,'w') as archive:
            archive.writestr(v.MANIFEST,json.dumps(self.data))
            for name,raw in self.assets.items(): archive.writestr(name,raw)
            if extra: archive.writestr(extra,b'not a translation')
        return path

    def test_profiles_for_two_games_without_registry(self):
        for title in ('PCSG00597','PCSE12345'):
            data,_ = fixture(title)
            self.assertEqual(v.validate(data)['title_id'],title)

    def test_wrong_game_content_and_engine_rejected(self):
        for key,value in [('content_id','JP0700-PCSG11111_00-CROSSANGEGAME000'),
                          ('title_id','../PCSG00597'),('engine','run-downloaded-script'),
                          ('target','Hardware'),('minimum_app_version','99.0.0')]:
            data=copy.deepcopy(self.data); data[key]=value
            with self.subTest(key=key),self.assertRaises(PatchError): v.validate(data)

    def test_invalid_source_names_and_reserved_files(self):
        for name in ('../eboot.bin','a//b','C:/bad','sce_sys/work.bin','license/test.rif',
                     'sce_pfs/files.db','DATA/CON/x.bin','a/./b','bad\0file','a/'+'x'*68):
            data=copy.deepcopy(self.data);data['source_files'][0]['path']=name
            with self.subTest(name=name),self.assertRaises(PatchError): v.validate(data)

    def test_case_collisions_and_file_directory_conflicts(self):
        for name in ('EBOOT.BIN','eboot.bin/child.dat'):
            data=copy.deepcopy(self.data);data['source_files'].append(dict(path=name,**identity(b'new')))
            with self.subTest(name=name),self.assertRaises(PatchError): v.validate(data)

    def test_extra_cannot_override_original_or_supply_license(self):
        for name in ('eboot.bin','sce_sys/param.sfo','sce_sys/work.bin','new/data.rif'):
            data=copy.deepcopy(self.data);data['extras'][0]['path']=name
            with self.subTest(name=name),self.assertRaises(PatchError): v.validate(data)

    def test_patch_source_must_match_inventory(self):
        self.data['files'][0]['source']=identity(b'wrong revision')
        with self.assertRaises(PatchError):v.validate(self.data)

    def test_archive_verified_and_private_folder_removed(self):
        path=self.archive()
        with v.archive_description(path) as (data,folder):
            self.assertEqual(data,self.data)
            self.assertEqual((folder/'translation.xdelta').read_bytes(),self.assets['translation.xdelta'])
        self.assertFalse(folder.exists())

    def test_unexpected_zip_entries_rejected(self):
        for name in ('../escape','work.bin','run.py'):
            with self.subTest(name=name),self.assertRaises(PatchError):
                with v.archive_description(self.archive(name)):pass
        self.assertFalse((self.root.parent/'escape').exists())

    def test_damaged_asset_rejected_and_cancelled(self):
        self.assets['translation.xdelta']=b'tampered patch'
        with self.assertRaises(PatchError):
            with v.archive_description(self.archive()):pass
        self.assets['translation.xdelta']=b'patch fixture'
        cancel=threading.Event();cancel.set()
        with self.assertRaises(Cancelled):
            with v.archive_description(self.archive(),cancel=cancel):pass

    def test_zip_symlink_and_case_duplicate_rejected(self):
        path=self.archive()
        with zipfile.ZipFile(path,'a') as archive:
            item=zipfile.ZipInfo('link');item.create_system=3;item.external_attr=0o120777<<16
            archive.writestr(item,'outside')
        with self.assertRaises(PatchError):
            with v.archive_description(path):pass
        path=self.archive('TRANSLATION.XDELTA')
        with self.assertRaises(PatchError):
            with v.archive_description(path):pass

    def test_existing_output_and_early_cancel_unchanged(self):
        source=self.root/'original.pkg';source.write_bytes(b'preserve original')
        license=self.root/'work.bin';license.write_bytes(b'preserve license')
        output=self.root/'translated.pkg';output.write_bytes(b'preserve output')
        with self.assertRaises(PatchError):v.apply(source,license,output,self.archive())
        output.unlink();cancel=threading.Event();cancel.set()
        with self.assertRaises(Cancelled):v.apply(source,license,output,self.archive(),cancel=cancel)
        self.assertFalse(output.exists())
        self.assertEqual(source.read_bytes(),b'preserve original')
        self.assertEqual(license.read_bytes(),b'preserve license')

    def test_no_profile_does_not_fetch_license_or_release(self):
        with patch.object(v.GitHubClient,'json') as network,self.assertRaises(PatchError):
            with v.description_context():pass
        network.assert_not_called()


class NativeFormatTests(unittest.TestCase):
    def test_known_aes_vector_and_partial_sectors(self):
        key=bytes.fromhex('2b7e151628aed2a6abf7158809cf4f3c');iv=bytes.fromhex('000102030405060708090a0b0c0d0e0f')
        self.assertEqual(p.cbc_tail(bytes.fromhex('6bc1bee22e409f96e93d7e117393172a'),key,iv).hex(),
                         '7649abac8119b246cee98e9b12e9197d')
        for size in (1,15,16,17,31,32,32767,32768):
            raw=bytes(i%251 for i in range(size));encrypted=p.sector_cipher(raw,key,iv,37)
            self.assertEqual(p.sector_cipher(encrypted,key,iv,37,True),raw)

    def test_inner_path_validation_and_cycles(self):
        values=p.constants();key=bytes(range(16));template=bytearray(1024)
        struct.pack_into('<8sIHHIIIIQQQ',template,0,b'SCENGPFS',5,1,0,1024,10,0,123,0xffffffffffffffff,0,0)
        records=[dict(path='eboot.bin',id=1,parent=0,directory=False,bytes=20),
                 dict(path='sce_sys',id=2,parent=0,directory=True,bytes=0),
                 dict(path='sce_sys/param.sfo',id=3,parent=2,directory=False,bytes=20)]
        expected={'eboot.bin','sce_sys/param.sfo'}
        parsed=dict(entries=[dict(name=name,directory=False) for name in expected|{'sce_pfs/files.db','sce_pfs/unicv.db'}])
        database=p.files_database(records,template,key,values)
        with patch.object(p,'small_member',return_value=database):
            p.validate_original_paths(None,parsed,key,expected,values)
        cyclic=copy.deepcopy(records);cyclic[1]['parent']=2
        with patch.object(p,'small_member',return_value=p.files_database(cyclic,template,key,values)),self.assertRaises(PatchError):
            p.validate_original_paths(None,parsed,key,expected,values)
        with patch.object(p,'small_member',return_value=database),self.assertRaises(PatchError):
            p.validate_original_paths(None,parsed,bytes(16),expected,values)
