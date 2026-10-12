import json
import hashlib
import io
from contextlib import nullcontext
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
import urllib.error
from unittest.mock import patch

from retro_trans import diagnostics as d, vita_repatch as v
from retro_trans.core import Cancelled, GitHubClient, PatchError, Asset, sha256_file


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        d.close_session()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.log = d.start_session(self.root/'logs')

    def tearDown(self):
        d.close_session()
        self.temp.cleanup()

    def rows(self):
        return [json.loads(line) for line in self.log.read_text(encoding='utf-8').splitlines()]

    def test_session_metadata_and_private_fields_rejected(self):
        self.assertEqual(self.rows()[0]['event'], 'session_start')
        self.assertIn('version', self.rows()[0])
        d.event('vita_input', mode='automatic', pkg=True, work_bin='LICENSE-SECRET', path='/Users/private-name/game.pkg')
        d.event('network_open', host='github.com', endpoint='release_asset', url='https://github.com/?token=TOKEN-SECRET')
        d.event('arbitrary_message', message='PRIVATE-MESSAGE')
        text = self.log.read_text()
        for secret in ('LICENSE-SECRET', 'private-name', 'TOKEN-SECRET', 'PRIVATE-MESSAGE'):
            self.assertNotIn(secret, text)
        if os.name != 'nt':
            self.assertEqual(self.log.stat().st_mode & 0o777, 0o600)

    def test_exceptions_never_serialize_messages_commands_or_locals(self):
        try:
            try:
                raise subprocess.CalledProcessError(1, ['Vita3K', '--zrif', 'LICENSE-SECRET'], output=b'KEY-SECRET')
            except subprocess.CalledProcessError as exc:
                raise PatchError('File mismatch: /Users/private-name/secret-save') from exc
        except PatchError as exc:
            d.exception(exc)
        text = self.log.read_text()
        for secret in ('LICENSE-SECRET', 'KEY-SECRET', 'private-name', 'secret-save', '--zrif'):
            self.assertNotIn(secret, text)
        row = self.rows()[-1]
        self.assertEqual(row['category'], 'file_mismatch')
        self.assertEqual(row['types'], ['PatchError', 'CalledProcessError'])

    def test_operations_cancel_failure_and_thread_correlation(self):
        def work(kind):
            with d.operation(kind):
                d.progress('Verifying /Users/secret-name/input')
                d.progress('Verifying /Users/secret-name/input')
        threads = [threading.Thread(target=work, args=(name,)) for name in ('patch', 'catalog_refresh')]
        for t in threads: t.start()
        for t in threads: t.join()
        with self.assertRaises(Cancelled), d.operation('vita_repatch'):
            raise Cancelled('Cancelled. Your original file is unchanged.')
        with self.assertRaises(ValueError), d.operation('save_convert'):
            raise ValueError('SECRET')
        ends = [r for r in self.rows() if r['event'] == 'operation_end']
        self.assertEqual(len({r['operation'] for r in ends}), 4)
        self.assertEqual(sorted(r['outcome'] for r in ends), ['cancelled', 'error', 'success', 'success'])
        self.assertEqual(len([r for r in self.rows() if r['event'] == 'phase']), 2)
        self.assertNotIn('secret-name', self.log.read_text())
        self.assertNotIn('SECRET', self.log.read_text())

    def test_missing_size_and_hash_failure_are_distinct(self):
        path = self.root/'VITA-PCSG00264-test18-000.xdelta'
        expected = dict(bytes=4, sha256='0'*64)
        for content, result in [(None, 'missing'), (b'abc', 'size_mismatch'), (b'abcd', 'hash_mismatch')]:
            if content is not None: path.write_bytes(content)
            with self.assertRaises(PatchError):
                v.verify(path, expected)
            self.assertEqual(self.rows()[-1]['result'], result)
        expected['sha256'] = sha256_file(path)
        v.verify(path, expected)
        row = self.rows()[-1]
        self.assertEqual(row['result'], 'verified')
        self.assertEqual(row['actual_sha256'], expected['sha256'])
        path = self.root/'private-save-name.bin'; path.write_bytes(b'abcd')
        v.verify(path, expected)
        self.assertNotIn('actual_sha256', self.rows()[-1])
        self.assertNotIn('private-save-name', self.log.read_text())

    def test_network_failure_keeps_status_not_auth_url(self):
        url = 'https://api.github.com/repos/retro-trans/tools?secret=TOKEN-SECRET'
        with patch.dict(os.environ, {'GH_TOKEN': 'AUTH-SECRET'}), \
                patch.object(GitHubClient, 'tls_context', return_value=None), \
                patch('urllib.request.urlopen', side_effect=urllib.error.HTTPError(url, 403, 'SECRET', None, None)):
            with self.assertRaises(PatchError): GitHubClient().open(url)
        row = self.rows()[-1]
        self.assertEqual(row['http_status'], 403)
        self.assertNotIn('SECRET', self.log.read_text())

    def test_download_cache_and_vita_input_modes_are_recorded(self):
        payload = b'public patch fixture'
        asset = Asset('public.xdelta', 'https://github.com/retro-trans/test/releases/download/v1/public.xdelta',
                      len(payload), hashlib.sha256(payload).hexdigest())
        client = GitHubClient()
        with patch.object(client, 'open', side_effect=lambda _: io.BytesIO(payload)):
            path = client.download(asset, self.root/'cache')
            client.download(asset, self.root/'cache')
            path.write_bytes(b'corrupt')
            client.download(asset, self.root/'cache')
        states = [r['state'] for r in self.rows() if r['event'] == 'download']
        self.assertEqual(states, ['started', 'verified', 'cache_hit', 'cache_rejected', 'started', 'verified'])
        for description in (None, self.root/'patches/fixture.zip', self.root/'patches/fixture.json'):
            with patch.object(v, 'description_context', return_value=nullcontext(({}, None, None))), \
                    patch.object(v, '_apply_files', return_value=self.root/'output'):
                v.apply(self.root/'source', self.root/'output', description)
        modes = [r['mode'] for r in self.rows() if r['event'] == 'vita_input']
        self.assertEqual(modes, ['automatic', 'local_zip', 'local_json'])

    def test_rotation_retention_and_nonlog_preservation(self):
        d.close_session()
        unrelated = self.root/'logs/keep.txt'; unrelated.write_text('keep')
        with patch.object(d, 'MAX_BYTES', 500), patch.object(d, 'KEEP_SESSIONS', 2):
            for _ in range(4):
                self.log = d.start_session(self.root/'logs')
                for _ in range(15): d.event('phase', stage='verifying')
                d.close_session()
        files = list((self.root/'logs').glob('*.log'))
        self.assertEqual(len(files), 2)
        self.assertLessEqual(len(list((self.root/'logs').glob('*.log*'))), 4)
        for path in (self.root/'logs').glob('*.log*'):
            self.assertLess(path.stat().st_size, 1000)
            for line in path.read_text().splitlines():
                self.assertIn('version', json.loads(line))
            if os.name != 'nt': self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(unrelated.read_text(), 'keep')

    def test_unwritable_directory_and_failed_write_do_not_break_operations(self):
        d.close_session()
        not_directory = self.root/'file'; not_directory.write_text('x')
        self.assertIsNone(d.start_session(not_directory/'logs'))
        with d.operation('patch'): d.event('phase', stage='verifying')
        self.log = d.start_session(self.root/'logs')
        with patch.object(d._logger.handlers[0], 'emit', side_effect=OSError('disk full')):
            with d.operation('patch'): d.event('phase', stage='verifying')
