import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import zipfile

from retro_trans import dcp_automatic as auto
from retro_trans.catalog import Catalog, recognize, scan_root, assert_immutable, apply_plan
from retro_trans.catalog_builder import build_catalog
from retro_trans.core import Cancelled, GitHubClient, PatchError


def digest(raw): return hashlib.sha256(raw).hexdigest()


def fixture():
    tracks = [b'original data track',b'audio samples',b'original high density game']
    metadata = dict(retro_trans_dcp=1,game_id='test-dreamcast',game_name='Test Dreamcast',
        disc=1,version='0.9.0',source_version='original',target_version='0.9.0',
        source_tree_sha256='1'*64,target_tree_sha256='2'*64,bootsector_invariant_sha256='3'*64)
    memory = io.BytesIO()
    with zipfile.ZipFile(memory,'w') as z:
        z.writestr('GAME.DAT.xdelta',b'\xd6\xc3\xc4test')
        z.comment=json.dumps(metadata).encode()
    raw=memory.getvalue()
    manifest=dict(schema_version=1,format='DCP',platform='Dreamcast',game_id='test-dreamcast',
        game_name='Test Dreamcast',language='en',version='0.9.0',source_commit='a'*40,
        minimum_app_version='0.5.20',allow_prerelease=True,patches=[dict(patch='Disc1.dcp',
        edition='jp-disc1-native',bytes=len(raw),sha256=digest(raw),metadata=metadata,
        source_tracks=[dict(bytes=len(t),sha256=digest(t)) for t in tracks])])
    prefix='https://github.com/retro-trans/dcp-game/releases/download/v0.9.0/'
    files={'DCP-AUTOMATIC.json':json.dumps(manifest).encode(),'Disc1.dcp':raw}
    release=dict(tag_name='v0.9.0',prerelease=True,draft=False,assets=[dict(name=n,size=len(v),
        digest='sha256:'+digest(v),browser_download_url=prefix+n) for n,v in files.items()])
    return tracks,manifest,files,release,prefix


class Client(GitHubClient):
    def __init__(self):
        self.tracks,self.manifest,self.files,self.release,self.prefix=fixture()
    def open(self,url): return io.BytesIO(self.files[url[len(self.prefix):]])
    def repositories(self): return ['retro-trans/dcp-game']
    def releases(self,repo,**kwargs): return [self.release]


class AutomaticDcpTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.client=Client()
        self.data=build_catalog(dict(schema_version=1,releases=[]),self.client)
        self.catalog=Catalog(self.data)
        for i,t in enumerate(self.client.tracks): (self.root/f'renamed{i}.bin').write_bytes(t)
        self.cue=self.root/'arbitrary-name.cue'
        self.cue.write_text(''.join(f'FILE "renamed{i}.bin" BINARY\n TRACK {i+1:02} MODE1/2352\n INDEX 01 00:00:00\n' for i in range(3)))

    def test_imports_experimental_dcp_independently_and_refreshes_immutably(self):
        self.assertEqual(self.data['releases'],[])
        self.assertEqual(len(self.data['dcp_releases']),1)
        self.assertEqual(build_catalog(self.data,self.client),self.data)
        self.assertEqual(len(self.catalog.dcp_profiles),1)
        self.assertEqual(len(self.catalog.edges),0)
        changed=copy.deepcopy(self.data);changed['dcp_releases'][0]['manifest']['patches'][0]['metadata']['target_tree_sha256']='4'*64
        with self.assertRaises(PatchError): assert_immutable(self.catalog,Catalog(changed))
        with self.assertRaises(PatchError): assert_immutable(self.catalog,Catalog(dict(schema_version=1,releases=[])))

    def test_browse_scan_renamed_cue_and_gdi(self):
        nodes=recognize(self.cue,self.catalog)
        self.assertEqual(len(nodes),1)
        self.assertIn('experimental DCP',nodes[0].label)
        self.assertEqual(self.catalog.plan(nodes[0]).version,'0.9.0')
        self.assertEqual([n.version for n in self.catalog.versions(nodes[0])],['0.9.0'])
        self.assertEqual(len(scan_root(self.root,self.catalog)),1)
        gdi=self.root/'game.gdi'
        gdi.write_text('3\n'+''.join(f'{i+1} {i*100} 4 2352 "renamed{i}.bin" 0\n' for i in range(3)))
        self.assertEqual(len(recognize(gdi,self.catalog)),1)
        with self.assertRaises(PatchError):self.catalog.plan(nodes[0],'0.8.0')

    def test_new_release_cannot_redefine_a_known_original(self):
        data=copy.deepcopy(self.data);new=copy.deepcopy(data['dcp_releases'][0])
        new['tag']='v0.9.1';new['manifest']['version']='0.9.1'
        row=new['manifest']['patches'][0]
        row['metadata'].update(version='0.9.1',target_version='0.9.1')
        new['assets']['Disc1.dcp']=new['assets']['Disc1.dcp'].replace('/v0.9.0/','/v0.9.1/')
        data['dcp_releases'].append(new)
        Catalog(data)
        row['source_tracks'][0]['sha256']='4'*64
        with self.assertRaisesRegex(PatchError,'source identity'):Catalog(data)

    def test_bad_disc_missing_audio_and_modified_inputs_never_download(self):
        node=recognize(self.cue,self.catalog)[0]
        plan=self.catalog.plan(node)
        (self.root/'renamed1.bin').write_bytes(b'wrong samples')
        self.assertEqual(recognize(self.cue,self.catalog),[])
        client=Mock()
        with self.assertRaises(PatchError):auto.apply(plan,self.root/'out',client=client)
        client.download.assert_not_called()
        (self.root/'renamed1.bin').unlink()
        with self.assertRaisesRegex(PatchError,'Missing'):recognize(self.cue,self.catalog)

    def test_download_and_apply_verify_native_metadata_and_preserve_inputs(self):
        plan=self.catalog.plan(recognize(self.cue,self.catalog)[0])
        with patch.object(auto.dcp,'apply',return_value={'output':str(self.root/'out')}) as apply:
            result=apply_plan(self.cue,self.root/'out',plan,self.catalog,self.client,self.root/'cache')
        self.assertEqual(result['output'],str(self.root/'out'))
        self.assertEqual(apply.call_args.kwargs['format'],'GDI')
        self.assertEqual([p.read_bytes() for p in auto.descriptor_tracks(self.cue)],self.client.tracks)
        self.assertEqual(self.catalog.plan(plan.source,'Next version only').version,'0.9.0')

    def test_source_mismatch_existing_output_and_cancellation_are_safe(self):
        node=recognize(self.cue,self.catalog)[0];plan=self.catalog.plan(node);client=Mock()
        (self.root/'out').mkdir()
        with self.assertRaises(PatchError):auto.apply(plan,self.root/'out',client=client)
        client.download.assert_not_called()
        cancel=threading.Event();cancel.set()
        with self.assertRaises(Cancelled):recognize(self.cue,self.catalog,cancel)
        with self.assertRaises(PatchError):apply_plan(self.root/'wrong.cue',self.root/'next',plan,self.catalog,client)
        self.assertFalse((self.root/'next').exists())

    def test_unsafe_descriptors_and_nonzero_gdi_offsets_are_not_accepted(self):
        self.cue.write_text('FILE "../outside.bin" BINARY\n'*3)
        with self.assertRaises(PatchError):auto.descriptor_tracks(self.cue)
        gdi=self.root/'game.gdi';gdi.write_text('3\n1 0 4 2352 "renamed0.bin" 2\n2 1 0 2352 "renamed1.bin" 0\n3 2 4 2352 "renamed2.bin" 0\n')
        self.assertEqual(recognize(gdi,self.catalog),[])

    def test_bad_or_replaced_metadata_and_undeclared_packages_fail_import(self):
        for kind in ('digest','content','extra','missing','prerelease'):
            client=Client()
            if kind=='digest':client.release['assets'][1]['digest']='sha256:'+'0'*64
            elif kind=='content':client.files['Disc1.dcp']=b'corrupted'
            elif kind=='extra':client.release['assets'].append(dict(name='Disc2.dcp'))
            elif kind=='missing':client.release['assets']=[a for a in client.release['assets'] if a['name']!='DCP-AUTOMATIC.json']
            else:
                client.manifest['allow_prerelease']=False
                raw=json.dumps(client.manifest).encode();client.files['DCP-AUTOMATIC.json']=raw
                client.release['assets'][0].update(size=len(raw),digest='sha256:'+digest(raw))
            with self.subTest(kind=kind),self.assertRaises((PatchError,KeyError)):
                build_catalog(self.data,client)

    def test_manifest_rejects_bad_version_hashes_duplicates_and_paths(self):
        for key,value in (('minimum_app_version','0.5.19'),('source_commit','bad'),('format','xdelta')):
            m=copy.deepcopy(self.client.manifest);m[key]=value
            with self.assertRaises(PatchError):auto.validate_manifest(m)
        for change in ('duplicate','path','identity','hash'):
            m=copy.deepcopy(self.client.manifest);p=m['patches'][0]
            if change=='duplicate':m['patches'].append(copy.deepcopy(p))
            elif change=='path':p['edition']='../evil'
            elif change=='identity':p['metadata']['disc']=True
            else:p['source_tracks'][0]['sha256']='bad'
            with self.assertRaises(PatchError):auto.validate_manifest(m)


if __name__=='__main__':unittest.main()
