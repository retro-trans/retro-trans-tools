"""Stage metadata only for the approved public Black/Matrix AD DCPs.

Original tracks remain local/read-only; only byte counts and hashes are emitted.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from retro_trans.dcp_automatic import descriptor_tracks, validate_manifest
from retro_trans.dcp import inspect_patch
from retro_trans.core import sha256_file


def prepare(game,output):
    game=Path(game).resolve();output=Path(output).resolve()
    if output.exists():raise ValueError('Preserve existing metadata preparation')
    manifest=json.loads((game/'build/dcp-v0.9.0/ready/DCP-MANIFEST-v0.9.0.json').read_text())
    original=json.loads((game/'build/retro-trans-v0.9.0/ready/BUILD-MANIFEST.json').read_text())
    result=dict(schema_version=1,format='DCP',platform='Dreamcast',game_id=manifest['game_id'],
        game_name=manifest['game_name'],language='en',version='0.9.0',minimum_app_version='0.5.20',
        allow_prerelease=True,source_commit='9ef9fa17922d3d8c646715cb49d35fb601ebd267',patches=[])
    for disc in (1,2):
        row=next(p for p in manifest['patches'] if p['disc']==disc)
        package=game/'build/dcp-v0.9.0/ready'/row['patch']
        assert sha256_file(package)==row['sha256'] and package.stat().st_size==row['bytes']
        assert inspect_patch(package)['metadata']==row['metadata']
        tracks=descriptor_tracks(game/f'Black-Matrix Advanced (Japan) (Disc {disc}).cue')
        assert len(tracks)==3
        fingerprints=[dict(bytes=p.stat().st_size,sha256=sha256_file(p)) for p in tracks]
        source=next(p for p in original['patches'] if p['edition']==f'jp-disc{disc}-track3-native')
        assert fingerprints[2]==dict(bytes=source['source_bytes'],sha256=source['source_sha256'])
        result['patches'].append(dict(patch=row['patch'],bytes=row['bytes'],sha256=row['sha256'],
            edition=f'jp-disc{disc}-native',metadata=row['metadata'],source_tracks=fingerprints))
    validate_manifest(result)
    raw=(json.dumps(result,indent=2)+'\n').encode()
    output.mkdir(parents=True)
    (output/'DCP-AUTOMATIC.json').write_bytes(raw)
    (output/'SHA256SUMS-DCP-AUTOMATIC-v0.9.0.txt').write_text(hashlib.sha256(raw).hexdigest()+'  DCP-AUTOMATIC.json\n',encoding='utf-8')
    print('Prepared two metadata-only assets; original tracks and DCP packages unchanged.',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-root',required=True);parser.add_argument('--out',required=True)
    args=parser.parse_args();prepare(args.game_root,args.out)
