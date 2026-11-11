import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from retro_trans import linux, updater, mx_crypto
from retro_trans.core import PatchError


class LinuxTests(unittest.TestCase):
    def test_linux_never_downloads_windows_updates(self):
        client=Mock()
        client.json.return_value=dict(tag_name='v9.0.0',assets=[dict(name='Retro-Trans.exe')])
        with patch.object(updater,'sys',SimpleNamespace(platform='linux')):
            self.assertIsNone(updater.stage_update(client,current='0.5.22'))
            client.download.assert_not_called()
            self.assertIn('download and extract',updater.update_status())
            client.json.return_value['assets'].append(dict(name=linux.archive_name('9.0.0')))
            self.assertIn('9.0.0',updater.stage_update(client,current='0.5.22'))
            client.download.assert_not_called()

    def test_linux_cipher_vector_closed_key_and_roundtrip(self):
        with patch.object(mx_crypto,'sys',SimpleNamespace(platform='linux')):
            key=bytes.fromhex('2b7e151628aed2a6abf7158809cf4f3c')
            with mx_crypto.AES(key) as cipher:
                encoded=cipher.crypt(bytes.fromhex('6bc1bee22e409f96e93d7e117393172a'),iv=bytes(range(16)))
                self.assertEqual(encoded.hex(),'7649abac8119b246cee98e9b12e9197d')
                self.assertEqual(cipher.crypt(encoded,True,bytes(range(16))).hex(),'6bc1bee22e409f96e93d7e117393172a')
            with self.assertRaises(ValueError):cipher.crypt(bytes(16))
            self.assertEqual(mx_crypto.cmac(key,b'').hex(),'bb1d6929e95937287fa37d129b756746')

    def test_native_tools_reject_corruption_and_wrong_architecture(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);tool=root/'xdelta3';tool.write_bytes(b'fixture');tool.chmod(0o755)
            (root/'manifest.json').write_text(json.dumps(dict(architecture='x86_64',sha256={'xdelta3':hashlib.sha256(b'fixture').hexdigest()})))
            with patch.object(linux,'ROOT',root),patch.object(linux.platform,'machine',return_value='x86_64'):
                self.assertEqual(linux.native_tool('xdelta3'),tool)
                with patch.object(linux.platform,'machine',return_value='aarch64'),self.assertRaises(PatchError):linux.native_tool('xdelta3')
                tool.write_bytes(b'corrupt')
                with self.assertRaises(PatchError):linux.native_tool('xdelta3')
                with self.assertRaises(PatchError):linux.native_tool('../xdelta3')

    def test_system_opener_does_not_inherit_bundled_libraries(self):
        with patch.dict(os.environ,{'LD_LIBRARY_PATH':'/bundle','LD_LIBRARY_PATH_ORIG':'/user'},clear=True):
            self.assertEqual(linux.system_environment(),{'LD_LIBRARY_PATH':'/user'})
            self.assertEqual(os.environ['LD_LIBRARY_PATH'],'/bundle')
        with patch.dict(os.environ,{'LD_LIBRARY_PATH':'/bundle'},clear=True):
            self.assertNotIn('LD_LIBRARY_PATH',linux.system_environment())

    @unittest.skipUnless(sys.platform=='linux','Linux native UI')
    def test_unsupported_vita_operations_are_disabled_and_explained(self):
        from retro_trans.gui import Application
        from retro_trans.vita_automatic import VitaPackage
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'RETRO_TRANS_DATA_DIR':folder}):
            app=Application(startup=False,visible=False)
            try:
                app.notebook.select(3)
                app.vita_source.set('original.pkg');app.vita_license.set('work.bin');app.vita_output.set('output.pkg')
                app.update_action()
                self.assertEqual(str(app.apply_button['state']),'disabled')
                self.assertIn('unavailable on Linux',app.vita_summary.get())
                with patch('retro_trans.gui.messagebox.showinfo') as message,patch.object(app,'start') as start:
                    app.create_vita_repatch();message.assert_called_once();start.assert_not_called()
                app.notebook.select(0)
                app.selection=(Path(folder)/'original.pkg',VitaPackage('JP0700-PCSG00597_00-CROSSANGEGAME000'))
                app.plan_selection();app.auto_vita_license.set('work.bin');app.update_action()
                self.assertIn('requires Windows',app.detail.get())
                self.assertEqual(str(app.apply_button['state']),'disabled')
            finally:app.destroy()
