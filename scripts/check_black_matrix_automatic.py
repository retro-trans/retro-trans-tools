"""Real original-disc Automatic DCP checks; all game content remains local."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from retro_trans.catalog import Catalog, assert_immutable, recognize
from retro_trans.core import sha256_file
from retro_trans.dcp_automatic import apply, descriptor_tracks


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-root',required=True);parser.add_argument('--work',required=True)
    parser.add_argument('--executable',type=Path)
    parser.add_argument('--format',choices=('GDI','CUE/BIN'),default='GDI')
    args=parser.parse_args();game=Path(args.game_root).resolve();work=Path(args.work).resolve()
    work.mkdir(parents=True,exist_ok=True)
    raw=(game/'build/automatic-dcp-0.5.20/ready/DCP-AUTOMATIC.json').read_bytes()
    manifest=json.loads(raw)
    prefix='https://github.com/retro-trans/Black-Matrix-AD/releases/download/v0.9.0/'
    data=json.loads((Path(__file__).resolve().parents[1]/'retro_trans/resources/catalog.json').read_text(encoding='utf-8'))
    old=Catalog(data)
    record=dict(repo='retro-trans/Black-Matrix-AD',tag='v0.9.0',manifest=manifest,prerelease=True,
        manifest_sha256=hashlib.sha256(raw).hexdigest(),assets={p['patch']:prefix+p['patch'] for p in manifest['patches']})
    data['dcp_releases']=[record]
    catalog=Catalog(data);assert_immutable(old,catalog)
    (work/'candidate-catalog.json').write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    profile=work/'isolated-profile';(profile/'cache').mkdir(parents=True,exist_ok=True)
    (profile/'cache/catalog.json').write_text(json.dumps(data),encoding='utf-8')
    temporary=work/'temp';temporary.mkdir(exist_ok=True)
    previous=0
    def progress(message,fraction=None):
        nonlocal previous
        now=time.monotonic()
        if now-previous>15:
            print(message,flush=True);previous=now
    for disc in (1,2):
        source=game/f'Black-Matrix Advanced (Japan) (Disc {disc}).cue'
        tracks=descriptor_tracks(source)
        before={str(p):sha256_file(p) for p in [source]+tracks}
        nodes=recognize(source,catalog,progress=progress)
        assert len(nodes)==1 and nodes[0].profiles[0]['row']['metadata']['disc']==disc
        plan=catalog.plan(nodes[0]);assert plan.version=='0.9.0'
        output=work/f'disc{disc}-{args.format.replace("/","-").lower()}'
        if output.exists():raise ValueError('Preserve prior Automatic output: '+str(output))
        print('Disc',disc,'Automatic recognized:',nodes[0].label,flush=True)
        if args.executable:
            env=dict(os.environ,RETRO_TRANS_DATA_DIR=str(profile),TEMP=str(temporary),TMP=str(temporary),TMPDIR=str(temporary))
            run=subprocess.run([str(args.executable.resolve()),'--automatic',str(source),'--output',str(output),
                '--format',args.format],env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=1800)
            assert run.returncode==0,('Packaged Automatic failed',disc,run.returncode)
            proof=json.loads((output/'DCP-VALIDATION.json').read_text(encoding='utf-8'))
        else:
            proof=apply(plan,output,format=args.format,cache=profile/'cache',progress=progress)
        metadata=plan.profile['row']['metadata']
        assert proof['release_metadata_verified'] and proof['audio_tracks_preserved']
        assert proof['verified_game_tree_sha256']==metadata['target_tree_sha256']
        assert proof['bootsector_invariant_sha256']==metadata['bootsector_invariant_sha256']
        assert before=={str(p):sha256_file(p) for p in [source]+tracks}
        receipt=dict(disc=disc,format=args.format,originals_unchanged=True,automatic_recognition=True,
            automatic_download=True,proof=proof,manifest_sha256=hashlib.sha256(raw).hexdigest(),
            executable_sha256=sha256_file(args.executable) if args.executable else None)
        (work/f'disc{disc}-verification.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
        print('Disc',disc,'Automatic output verified; originals unchanged.',flush=True)


if __name__=='__main__':main()
