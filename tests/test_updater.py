import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from retro_trans.core import GitHubClient, PatchError
from retro_trans.catalog import atomic_json
from retro_trans.updater import stage_update, pending_update, install_staged, update_status


class UpdateClient(GitHubClient):
    def __init__(self, binary=b"new executable", corrupt=False):
        self.binary, self.corrupt = binary, corrupt
        self.metadata = json.dumps({"schema_version": 1, "version": "9.0.0", "platform": "windows-x86_64",
            "asset": "Retro-Trans.exe", "sha256": hashlib.sha256(binary).hexdigest(), "bytes": len(binary)}).encode()
        self.prefix = "https://github.com/retro-trans/retro-trans-tools/releases/download/v9.0.0/"

    def json(self, *args):
        return {"tag_name": "v9.0.0", "assets": [
            {"name": name, "size": len(data), "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
             "browser_download_url": self.prefix + name}
            for name, data in (("UPDATE.json", self.metadata), ("Retro-Trans.exe", self.binary))]}

    def read(self, *args):
        return self.metadata

    def open(self, url):
        return io.BytesIO(b"broken" if self.corrupt else self.binary)


class UpdateTests(unittest.TestCase):
    def setUp(self):
        # These fixtures exercise the unchanged Windows update protocol on either OS.
        self.addCleanup(patch.stopall)
        patch('retro_trans.updater.sys', SimpleNamespace(platform='win32')).start()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.target = self.root / "installed.exe"
        self.target.write_bytes(b"old executable")
        self.directory = self.root / "updates"

    def tearDown(self):
        self.temp.cleanup()

    def test_verified_stage_and_install_preserve_settings_and_backup(self):
        stage_update(UpdateClient(), self.directory)
        settings = self.root / "settings.json"
        settings.write_text('{"keep":true}')
        self.assertTrue(install_staged(self.target, self.directory, health_check=lambda *a, **kw: True))
        self.assertEqual(self.target.read_bytes(), b"new executable")
        self.assertEqual(self.target.with_name("installed.exe.previous").read_bytes(), b"old executable")
        self.assertEqual(settings.read_text(), '{"keep":true}')
        self.assertFalse((self.directory / "pending.json").exists())

    def test_corrupt_download_never_becomes_pending(self):
        with self.assertRaises(PatchError):
            stage_update(UpdateClient(corrupt=True), self.directory)
        self.assertFalse((self.directory / "pending.json").exists())
        self.assertEqual(self.target.read_bytes(), b"old executable")

    def test_tampered_staged_update_rejected(self):
        stage_update(UpdateClient(), self.directory)
        _, candidate = pending_update(self.directory)
        candidate.write_bytes(b"tampered")
        with self.assertRaises(PatchError):
            pending_update(self.directory)

    def test_startup_failure_rolls_back(self):
        stage_update(UpdateClient(), self.directory)
        def health(*args, **kwargs):
            return not kwargs.get("launch", False)
        self.assertFalse(install_staged(self.target, self.directory, health_check=health))
        self.assertEqual(self.target.read_bytes(), b"old executable")
        status = json.loads((self.directory / "status.json").read_text())
        self.assertEqual(status["failed_version"], "9.0.0")
        self.assertIn("needs attention", stage_update(UpdateClient(), self.directory))

    def test_preflight_failure_keeps_original(self):
        stage_update(UpdateClient(), self.directory)
        self.assertFalse(install_staged(self.target, self.directory, health_check=lambda *a, **kw: False))
        self.assertEqual(self.target.read_bytes(), b"old executable")

    def test_locked_destination_retains_old_app(self):
        stage_update(UpdateClient(), self.directory)
        import os
        replace = os.replace
        def locked(source, destination):
            if Path(source) == self.target:
                raise PermissionError("Locked")
            return replace(source, destination)
        with patch("retro_trans.updater.os.replace", locked):
            self.assertFalse(install_staged(self.target, self.directory, health_check=lambda *a, **kw: True, retry_seconds=0))
        self.assertEqual(self.target.read_bytes(), b"old executable")

    def test_current_version_and_untrusted_metadata_do_not_install(self):
        self.assertIsNone(stage_update(UpdateClient(), self.directory, current="9.0.0"))
        client = UpdateClient()
        metadata = json.loads(client.metadata)
        metadata["asset"] = "../../bad.exe"
        client.metadata = json.dumps(metadata).encode()
        with self.assertRaises(PatchError):
            stage_update(client, self.directory)

    def test_status_ignores_success_for_another_executable_version(self):
        default = update_status(self.directory, current='0.5.17')
        for version in ('0.5.16', '0.5.18'):
            with self.subTest(version=version):
                path = self.directory / 'status.json'
                atomic_json(path, {'message': 'Updated to ' + version})
                before = path.read_bytes()
                self.assertEqual(update_status(self.directory, current='0.5.17'), default)
                self.assertEqual(path.read_bytes(), before)  # Keep historical diagnostics intact.
        atomic_json(self.directory / 'status.json', {'message': 'Updated to 0.5.17'})
        self.assertEqual(update_status(self.directory, current='0.5.17'), 'Updated to 0.5.17')

    def test_status_preserves_install_failure_and_handles_invalid_history(self):
        default = update_status(self.directory, current='0.5.17')
        path = self.directory / 'status.json'
        message = 'Automatic update failed: destination locked. Existing app retained.'
        atomic_json(path, {'failed_version': '0.5.18', 'message': message})
        self.assertEqual(update_status(self.directory, current='0.5.17'), message)
        for data in (None, [], {}, {'message': None}, {'message': []}, {'message': ' '}):
            with self.subTest(data=data):
                atomic_json(path, data)
                self.assertEqual(update_status(self.directory, current='0.5.17'), default)
        path.write_text('{incomplete', encoding='utf-8')
        self.assertEqual(update_status(self.directory, current='0.5.17'), default)


if __name__ == "__main__":
    unittest.main()
