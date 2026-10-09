import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import zipfile
import zlib

from retro_trans import vita_pkg as p, vita_repatch as v
from retro_trans.core import Cancelled, PatchError, Asset


class PkgTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pkg = self.root/'original.pkg'
        self.license = self.root/'work.bin'
        header = bytearray(128)
        header[:4] = b'\x7fPKG'
        struct.pack_into('>Q', header, 0x18, 128)
        header[0x30:0x60] = b'JP0000-PCSG00264_00-ABCDEFGHIJKLMNOP'.ljust(48, b'\0')
        self.pkg.write_bytes(header)
        data = bytearray(512)
        struct.pack_into('>HHH', data, 0, 1, 1, 1)
        struct.pack_into('<Q', data, 8, 0x0123456789abcdef)
        data[0x10:0x40] = header[0x30:0x60]
        data[0x50:0x60] = b'private-fixture!'
        self.license.write_bytes(data)

    def test_license_identity_and_bounds(self):
        original = self.license.read_bytes()
        self.assertEqual(p.license_bytes(self.pkg, self.license), original)
        for data in (original + b'x', original[:511], bytes(512),
                     original[:0x17] + b'X' + original[0x18:],
                     original[:0x50] + bytes(16) + original[0x60:]):
            self.license.write_bytes(data)
            with self.subTest(size=len(data)), self.assertRaises(PatchError) as err:
                p.license_bytes(self.pkg, self.license)
            self.assertNotIn('private-fixture', str(err.exception))

    def test_license_encoding_independent_deflate(self):
        data = self.license.read_bytes()
        encoded = base64.b64decode(p.encoded_license(data))
        header, dictionary = struct.unpack('>HI', encoded[:6])
        self.assertEqual(header % 31, 0)
        self.assertTrue(header & 0x20)
        self.assertEqual(dictionary, 0x627d1d5d)
        self.assertEqual(zlib.decompress(encoded[6:-4], -10), data)
        self.assertEqual(struct.unpack('>I', encoded[-4:])[0], zlib.adler32(data))

    def test_publisher_asset_identity(self):
        item = dict(name='windows-latest.zip', browser_download_url=p.URL,
                    size=100, digest='sha256:'+'a'*64)
        release = dict(tag_name='continuous', draft=False, assets=[item])
        client = Mock(); client.json.return_value = release
        self.assertEqual(p.runtime_asset(client, None).sha256, 'a'*64)
        for key, value in [('browser_download_url', 'https://example.com/tool.exe'),
                           ('digest', ''), ('size', 151*1024**2)]:
            changed = dict(item); changed[key] = value
            client.json.return_value = dict(release, assets=[changed])
            with self.subTest(key=key), self.assertRaises(PatchError):
                p.runtime_asset(client, None)

    def archive(self, name):
        archive = self.root/'runtime.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr(name, b'tool')
        return archive

    def test_runtime_path_guards(self):
        for name in ('../Vita3K.exe', '/Vita3K.exe', 'C:/Vita3K.exe',
                     'NUL.exe', 'portable/config.yml', 'Vita3K.exe:stream'):
            with self.subTest(name=name), self.assertRaises(PatchError):
                p.extract_runtime(self.archive(name), self.root/'engine')
        exe = p.extract_runtime(self.archive('Vita3K.exe'), self.root/'engine')
        self.assertEqual(exe.read_bytes(), b'tool')

    @unittest.skipUnless(os.name == 'nt', 'Windows process isolation')
    def test_process_isolation_and_cancel(self):
        exe = self.root/'Vita3K.exe'
        fs = self.root/'portable/fs'
        process = Mock(); process.poll.return_value = None
        cancel = threading.Event(); cancel.set()
        with patch.object(p.subprocess, 'Popen', return_value=process) as popen:
            with self.assertRaises(Cancelled):
                p.run_installer(exe, self.pkg, 'secret-fixture', fs, cancel)
        process.kill.assert_called_once()
        process.wait.assert_called_once()
        args, options = popen.call_args.args[0], popen.call_args.kwargs
        self.assertEqual(args[1:3], ['--pkg', str(self.pkg)])
        self.assertEqual(options['stdout'], p.subprocess.DEVNULL)
        self.assertEqual(options['stderr'], p.subprocess.DEVNULL)
        self.assertEqual(options['cwd'], exe.parent)
        for key in ('APPDATA', 'LOCALAPPDATA', 'TEMP', 'TMP'):
            self.assertTrue(Path(options['env'][key]).is_relative_to(self.root))
        self.assertNotIn('secret-fixture', (self.root/'portable/config.yml').read_text())

    @unittest.skipUnless(os.name == 'nt', 'Windows read sharing')
    def test_input_lock_blocks_writes(self):
        with p.read_lock(self.pkg):
            self.assertEqual(self.pkg.read_bytes()[:4], b'\x7fPKG')
            with self.assertRaises(PermissionError):
                self.pkg.open('wb')
        self.assertEqual(self.pkg.stat().st_size, 128)

    def test_pkg_dispatch_and_cleanup_context(self):
        seen = []
        @contextmanager
        def source(*args):
            seen.append('enter')
            try:
                yield self.root/'decrypted'
            finally:
                seen.append('exit')
        # Actual folder patching fails; the temporary package context still exits.
        with patch.object(p, 'decrypted_source', source), patch.object(v, 'local_description'):
            with self.assertRaises(PatchError):
                v.apply(self.pkg, self.root/'output', 'profile.json', work_bin=self.license)
        self.assertEqual(seen, ['enter', 'exit'])


if __name__ == '__main__':
    unittest.main()
