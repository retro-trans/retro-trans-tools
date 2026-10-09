"""Native adapters, archive boundaries and platform-specific update isolation."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

from retro_trans import mac_updater as u, vita_pkg as v
from retro_trans.core import PatchError, Cancelled


class MacTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def bundle(self, name='update.zip', extra=()):
        archive = self.root/name
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr(u.APP+'/Contents/Info.plist', plistlib.dumps({
                'CFBundleIdentifier': u.IDENTIFIER, 'CFBundleShortVersionString': '9.0.0',
                'CFBundleExecutable': 'Retro-Trans'}))
            z.writestr(u.APP+'/Contents/MacOS/Retro-Trans', b'new app')
            for name, data, mode in extra:
                item = zipfile.ZipInfo(name); item.external_attr = mode << 16
                z.writestr(item, data)
        return archive

    def test_bundle_identity_and_path_boundaries(self):
        archive = self.bundle()
        result = u.extract_app(archive, self.root/'valid', '9.0.0')
        self.assertEqual(u.executable(result).read_bytes(), b'new app')
        with self.assertRaises(PatchError):
            u.extract_app(archive, self.root/'wrong-version', '8.0.0')
        for i, name in enumerate(('../escape', '/absolute', u.APP+'/../escape', 'Other.app/file')):
            archive = self.bundle('bad%d.zip'%i, [(name, b'no', stat.S_IFREG)])
            with self.subTest(name=name), self.assertRaises(PatchError):
                u.extract_app(archive, self.root/('bad%d'%i), '9.0.0')
        archive = self.bundle('link.zip', [(u.APP+'/Contents/bad', b'../../../outside', stat.S_IFLNK)])
        with self.assertRaises(PatchError):
            u.extract_app(archive, self.root/'link', '9.0.0')

    def test_mac_vita_publisher_selection(self):
        client = Mock()
        for arch, filename in [('arm64', 'macos-arm64-latest.dmg'), ('x86_64', 'macos-latest.dmg')]:
            client.json.return_value = {'tag_name':'continuous', 'assets':[{
                'name':filename, 'browser_download_url':v.URL.rsplit('/',1)[0]+'/'+filename,
                'size':100, 'digest':'sha256:'+'a'*64}]}
            with patch.object(v, 'sys', SimpleNamespace(platform='darwin')), patch('retro_trans.macos.architecture', return_value=arch):
                self.assertEqual(v.runtime_asset(client, None).name, filename)

    @unittest.skipUnless(sys.platform == 'darwin', 'Mac whole-bundle filesystem test')
    def test_mac_install_success_failure_and_backup(self):
        for fail in (False, True):
            root = self.root/str(fail); root.mkdir()
            target = root/u.APP
            (target/'Contents').mkdir(parents=True)
            (target/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':u.IDENTIFIER}))
            (target/'old').write_text('keep')
            directory = root/'updates'; directory.mkdir()
            archive = self.bundle('fixture-%s.zip'%fail)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            (directory/(digest+'.zip')).write_bytes(archive.read_bytes())
            _, asset, platform_id = u.names()
            (directory/'pending-mac.json').write_text(json.dumps({'version':'9.0.0',
                'sha256':digest, 'bytes':archive.stat().st_size, 'asset':asset, 'platform':platform_id}))
            def health(*a, **kw):
                return not (fail and kw.get('launch'))
            self.assertEqual(u.install(target, directory, health), not fail)
            if fail:
                self.assertEqual((target/'old').read_text(), 'keep')
            else:
                self.assertTrue(list(root.glob('*.previous-*')))

    @unittest.skipUnless(sys.platform == 'darwin', 'Mac process isolation')
    def test_vita_portable_directory_and_cancellation(self):
        bundle = self.root/'Vita3K.app'
        exe = bundle/'Contents/MacOS/Vita3K'
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b'fake')
        (bundle/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable':'Vita3K'}))
        self.assertEqual(v.portable_directory(exe), self.root/'portable')
        process = Mock(); process.poll.return_value = None
        cancel = Mock(); cancel.is_set.return_value = True
        with patch.object(v.subprocess, 'Popen', return_value=process) as popen:
            with self.assertRaises(Cancelled):
                v.run_installer(exe, self.root/'input.pkg', 'private', self.root/'portable/fs', cancel)
        process.kill.assert_called_once()
        self.assertEqual(popen.call_args.kwargs['creationflags'], 0)
        self.assertNotIn('private', (self.root/'portable/config.yml').read_text())
