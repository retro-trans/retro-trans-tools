import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from retro_trans import __version__
from scripts.prepare_release import PREVIEW_SIGNER, prepare


class ReleaseGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifacts = self.root/'artifacts'
        self.output = self.root/'release'
        self.artifacts.mkdir()
        self.health = dict(version=__version__, ok=True, tls=dict(provider='windows-native'))
        win = self.asset('Retro-Trans.exe')
        self.json('UPDATE.json', dict(version=__version__, platform='windows-x86_64', asset='Retro-Trans.exe', **win))
        with zipfile.ZipFile(self.artifacts/'Retro-Trans-Windows.zip', 'w') as z:
            z.write(self.artifacts/'Retro-Trans.exe', 'Retro-Trans.exe')
        for name in ('packaged-health.json', 'packaged-network.json'):
            self.json(name, self.health)
        for arch in ('arm64', 'x86_64'):
            folder = self.artifacts/arch
            folder.mkdir()
            name = 'Retro-Trans-macos-'+arch+'.zip'
            record = self.asset(name, folder)
            self.json('UPDATE-macos-'+arch+'.json', dict(version=__version__, platform='macos-'+arch, asset=name, **record), folder)
            for check in ('APP-HEALTH.json', 'NETWORK-HEALTH.json'):
                self.json(check, self.health, folder)
            self.json('MAC-VALIDATION.json', dict(version=__version__, packaged_next_launch_update=True), folder)
        name = 'Retro-Trans-Linux-x86_64-'+__version__+'.tar.gz'
        record = self.asset(name)
        self.json('LINUX-'+__version__+'-VALIDATION.json', dict(version=__version__, tests_passed=True,
                  health=self.health, archive=dict(name=name, **record)))
        self.asset('SHA256SUMS-Linux-'+__version__+'.txt')
        self.json('CLEAN-LINUX-HEALTH.json', self.health)
        name = 'Retro-Trans-Android-'+__version__+'-preview.apk'
        record = self.asset(name)
        self.android = dict(version=__version__, version_name=__version__+'-preview', preview=True,
                            abis=['arm64-v8a', 'x86_64'], signer_sha256=PREVIEW_SIGNER,
                            native_16kb_alignment=True, apk_16kb_alignment=True, lint_errors=0,
                            jvm_tests=[dict(tests=1, failures=0, errors=0)],
                            emulator_tests=[dict(tests=1, failures=0, errors=0)], apk=dict(name=name, **record))
        self.json('ANDROID-'+__version__+'-VALIDATION.json', self.android)
        self.asset('README-Android.md')

    def asset(self, name, folder=None):
        path = (folder or self.artifacts)/name
        path.write_bytes(('Synthetic fixture: '+name).encode())
        return dict(bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())

    def json(self, name, value, folder=None):
        ((folder or self.artifacts)/name).write_text(json.dumps(value), encoding='utf-8')

    def test_complete_current_release_stages_all_platforms_and_checksums(self):
        report = prepare(self.artifacts, self.output)
        self.assertEqual(len(report['platforms']), 5)
        for line in (self.output/'SHA256SUMS.txt').read_text().splitlines():
            digest, name = line.split('  ')
            self.assertEqual(digest, hashlib.sha256((self.output/name).read_bytes()).hexdigest())

    def test_missing_platform_prevents_any_staging(self):
        (self.artifacts/self.android['apk']['name']).unlink()
        with self.assertRaises(ValueError):
            prepare(self.artifacts, self.output)
        self.assertFalse(self.output.exists())

    def test_stale_build_prevents_staging(self):
        self.json('APP-HEALTH.json', dict(self.health, version='0.5.18'), self.artifacts/'arm64')
        with self.assertRaisesRegex(ValueError, 'stale'):
            prepare(self.artifacts, self.output)
        self.assertFalse(self.output.exists())

    def test_changed_download_and_wrong_signer_are_rejected(self):
        self.android['signer_sha256'] = '0'*64
        self.json('ANDROID-'+__version__+'-VALIDATION.json', self.android)
        with self.assertRaises(ValueError):
            prepare(self.artifacts, self.output)
        self.android['signer_sha256'] = PREVIEW_SIGNER
        self.json('ANDROID-'+__version__+'-VALIDATION.json', self.android)
        (self.artifacts/'Retro-Trans.exe').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            prepare(self.artifacts, self.output)

    def test_mismatching_windows_zip_is_rejected(self):
        with zipfile.ZipFile(self.artifacts/'Retro-Trans-Windows.zip', 'w') as z:
            z.writestr('Retro-Trans.exe', b'old build')
        with self.assertRaisesRegex(ValueError, 'different EXE'):
            prepare(self.artifacts, self.output)

    def test_failed_platform_check_is_not_publishable(self):
        self.json('CLEAN-LINUX-HEALTH.json', dict(self.health, ok=False))
        with self.assertRaises(ValueError):
            prepare(self.artifacts, self.output)
        self.assertFalse(self.output.exists())
