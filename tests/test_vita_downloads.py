import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request
import zipfile

from retro_trans import vita_downloads as d, vita_translation as v
from retro_trans import game_library as lib
from retro_trans.core import GitHubClient, GitHubRateLimit, PatchError, Cancelled
from test_vita_translation import fixture, identity


class Releases(GitHubClient):
    def __init__(self, data, assets, pkg, profile=v):
        self.profile = profile
        self.calls = []
        self.blobs = {}
        self.records = {}
        self.library = dict(schema_version=1, games=[], vita_releases=[])
        self.add('retro-trans/fixture', data, assets, pkg)

    def add(self, repo, data, assets, pkg):
        v = self.profile
        data = copy.deepcopy(data)
        if v.SCHEMA != 'retro-trans-vita-repatch-v1' or 'package' in data:
            content = data.get('package',{}).get('content_id')
            data['package'] = identity(pkg)
            if content is not None:data['package']['content_id']=content
        raw = json.dumps(data).encode()
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as bundle:
            bundle.writestr(v.MANIFEST, raw)
            for name, value in assets.items(): bundle.writestr(name, value)
        rows = []
        for name, raw in ((v.MANIFEST, raw), ('Fixture'+getattr(v, 'ZIP_SUFFIX', '-Vita-PKG-patches.zip'), archive.getvalue())):
            index = len(self.blobs) + 1
            url = 'https://api.github.com/repos/' + repo + '/releases/assets/' + str(index)
            self.blobs[url] = raw
            rows.append(dict(id=index, name=name, size=len(raw), digest='sha256:' + hashlib.sha256(raw).hexdigest(),
                             browser_download_url='https://github.com/' + repo + '/releases/download/v' + data['build'] + '/' + name))
        self.records.setdefault(repo, []).append(dict(tag_name='v' + data['build'], draft=False, prerelease=False, assets=rows))
        if data.get('package'):
            content = data.get('content_id', data['package'].get('content_id'))
            game = dict(game_id='fixture', name='Fixture', repo=repo,
                        package_ids=[dict(platform='PS Vita', kind='vita-content-id', id=content)])
            if game not in self.library['games']: self.library['games'].append(game)
            def indexed(row):
                return dict(id=row['id'], name=row['name'], bytes=row['size'], sha256=row['digest'][7:])
            self.library['vita_releases'].append(dict(game_id='fixture', repo=repo, version=data['build'],
                mode='pkg' if v.MANIFEST == 'VITA-PKG.json' else 'repatch', content_id=content,
                package={k:data['package'][k] for k in ('bytes','sha256')}, profile=indexed(rows[0]), archive=indexed(rows[1])))

    def repositories(self, cancel=None):
        raise AssertionError('Application must not enumerate repositories.')

    def json(self, url, cancel=None):
        self.calls.append(url)
        if url == lib.URL: return copy.deepcopy(self.library)
        raise AssertionError('Application must not search releases: ' + url)

    def open(self, url):
        self.calls.append(url)
        return io.BytesIO(self.blobs[url])


def pkg_bytes(content):
    header = bytearray(256)
    header[:4] = b'\x7fPKG'; header[192:196] = b'\x7fext'; header[231] = 2
    header[48:48+len(content)] = content.encode('ascii')
    return bytes(header)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data, self.assets = fixture()
        self.pkg = self.root / 'arbitrary-filename.pkg'
        self.pkg.write_bytes(pkg_bytes(self.data['content_id']))
        self.client = Releases(self.data, self.assets, self.pkg.read_bytes())
        # Resolver tests use the supplied current index; loader caching is tested separately.
        mock = patch.object(lib, 'load', side_effect=lambda client,*args: lib.validate(client.library))
        mock.start(); self.addCleanup(mock.stop)

    def run_download(self, cancel=None):
        return d.automatic_description(self.pkg, self.client, self.root/'cache', cancel)

    def test_generic_hardware_profile_uses_nested_content_id_and_keyword_context(self):
        from retro_trans import vita_repatch as hardware
        data = dict(schema=hardware.SCHEMA,title_id='PCSG00597',app_version='01.00',
            name='Hardware fixture',build='0.1.13',auth=None,minimum_app_version='0.5.13',
            package=dict(content_id=self.data['content_id']),files=[dict(path='cpk/Ange.cpk',
                source=identity(b'original'),target=identity(b'translated'),
                patch=dict(name='hardware.xdelta',**identity(b'delta')))])
        client = Releases(data,{'hardware.xdelta':b'delta'},self.pkg.read_bytes(),profile=hardware)
        cancel = threading.Event()
        with d.automatic_description(self.pkg,client,self.root/'hardware-cache',cancel,
                progress=lambda *args:None,profile=hardware) as (found,folder,assets):
            self.assertEqual(found['title_id'],'PCSG00597')
            self.assertEqual((folder/'hardware.xdelta').read_bytes(),b'delta')
            self.assertIsNone(assets)

    def test_unrelated_legacy_hardware_build_does_not_block_game_discovery(self):
        from retro_trans import vita_repatch as hardware
        data = dict(schema=hardware.SCHEMA,title_id='PCSG00264',app_version='01.00',
            name='Old hardware fixture',build='test18',auth=None,
            files=[dict(path='DATA/x.cpk',source=identity(b'a'),target=identity(b'b'),
                patch=dict(name='legacy.xdelta',**identity(b'delta')))])
        client = Releases(data,{'legacy.xdelta':b'delta'},self.pkg.read_bytes(),profile=hardware)
        client.records['retro-trans/fixture'][0]['tag_name']='v0.9.0'
        for item in client.records['retro-trans/fixture'][0]['assets']:
            item['browser_download_url']=item['browser_download_url'].replace('/vtest18/','/v0.9.0/')
        with self.assertRaisesRegex(PatchError,'No automatic Vita translation'), \
                d.automatic_description(self.pkg,client,self.root/'legacy-cache',profile=hardware):pass

    def test_detect_download_and_cache_two_titles(self):
        for title in ('PCSG00597', 'PCSE12345'):
            self.data, self.assets = fixture(title)
            self.pkg.write_bytes(pkg_bytes(self.data['content_id']))
            self.client = Releases(self.data, self.assets, self.pkg.read_bytes())
            with self.run_download() as (data, folder):
                self.assertEqual(data['title_id'], title)
                self.assertEqual((folder/'translation.xdelta').read_bytes(), self.assets['translation.xdelta'])
            self.assertFalse(folder.exists())
            self.client.calls.clear()
            with self.run_download(): pass
            self.assertFalse(any('/releases/assets/' in url for url in self.client.calls))

    def test_latest_matching_revision_not_just_latest_release(self):
        older = copy.deepcopy(self.data); older['build'] = '0.1.12'
        self.client.add('retro-trans/fixture', older, self.assets, self.pkg.read_bytes())
        newer = copy.deepcopy(self.data); newer['build'] = '0.1.14'
        self.client.add('retro-trans/fixture', newer, self.assets, self.pkg.read_bytes()[:-1]+b'X')
        with self.run_download() as (data, _): self.assertEqual(data['build'], '0.1.13')

    def test_automatic_download_accepts_larger_complete_profile(self):
        self.data['minimum_app_version'] = '0.5.17'
        self.data['source_files'].extend(dict(path='DATA/synthetic-fixture{:04d}.cpk'.format(i),
            **identity(b'original fixture')) for i in range(1000))
        self.client = Releases(self.data, self.assets, self.pkg.read_bytes())
        self.assertGreater(self.client.records['retro-trans/fixture'][0]['assets'][0]['size'], 128*1024)
        with self.run_download() as (data, _):
            self.assertEqual(len(data['source_files']), 1002)

    def test_wrong_pkg_revision_rejected_without_zip_download(self):
        self.pkg.write_bytes(self.pkg.read_bytes()[:-1] + b'X')
        with self.assertRaisesRegex(PatchError, 'revision'):
            with self.run_download(): pass
        self.assertEqual(len([url for url in self.client.calls if '/releases/assets/' in url]), 0)

    def test_ps3_rejected_before_network(self):
        self.pkg.write_bytes(pkg_bytes('JP0700-NPJB00689_00-SRWZ3RENDLGPKG00'))
        with self.assertRaisesRegex(PatchError, 'PS3'):
            with self.run_download(): pass
        self.assertEqual(self.client.calls, [])

    def test_missing_release_and_ambiguous_projects(self):
        self.client.library['vita_releases'].clear()
        with self.assertRaisesRegex(PatchError, 'No automatic'):
            with self.run_download(): pass
        self.client = Releases(self.data, self.assets, self.pkg.read_bytes())
        self.client.add('retro-trans/another-project', self.data, self.assets, self.pkg.read_bytes())
        with self.assertRaisesRegex(PatchError, 'Several projects'):
            with self.run_download(): pass

    def test_checksums_urls_and_zip_profile_must_agree(self):
        row = self.client.library['vita_releases'][0]['profile']
        row['name'] = '../profile'
        with self.assertRaises(PatchError):
            with self.run_download(): pass
        self.client = Releases(self.data, self.assets, self.pkg.read_bytes())
        row = self.client.library['vita_releases'][0]['archive']
        row['sha256'] = '0'*64
        with self.assertRaises(PatchError):
            with self.run_download(): pass

    def test_cancel_and_private_error_do_not_download_zip(self):
        cancel = threading.Event(); cancel.set()
        with self.assertRaises(Cancelled):
            with self.run_download(cancel): pass
        self.assertEqual(self.client.calls, [])

    def test_token_is_removed_on_redirect_and_disallowed_host_rejected(self):
        req = urllib.request.Request('https://api.github.com/repos/retro-trans/test/releases/assets/1',
                                     headers={'Authorization':'Bearer test-only-token'})
        handler = d.ApiRedirect()
        redirected = handler.redirect_request(req, None, 302, '', {}, 'https://release-assets.githubusercontent.com/test')
        self.assertIsNone(redirected.get_header('Authorization'))
        with self.assertRaises(PatchError):
            handler.redirect_request(req, None, 302, '', {}, 'https://example.org/test')

    def test_optional_signin_not_required_and_credentials_not_sent_to_other_repos(self):
        with patch.dict('os.environ', {}, clear=True), patch.object(d.shutil, 'which', return_value=None):
            client = d.VitaReleaseClient(cache=self.root/'cache')
        self.assertEqual(client._token, '')
        client._token = 'test-only-token'
        with patch.object(GitHubClient,'open',return_value=io.BytesIO(b'{}')) as original:
            client.open('https://api.github.com/repos/unrelated/project/releases/latest')
        original.assert_called_once()

    def test_existing_signin_used_for_exact_official_runtime_only(self):
        with patch.dict('os.environ', {}, clear=True), patch.object(d.shutil, 'which', return_value=None):
            client = d.VitaReleaseClient(cache=self.root/'cache')
        client._token = 'test-only-token'
        opener = Mock(); opener.open.return_value.status = 200
        with patch.object(d.urllib.request, 'build_opener', return_value=opener):
            client.open('https://api.github.com/repos/Vita3K/Vita3K/releases/tags/continuous')
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_header('Authorization'), 'Bearer test-only-token')
        redirected = d.ApiRedirect().redirect_request(request, None, 302, '', {},
            'https://release-assets.githubusercontent.com/runtime')
        self.assertIsNone(redirected.get_header('Authorization'))
        error = urllib.error.HTTPError(request.full_url, 429, 'limited', {'Retry-After':'60'}, None)
        opener.open.side_effect = error
        with patch.object(d.urllib.request, 'build_opener', return_value=opener), self.assertRaises(GitHubRateLimit):
            client.open(request.full_url)

    def test_discovery_cache_reuses_metadata_expires_and_separates_signins(self):
        url = 'https://api.github.com/repos/retro-trans/fixture/releases?per_page=10'
        rows = [{'tag_name':'v0.1.13','assets':[]}]
        def response(*args):return io.BytesIO(json.dumps(rows).encode())
        with patch.dict('os.environ', {}, clear=True), patch.object(d.shutil, 'which', return_value=None), \
                patch.object(d.VitaReleaseClient, 'open', side_effect=response) as network, \
                patch.object(d.time, 'time', return_value=1000) as now:
            first = d.VitaReleaseClient(cache=self.root/'cache')
            self.assertEqual(first.json(url), rows)
            second = d.VitaReleaseClient(cache=self.root/'cache')
            self.assertEqual(second.json(url), rows)
            self.assertEqual(network.call_count, 1)
            now.return_value = 4601
            self.assertEqual(second.json(url), rows)
            self.assertEqual(network.call_count, 2)
            second._token = 'test-only-token'
            self.assertEqual(second.json(url), rows)
            self.assertEqual(network.call_count, 3)
            cancel = threading.Event(); cancel.set()
            with self.assertRaises(Cancelled):second.json(url, cancel)
            self.assertEqual(network.call_count, 3)
            for path in second.metadata_cache.glob('*.json'):
                self.assertNotIn('test-only-token', path.read_text(encoding='utf-8'))
                path.write_text('not json', encoding='utf-8')
            self.assertEqual(second.json(url), rows)
            self.assertEqual(network.call_count, 4)

    def test_discovery_errors_are_not_cached_or_retried(self):
        with patch.dict('os.environ', {}, clear=True), patch.object(d.shutil, 'which', return_value=None):
            client = d.VitaReleaseClient(cache=self.root/'cache')
        with patch.object(client, 'open', side_effect=GitHubRateLimit()) as network, self.assertRaises(GitHubRateLimit):
            client.json('https://api.github.com/orgs/retro-trans/repos?per_page=100')
        network.assert_called_once()
        self.assertFalse(list(client.metadata_cache.glob('*.json')))
