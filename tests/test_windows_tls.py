"""Real Windows HTTPS verification without changing the machine's trust stores.

Only synthetic certificates and loopback sockets are used. The CA is trusted
in one client context, never installed in Windows. DNS and proxies are bypassed
only to route the real GitHub client requests to the local fixture server.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import socket
import ssl
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from retro_trans.core import GitHubClient, PatchError
from retro_trans.network_check import tls_details
from retro_trans.vita_downloads import VitaReleaseClient


@unittest.skipUnless(sys.platform == 'win32', 'Windows native certificate verification')
class WindowsTlsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = datetime.now(timezone.utc)
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Retro Trans temporary TLS test CA')])
        self.ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                   .public_key(self.ca_key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(self.now - timedelta(days=2))
                   .not_valid_after(self.now + timedelta(days=2))
                   .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                   .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
                   .sign(self.ca_key, hashes.SHA256()))
        (self.root/'ca.pem').write_bytes(self.ca.public_bytes(serialization.Encoding.PEM))
        (self.root/'key.pem').write_bytes(self.key.private_bytes(serialization.Encoding.PEM,
                                        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        self.requests = []

    def client(self, trusted=True, vita=False):
        with patch.dict(os.environ, {'GH_TOKEN': 'test-only-token'}):
            client = VitaReleaseClient(cache=self.root) if vita else GitHubClient()
        context = client.tls_context()
        if trusted:
            context.load_verify_locations(cafile=str(self.root/'ca.pem'))
        self.assertEqual(tls_details(client), dict(provider='windows-native',
                         verification_required=True, hostname_checked=True))
        return client

    @contextmanager
    def server(self, *, hostname='api.github.com', expired=False, redirect=False, valid_redirect=True):
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
        hosts = [x509.DNSName(hostname)]
        if valid_redirect:
            hosts.append(x509.DNSName('release-assets.githubusercontent.com'))
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(self.ca.subject)
                .public_key(self.key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(self.now - timedelta(days=2))
                .not_valid_after(self.now + timedelta(days=-1 if expired else 1))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .add_extension(x509.SubjectAlternativeName(hosts), critical=False)
                .sign(self.ca_key, hashes.SHA256()))
        (self.root/'server.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        requests = self.requests

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                requests.append((self.headers['Host'], self.headers.get('Authorization')))
                if redirect and self.headers['Host'] == 'api.github.com':
                    self.send_response(302)
                    self.send_header('Location', 'https://release-assets.githubusercontent.com/fixture')
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.send_header('Content-Length', '2')
                    self.end_headers()
                    self.wfile.write(b'ok')

        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(self.root/'server.pem', self.root/'key.pem')
        with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
            server.socket = server_context.wrap_socket(server.socket, server_side=True)
            server.socket.settimeout(5)
            worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
            worker.start()
            connect = socket.create_connection

            def loopback(address, *args, **kwargs):
                self.assertIn(address[0], ('api.github.com', 'release-assets.githubusercontent.com'))
                return connect(server.server_address, *args, **kwargs)

            try:
                with patch('socket.create_connection', side_effect=loopback), \
                        patch('urllib.request.getproxies', return_value={}):
                    yield
            finally:
                server.shutdown()
                worker.join(timeout=5)

    def test_trusted_certificate_and_context_reuse(self):
        client = self.client()
        with self.server():
            for _ in range(2):
                self.assertEqual(client.read('https://api.github.com/repos/retro-trans/fixture'), b'ok')
        self.assertEqual(len(self.requests), 2)

    def test_untrusted_certificate_rejected_before_sending_request(self):
        client = self.client(trusted=False)
        with self.server(), self.assertRaisesRegex(PatchError, 'HTTPS certificate'):
            client.read('https://api.github.com/repos/retro-trans/fixture')
        self.assertEqual(self.requests, [])

    def test_wrong_hostname_rejected_before_sending_request(self):
        client = self.client()
        with self.server(hostname='unrelated.example'), self.assertRaisesRegex(PatchError, 'HTTPS certificate'):
            client.read('https://api.github.com/repos/retro-trans/fixture')
        self.assertEqual(self.requests, [])

    def test_expired_certificate_rejected_before_sending_request(self):
        client = self.client()
        with self.server(expired=True), self.assertRaisesRegex(PatchError, 'HTTPS certificate'):
            client.read('https://api.github.com/repos/retro-trans/fixture')
        self.assertEqual(self.requests, [])

    def test_vita_asset_redirect_keeps_tls_and_strips_authorization(self):
        client = self.client(vita=True)
        with self.server(redirect=True):
            self.assertEqual(client.read('https://api.github.com/repos/retro-trans/fixture/releases/assets/1'), b'ok')
        self.assertEqual(self.requests, [('api.github.com', 'Bearer test-only-token'),
                                       ('release-assets.githubusercontent.com', None)])

    def test_vita_asset_redirect_rejects_wrong_hostname(self):
        client = self.client(vita=True)
        with self.server(redirect=True, valid_redirect=False), self.assertRaises(PatchError) as raised:
            client.read('https://api.github.com/repos/retro-trans/fixture/releases/assets/1')
        self.assertIsInstance(raised.exception.__cause__.reason, ssl.SSLCertVerificationError)
        self.assertEqual(self.requests, [('api.github.com', 'Bearer test-only-token')])
