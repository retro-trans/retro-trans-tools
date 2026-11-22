import io
import os
from pathlib import Path
import socket
import ssl
import sys
import tempfile
import types
import unittest
import urllib.error
from unittest.mock import Mock, patch

from retro_trans.core import GitHubClient, GitHubRateLimit, PatchError


class NetworkTests(unittest.TestCase):
    def test_mac_uses_explicit_bundle_and_reuses_verified_context(self):
        client = GitHubClient()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        certifi = types.SimpleNamespace(where=lambda: 'bundled/cacert.pem')
        with patch('retro_trans.core.sys.platform', 'darwin'), \
                patch.dict(sys.modules, {'certifi': certifi}), \
                patch('retro_trans.core.ssl.create_default_context', return_value=context) as create, \
                patch('urllib.request.urlopen', return_value=io.BytesIO(b'ok')) as open_url:
            client.open('https://api.github.com/repos/retro-trans/retro-trans-tools')
            client.open('https://github.com/retro-trans/retro-trans-tools/releases')
            create.assert_called_once_with(cafile='bundled/cacert.pem')
            self.assertIs(open_url.call_args.kwargs['context'], context)
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(context.check_hostname)

    def test_windows_uses_native_verifier_and_reuses_context(self):
        client = GitHubClient()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        truststore = types.SimpleNamespace(SSLContext=Mock(return_value=context))
        with patch('retro_trans.core.sys.platform', 'win32'), \
                patch.dict(sys.modules, {'truststore': truststore}), \
                patch('urllib.request.urlopen', return_value=io.BytesIO()) as open_url:
            client.open('https://github.com/retro-trans/retro-trans-tools')
            client.open('https://api.github.com/repos/retro-trans/retro-trans-tools')
            truststore.SSLContext.assert_called_once_with(ssl.PROTOCOL_TLS_CLIENT)
            self.assertIs(open_url.call_args.kwargs['context'], context)
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(context.check_hostname)

    def test_missing_windows_verifier_fails_closed_without_download(self):
        with patch('retro_trans.core.sys.platform', 'win32'), \
                patch.dict(sys.modules, {'truststore': None}), \
                patch('urllib.request.urlopen') as open_url:
            with self.assertRaisesRegex(PatchError, 'Windows HTTPS verifier'):
                GitHubClient().open('https://github.com/retro-trans/retro-trans-tools')
            open_url.assert_not_called()

    def test_windows_verifier_initialization_failure_does_not_fall_back(self):
        truststore = types.SimpleNamespace(SSLContext=Mock(side_effect=OSError('private details')))
        with patch('retro_trans.core.sys.platform', 'win32'), \
                patch.dict(sys.modules, {'truststore': truststore}), \
                patch('urllib.request.urlopen') as open_url:
            with self.assertRaisesRegex(PatchError, 'Windows HTTPS verifier') as raised:
                GitHubClient().open('https://github.com/retro-trans/retro-trans-tools')
            self.assertNotIn('private details', str(raised.exception))
            open_url.assert_not_called()

    def test_windows_diagnostics_do_not_query_openssl_ca_store(self):
        from retro_trans.network_check import tls_details
        context = Mock(verify_mode=ssl.CERT_REQUIRED, check_hostname=True)
        context.cert_store_stats.side_effect = NotImplementedError
        with patch('retro_trans.core.sys.platform', 'win32'), \
                patch.object(GitHubClient, 'tls_context', return_value=context):
            self.assertEqual(tls_details(GitHubClient()), dict(provider='windows-native',
                             verification_required=True, hostname_checked=True))
            context.cert_store_stats.assert_not_called()
            context.check_hostname = False
            with self.assertRaisesRegex(PatchError, 'verification is not enabled'):
                tls_details(GitHubClient())

    def test_missing_bundle_fails_closed_without_download(self):
        with patch('retro_trans.core.sys.platform', 'darwin'), \
                patch.dict(sys.modules, {'certifi': None}), \
                patch('urllib.request.urlopen') as open_url:
            with self.assertRaisesRegex(PatchError, 'certificate bundle'):
                GitHubClient().open('https://github.com/retro-trans/retro-trans-tools')
            open_url.assert_not_called()

    def test_corrupt_bundle_fails_closed(self):
        certifi = types.SimpleNamespace(where=lambda: 'missing.pem')
        with patch('retro_trans.core.sys.platform', 'darwin'), \
                patch.dict(sys.modules, {'certifi': certifi}), \
                patch('retro_trans.core.ssl.create_default_context', side_effect=ssl.SSLError('bad CA')), \
                patch('urllib.request.urlopen') as open_url:
            with self.assertRaisesRegex(PatchError, 'certificate bundle'):
                GitHubClient().open('https://github.com/retro-trans/retro-trans-tools')
            open_url.assert_not_called()

    def test_errors_distinguish_tls_dns_timeout_without_leaking_details(self):
        cases = [(ssl.SSLCertVerificationError(1, 'secret URL'), 'HTTPS certificate'),
                 (ssl.SSLError(1, 'secret URL'), 'secure HTTPS'),
                 (socket.gaierror(-2, 'secret URL'), 'network address'),
                 (TimeoutError('secret URL'), 'timed out'),
                 (OSError('secret URL'), 'Could not reach GitHub')]
        for reason, message in cases:
            for exc in (reason, urllib.error.URLError(reason)):
                with self.subTest(reason=type(reason).__name__, wrapper=type(exc).__name__), \
                        patch.object(GitHubClient, 'tls_context', return_value=None), \
                        patch('urllib.request.urlopen', side_effect=exc):
                    with self.assertRaisesRegex(PatchError, message) as raised:
                        GitHubClient().open('https://github.com/retro-trans/retro-trans-tools')
                    self.assertNotIn('secret', str(raised.exception))

    def test_http_errors_remain_distinct(self):
        for code, message in [(404, 'No published release'), (403, 'denied access'), (429, 'limited'), (500, 'HTTP 500')]:
            with self.subTest(code=code), patch.object(GitHubClient, 'tls_context', return_value=None), \
                    patch('urllib.request.urlopen', side_effect=urllib.error.HTTPError(
                        'https://github.com/', code, 'secret URL', None, None)):
                with self.assertRaisesRegex(PatchError, message):
                    GitHubClient().open('https://github.com/retro-trans/retro-trans-tools')

    def test_rate_limit_reset_retry_after_and_secondary_body(self):
        for code, headers, body, deadline in [
                (403, {'X-RateLimit-Remaining':'0','X-RateLimit-Reset':'1120'}, b'', 1120),
                (429, {'Retry-After':'90'}, b'', 1090),
                (403, {}, b'{"message":"secondary rate limit"}', 1060),
                (429, {'Retry-After':'invalid'}, b'', 1060)]:
            error = urllib.error.HTTPError('https://api.github.com/secret', code, 'secret', headers, io.BytesIO(body))
            with self.subTest(headers=headers), patch('retro_trans.core.time.time', return_value=1000), \
                    patch('urllib.request.urlopen', side_effect=error):
                with self.assertRaises(GitHubRateLimit) as raised:
                    GitHubClient().open('https://api.github.com/repos/retro-trans/test')
                self.assertEqual(raised.exception.retry_at, deadline)
                self.assertIn('Try again after', str(raised.exception))
                self.assertNotIn('secret', str(raised.exception))

    @unittest.skipUnless(sys.platform in ('darwin', 'linux'), 'Bundled certificate test')
    def test_real_context_has_roots_without_host_certificate_paths(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {
                'SSL_CERT_FILE': str(Path(temp)/'absent.pem'),
                'SSL_CERT_DIR': str(Path(temp)/'absent')}):
            self.assertEqual(ssl.create_default_context().cert_store_stats()['x509_ca'], 0)
            context = GitHubClient().tls_context()
            self.assertGreater(context.cert_store_stats()['x509_ca'], 0)
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(context.check_hostname)
