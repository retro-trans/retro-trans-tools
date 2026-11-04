import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from retro_trans import game_library as lib, game_library_builder as builder, vita_downloads
from retro_trans.core import Cancelled, PatchError
from retro_trans.release import build_release
from test_vita_downloads import Releases, fixture, pkg_bytes


class LibraryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.data, self.assets = fixture()
        self.pkg = self.root/'source.pkg'
        self.pkg.write_bytes(pkg_bytes(self.data['content_id']))
        self.client = Releases(self.data, self.assets, self.pkg.read_bytes())
        self.path = self.root/'bundled.json'
        self.path.write_text(json.dumps(self.client.library), encoding='utf-8')
        mocked = patch.object(lib, 'PATH', self.path)
        mocked.start(); self.addCleanup(mocked.stop)

    def load(self, cancel=None):
        return lib.load(self.client, self.root/'cache', cancel)

    def test_bundled_library_registers_every_reviewed_catalog_project_and_platform(self):
        library = lib.read(lib.RESOURCE_DIR/'game-library.json')
        catalog = json.loads((lib.RESOURCE_DIR/'catalog.json').read_text(encoding='utf-8'))
        games = {(g['repo'],g['game_id']):g for g in library['games']}
        for entry in catalog['releases'] + catalog.get('dcp_releases',[]):
            manifest = entry['manifest']
            with self.subTest(repo=entry['repo'],tag=entry['tag']):
                game = games[(entry['repo'],manifest['game_id'])]
                platforms = {p.get('platform',manifest['platform']) for p in manifest['patches']}
                self.assertTrue(platforms <= {p['platform'] for p in game['package_ids']})

    def test_constant_requests_despite_unrelated_projects_and_releases(self):
        # More games and old releases do not produce any extra discovery requests.
        for n in range(200):
            self.client.library['games'].append(dict(game_id='other-'+str(n), name='Other',
                repo='retro-trans/other-'+str(n), package_ids=[dict(platform='PC',kind='steam-app-id',id=str(n+1))]))
        for n in range(25):
            old = copy.deepcopy(self.data); old['build'] = '0.0.'+str(n)
            self.client.add('retro-trans/fixture', old, self.assets, self.pkg.read_bytes())
        with vita_downloads.automatic_description(self.pkg,self.client,self.root/'cache') as (data, folder):
            self.assertEqual(data['build'], '0.1.13')
            self.assertTrue((folder/'translation.xdelta').is_file())
        self.assertEqual(len(self.client.calls), 3)  # one raw JSON + selected profile + selected ZIP
        self.assertEqual(self.client.calls[0], lib.URL)
        self.assertTrue(all('/releases/assets/' in url for url in self.client.calls[1:]))
        self.client.calls.clear()
        with vita_downloads.automatic_description(self.pkg,self.client,self.root/'cache'): pass
        self.assertEqual(self.client.calls, [])

    def test_unknown_id_and_wrong_binary_never_fetch_any_patch(self):
        self.pkg.write_bytes(pkg_bytes('JP0700-PCSE99999_00-'+'A'*16))
        with self.assertRaisesRegex(PatchError,'No automatic'), vita_downloads.automatic_description(
                self.pkg,self.client,self.root/'cache'): pass
        self.assertEqual(self.client.calls, [lib.URL])
        self.pkg.write_bytes(pkg_bytes(self.data['content_id'])[:-1]+b'X')
        self.client.calls.clear()
        with self.assertRaisesRegex(PatchError,'revision'), vita_downloads.automatic_description(
                self.pkg,self.client,self.root/'cache'): pass
        self.assertEqual(self.client.calls, [])

    def test_cache_hour_expiry_offline_and_invalid_update_preserve_last_valid(self):
        with patch.object(lib.time,'time',return_value=1000) as clock:
            saved = self.load()
            self.assertEqual(self.load(),saved)
            self.assertEqual(self.client.calls, [lib.URL])
            clock.return_value = 4601
            self.client.library['schema_version'] = 999
            self.assertEqual(self.load(),saved)
            self.assertEqual(self.load(),saved)
            self.assertEqual(self.client.calls, [lib.URL,lib.URL])
            clock.return_value = 8202
            with patch.object(self.client,'json',side_effect=PatchError('offline')) as network:
                self.assertEqual(self.load(),saved)
                self.assertEqual(self.load(),saved)
                network.assert_called_once()

    def test_invalid_local_cache_falls_back_and_cancel_never_cached(self):
        cache = self.root/'cache'; cache.mkdir()
        (cache/'game-library-cache.json').write_text('invalid', encoding='utf-8')
        self.assertEqual(self.load(),self.client.library)
        before = (cache/'game-library-cache.json').read_bytes()
        cancel = threading.Event(); cancel.set()
        with self.assertRaises(Cancelled):self.load(cancel)
        self.assertEqual((cache/'game-library-cache.json').read_bytes(),before)
        with patch.object(lib.time,'time',return_value=10**12), \
                patch.object(self.client,'json',side_effect=Cancelled()), self.assertRaises(Cancelled):
            self.load()
        self.assertEqual((cache/'game-library-cache.json').read_bytes(),before)

    def test_private_library_is_local_and_not_written_to_public_cache(self):
        private = copy.deepcopy(self.client.library)
        private['games'][0]['repo']='retro-trans/private-fixture'
        private['vita_releases'][0]['repo']='retro-trans/private-fixture'
        cache=self.root/'cache'; cache.mkdir()
        (cache/'game-library.private.json').write_text(json.dumps(private), encoding='utf-8')
        self.assertEqual(len(self.load()['vita_releases']),2)
        self.assertNotIn('private-fixture',(cache/'game-library-cache.json').read_text(encoding='utf-8'))

    def test_changed_release_identity_is_rejected_and_not_cached(self):
        old = self.load()
        self.client.library['vita_releases'][0]['archive']['sha256']='0'*64
        with self.assertRaisesRegex(PatchError,'identity changed'):lib.merge(old,self.client.library)
        with patch.object(lib.time,'time',return_value=10**12):self.assertEqual(self.load(),old)

    def test_manifest_and_index_must_agree_even_with_valid_download_hash(self):
        self.client.library['vita_releases'][0]['version']='0.1.14'
        self.path.write_text(json.dumps(self.client.library), encoding='utf-8')
        with self.assertRaisesRegex(PatchError,'differs from the game library'), \
                vita_downloads.automatic_description(self.pkg,self.client,self.root/'cache'):pass
        self.assertEqual(len(self.client.calls),2)  # no ZIP download

    def test_cross_platform_registration_and_build_gate(self):
        ids=[dict(platform=p,kind=k,id=i) for p,k,i in
             [('PS2','disc-id','SLPS-TEST'),('Dreamcast','product-id','HDR-TEST'),('PC','steam-app-id','12345')]]
        library=dict(schema_version=1,games=[dict(game_id='sample',name='Sample',repo='retro-trans/sample',package_ids=ids)],vita_releases=[])
        manifest=dict(game_id='sample',platform='PS2',package_ids=ids,
                      patches=[dict(platform='PS2'),dict(platform='Dreamcast'),dict(platform='PC')])
        lib.validate_registration(manifest,'retro-trans/sample',library)
        for change in ('missing','wrong','platform','repo'):
            bad=copy.deepcopy(manifest); repo='retro-trans/sample'
            if change=='missing':del bad['package_ids']
            if change=='wrong':bad['package_ids'][0]['id']='wrong'
            if change=='platform':bad['package_ids'].pop()
            if change=='repo':repo='retro-trans/wrong'
            with self.assertRaises(PatchError):lib.validate_registration(bad,repo,library)
        # Registration fails before reading large source files or creating an output.
        config=self.root/'config.json'; config.write_text(json.dumps(dict(game_id='sample',platform='PS2')),encoding='utf-8')
        with self.assertRaisesRegex(PatchError,'package_ids'):build_release(config,self.root/'out',library=library)
        self.assertFalse((self.root/'out').exists())

    def test_invalid_and_duplicate_entries(self):
        for failure in ('unregistered','duplicate','asset','platform','hash','unknown-field'):
            bad=copy.deepcopy(self.client.library)
            if failure=='unregistered':bad['games'][0]['package_ids'][0]['id']='JP0700-PCSE99999_00-'+'A'*16
            if failure=='duplicate':bad['vita_releases'].append(copy.deepcopy(bad['vita_releases'][0]))
            if failure=='asset':bad['vita_releases'][0]['profile']['id']=True
            if failure=='platform':bad['games'][0]['package_ids'][0]['platform']='PC'
            if failure=='hash':bad['vita_releases'][0]['package']['sha256']='bad'
            if failure=='unknown-field':bad['games'][0]['license']='forbidden'
            with self.subTest(failure=failure),self.assertRaises(PatchError):lib.validate(bad)

    def test_builder_verified_metadata_and_public_visibility(self):
        client=self.client
        def json_response(url):
            self.assertEqual(url,'https://api.github.com/repos/retro-trans/fixture')
            return dict(private=False,full_name='retro-trans/fixture')
        with patch.object(client,'json',side_effect=json_response), \
                patch.object(client,'releases',return_value=client.records['retro-trans/fixture']):
            self.assertEqual(builder.refresh(client.library,client,self.root/'cache'),lib.merge(client.library,client.library))
        with patch.object(client,'json',return_value=dict(private=True,full_name='retro-trans/fixture')), \
                self.assertRaisesRegex(PatchError,'Private releases'):builder.refresh(client.library,client,self.root/'cache')

    def test_publication_gate_checks_vita_content_and_repo_without_network(self):
        raw = self.client.blobs[next(url for url in self.client.blobs if url.endswith('/1'))]
        manifest = self.root/'VITA-PKG.json'; manifest.write_bytes(raw)
        builder.validate_release(manifest,'retro-trans/fixture',self.client.library)
        with self.assertRaisesRegex(PatchError,'Register the Vita content ID'):
            builder.validate_release(manifest,'retro-trans/wrong',self.client.library)
        self.assertEqual(self.client.calls,[])

    def test_library_keeps_existing_hardware_profile_size_limit(self):
        row=copy.deepcopy(self.client.library['vita_releases'][0]['profile'])
        row.update(name='VITA-REPATCH.json',bytes=300000)
        self.assertEqual(lib.asset(row,'retro-trans/fixture','repatch').size,300000)
        row['name']='VITA-PKG.json'
        with self.assertRaises(PatchError):lib.asset(row,'retro-trans/fixture','pkg')

    def test_builder_rejects_bad_digest_url_and_unregistered_id(self):
        release=copy.deepcopy(self.client.records['retro-trans/fixture'][0])
        for problem in ('digest','url','unregistered','missing-zip'):
            row=copy.deepcopy(release); games=self.client.library['games']
            if problem=='digest':row['assets'][0]['digest']='sha256:'+'0'*64
            if problem=='url':row['assets'][0]['browser_download_url']='https://example.com/patch'
            if problem=='unregistered':games=[]
            if problem=='missing-zip':row['assets'].pop()
            with self.subTest(problem=problem),self.assertRaises(PatchError):
                builder.release_entries('retro-trans/fixture',row,self.client,self.root/problem,games)

    def test_catalog_gate_preserves_historical_releases_and_rejects_new_unregistered(self):
        from retro_trans.catalog_builder import build_catalog
        from test_catalog_builder import ReleaseClient
        client=ReleaseClient(); empty=dict(schema_version=1,releases=[])
        old=build_catalog(empty,client)
        library=dict(schema_version=1,games=[],vita_releases=[])
        self.assertEqual(build_catalog(old,client,library=library),old)
        with self.assertRaisesRegex(PatchError,'package_ids'):build_catalog(empty,client,library=library)
        rejects=[]
        self.assertEqual(build_catalog(empty,client,library=library,rejections=rejects),empty)
        self.assertEqual(len(rejects),1)
