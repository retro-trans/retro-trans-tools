"""Real converter/xdelta checks using generated GameCube/Wii-like disc bytes."""
import copy
import hashlib
import os
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

from retro_trans import rvz, chd
from retro_trans.catalog import Catalog, recognize, scan_root, apply_plan
from retro_trans.core import manual_patch, PatchError, Cancelled, sha256_file

@unittest.skipUnless(os.name == 'nt', 'Bundled Windows RVZ converter')
class RvzTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.storage = tempfile.TemporaryDirectory()
        cls.base = Path(cls.storage.name)
        data = bytearray(bytes(range(256))*4096)
        data[:6] = b'GTEST0'; data[0x1c:0x20] = bytes.fromhex('c2339f3d')
        cls.original = bytes(data)
        data[8192:8212] = b'English translation!'
        cls.translated = bytes(data)
        cls.iso = cls.base/'original.iso'; cls.iso.write_bytes(cls.original)
        cls.target = cls.base/'target.iso'; cls.target.write_bytes(cls.translated)
        cls.rvz = cls.base/'original.rvz'
        rvz.compress_verified(cls.iso, cls.rvz)
        cls.delta = cls.base/'translation.xdelta'
        manual_patch(cls.iso, cls.target, cls.delta, create=True, cache=cls.base/'cache')
        p = dict(patch=cls.delta.name, edition='japan', language='en', source_version='original',
                 source_format='iso', target_format='iso', patch_bytes=cls.delta.stat().st_size,
                 patch_sha256=sha256_file(cls.delta))
        for side, data in [('source', cls.original), ('target', cls.translated)]:
            p.update({side+'_bytes': len(data), side+'_sha256': hashlib.sha256(data).hexdigest()})
        cls.record = dict(repo='retro-trans/test-rvz',tag='v1.0',manifest=dict(schema_version=1,
            game_id='rvz-test',game_name='RVZ test',platform='GameCube',version='1.0',source_commit='a'*40,patches=[p]),
            assets={cls.delta.name:'https://github.com/retro-trans/test-rvz/releases/download/v1.0/'+cls.delta.name})

    @classmethod
    def tearDownClass(cls):
        cls.storage.cleanup()

    def setUp(self):
        self.storage_each = tempfile.TemporaryDirectory()
        self.root = Path(self.storage_each.name)
        self.catalog = Catalog(dict(schema_version=1,releases=[self.record]))
        self.downloads = []
        owner = self
        class Local:
            def download(self, asset, *args):
                owner.downloads.append(asset.name)
                return owner.delta
        self.client = Local()

    def tearDown(self):
        self.storage_each.cleanup()

    def plan(self):
        return self.catalog.plan(recognize(self.iso,self.catalog)[0])

    def test_real_header_and_magic_detection(self):
        self.assertEqual(rvz.inspect_rvz(self.rvz).size,len(self.original))
        renamed=self.root/'renamed.data';renamed.write_bytes(self.rvz.read_bytes())
        self.assertTrue(rvz.is_rvz(renamed))
        self.assertEqual(recognize(renamed,self.catalog)[0].version,'original')
        self.assertEqual(list(self.root.glob('.retro-*')),[])

    def test_scan_deferred_with_grouped_catalog_never_extracts(self):
        from test_solutions import grouped_record
        source=self.root/'original.rvz';source.write_bytes(self.rvz.read_bytes())
        for cat in [self.catalog,Catalog(dict(schema_version=1,releases=[self.record,grouped_record()]))]:
            with patch.object(rvz,'extract',side_effect=AssertionError('scan unpacked without asking')):
                self.assertIsInstance(recognize(source,cat,defer_chd=True)[0],rvz.RvzSource)
                found=scan_root(self.root,cat,defer_chd=True)
                self.assertEqual(len(found),1)
                self.assertIsInstance(found[0][1],rvz.RvzSource)

    def test_persistent_iso_reused_and_existing_folder_refused(self):
        source=self.root/'original.rvz';source.write_bytes(self.rvz.read_bytes())
        before=source.read_bytes();destination=chd.extraction_folder(source)
        with patch.object(rvz,'extract',wraps=rvz.extract) as extract:
            binary=rvz.unpack_to_folder(source,destination)
            self.assertEqual(binary.read_bytes(),self.original)
            self.assertEqual([p.name for p in destination.iterdir()],['original.iso'])
            node=recognize(binary,self.catalog)[0]
            output=destination/'patched.iso'
            apply_plan(binary,output,self.catalog.plan(node),self.catalog,self.client,cache=self.root/'cache')
            self.assertEqual(output.read_bytes(),self.translated)
            extract.assert_called_once()
        self.assertEqual(source.read_bytes(),before)
        with self.assertRaises(PatchError):rvz.unpack_to_folder(source,destination)

    def test_automatic_rvz_to_iso_and_verified_rvz_output(self):
        before=sha256_file(self.rvz)
        out=self.root/'patched.iso'
        apply_plan(self.rvz,out,self.plan(),self.catalog,self.client,cache=self.root/'cache')
        self.assertEqual(out.read_bytes(),self.translated)
        packed=self.root/'patched.rvz'
        apply_plan(self.rvz,packed,self.plan(),self.catalog,self.client,cache=self.root/'cache',rvz_output=True)
        self.assertEqual(recognize(packed,self.catalog)[0].version,'1.0')
        with tempfile.TemporaryDirectory(dir=str(self.root)) as folder:
            self.assertEqual(rvz.extract(packed,folder).read_bytes(),self.translated)
        self.assertEqual(sha256_file(self.rvz),before)
        self.assertEqual(self.downloads,[self.delta.name,self.delta.name])

    def test_manual_rvz_input_output_and_raw_override(self):
        out=self.root/'manual.rvz'
        digest=manual_patch(self.rvz,self.delta,out,cache=self.root/'cache',rvz_output=True)
        self.assertEqual(digest,hashlib.sha256(self.translated).hexdigest())
        with tempfile.TemporaryDirectory(dir=str(self.root)) as folder:
            self.assertEqual(rvz.extract(out,folder).read_bytes(),self.translated)
        delta=self.root/'raw.xdelta'
        manual_patch(self.rvz,out,delta,create=True,cache=self.root/'cache')
        raw=self.root/'raw.rvz'
        manual_patch(self.rvz,delta,raw,unpack_chd=False,cache=self.root/'cache')
        self.assertEqual(raw.read_bytes(),out.read_bytes())

    def test_wrong_input_rejected_before_download(self):
        bad=self.root/'wrong.iso';data=bytearray(self.original);data[9000]^=1;bad.write_bytes(data)
        packed=self.root/'wrong.rvz';rvz.compress_verified(bad,packed)
        self.assertEqual(recognize(packed,self.catalog),[])
        with self.assertRaises(PatchError):
            apply_plan(packed,self.root/'out.iso',self.plan(),self.catalog,self.client,cache=self.root/'cache')
        self.assertEqual(self.downloads,[])
        self.assertFalse((self.root/'out.iso').exists())
        self.assertEqual(list(self.root.glob('.retro-*')),[])

    def test_corrupt_headers_and_container_lengths(self):
        raw=self.rvz.read_bytes()
        for name,data in [('short',b'RVZ\x01'),('checksum',raw[:30]+bytes([raw[30]^1])+raw[31:]),('truncated',raw[:-1])]:
            p=self.root/(name+'.rvz');p.write_bytes(data)
            with self.assertRaises(PatchError):rvz.inspect_rvz(p)
        self.assertEqual(scan_root(self.root,self.catalog,defer_chd=True),[])

    def test_cancel_failure_cleanup_and_source_preserved(self):
        source=self.root/'original.rvz';source.write_bytes(self.rvz.read_bytes());before=sha256_file(source)
        destination=self.root/'cancelled'
        cancel=threading.Event();cancel.set()
        with self.assertRaises(Cancelled):rvz.unpack_to_folder(source,destination,cancel)
        self.assertFalse(destination.exists())
        def fail(engine,args,user,*rest):
            output=Path(args[args.index('-o')+1]);output.write_bytes(b'partial')
            raise PatchError('injected converter failure')
        with patch.object(rvz,'run',side_effect=fail),self.assertRaises(PatchError):
            rvz.unpack_to_folder(source,destination)
        self.assertFalse(destination.exists())
        self.assertEqual(list(self.root.glob('.retro-*')),[])
        self.assertEqual(sha256_file(source),before)

    def test_low_space_existing_output_and_incompatible_output(self):
        with patch.object(rvz.shutil,'disk_usage',return_value=type('Space',(),{'free':0})()),self.assertRaises(PatchError):
            rvz.unpack_to_folder(self.rvz,self.base/'low-space')
        existing=self.root/'existing.rvz';existing.write_bytes(b'keep')
        with self.assertRaises(PatchError):apply_plan(self.iso,existing,self.plan(),self.catalog,self.client,rvz_output=True)
        self.assertEqual(existing.read_bytes(),b'keep')
        other=copy.deepcopy(self.record);other['manifest']['platform']='PS2'
        cat=Catalog(dict(schema_version=1,releases=[other]));node=recognize(self.iso,cat)[0]
        with self.assertRaises(PatchError):apply_plan(self.iso,self.root/'bad.rvz',cat.plan(node),cat,self.client,rvz_output=True)
        with self.assertRaises(PatchError):manual_patch(self.iso,self.delta,self.root/'bad.rvz',rvz_output=True,chd_output=True)

    def test_unrelated_binary_and_engine_integrity(self):
        binary=self.root/'binary.iso';binary.write_bytes(b'not a GameCube disc')
        with self.assertRaises(PatchError):rvz.compress_verified(binary,self.root/'bad.rvz')
        with patch.object(rvz,'ENGINE_SHA256','0'*64),self.assertRaises(PatchError):
            with rvz.engine_context():pass

    def test_cancellation_during_native_conversion_cleans_owned_process(self):
        source=self.root/'source.rvz';source.write_bytes(self.rvz.read_bytes())
        cancel=threading.Event()
        def progress(message,fraction):
            if message=='Extracting RVZ to ISO':cancel.set()
        with self.assertRaises(Cancelled):
            rvz.unpack_to_folder(source,self.root/'cancelled',cancel,progress)
        self.assertFalse((self.root/'cancelled').exists())
        self.assertEqual(list(self.root.glob('.retro-*')),[])
        self.assertEqual(source.read_bytes(),self.rvz.read_bytes())

    def test_synthetic_wii_roundtrip(self):
        data=bytearray(2*1024**2);data[:6]=b'RTEST0';data[0x18:0x1c]=bytes.fromhex('5d1c9ea3')
        data[0x100000:0x100100]=bytes(range(256))
        iso=self.root/'wii.iso';iso.write_bytes(data)
        packed=self.root/'wii.rvz';rvz.compress_verified(iso,packed)
        with tempfile.TemporaryDirectory(dir=str(self.root)) as folder:
            self.assertEqual(rvz.extract(packed,folder).read_bytes(),data)

    def test_output_roundtrip_mismatch_never_published(self):
        original_extract=rvz.extract
        def corrupt(source,stage,*args):
            p=original_extract(source,stage,*args)
            with p.open('r+b') as f:f.seek(9000);f.write(b'wrong bytes')
            return p
        with patch.object(rvz,'extract',side_effect=corrupt),self.assertRaises(PatchError):
            apply_plan(self.iso,self.root/'must-not-exist.rvz',self.plan(),self.catalog,self.client,cache=self.root/'cache',rvz_output=True)
        self.assertFalse((self.root/'must-not-exist.rvz').exists())
        self.assertEqual(list(self.root.glob('.retro-*')),[])
