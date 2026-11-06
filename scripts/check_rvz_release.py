"""Verify a real RVZ through the built EXE and an exact public catalog output.

Dry-run by default. All generated full disc files are private and removed after
verification; originals, emulator profiles and game saves are never changed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from retro_trans import rvz
from retro_trans.catalog import load_catalog,recognize
from retro_trans.core import sha256_file

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--executable',type=Path,required=True)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--game-id',required=True)
    p.add_argument('--expected-version',required=True)
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--write',action='store_true')
    a=p.parse_args()
    print(json.dumps(dict(executable=str(a.executable.resolve()),source=str(a.source.resolve()),game_id=a.game_id,
        target=a.expected_version,format='rvz',temporary_discs_removed=True,report=str(a.report),write=a.write),indent=2),flush=True)
    if not a.write:return
    assert not a.report.exists()
    catalog=load_catalog()
    candidates=[n for n in catalog.nodes.values() if n.id[0]==a.game_id and n.version==a.expected_version]
    assert len(candidates)==1
    expected=candidates[0]
    info=rvz.inspect_rvz(a.source)
    source_hash=sha256_file(a.source)
    owned=(ROOT/'.integration/rvz-real-check').resolve()
    assert owned.is_relative_to((ROOT/'.integration').resolve())
    owned.mkdir(parents=True,exist_ok=True)
    started=time.monotonic()
    with tempfile.TemporaryDirectory(dir=str(owned)) as folder:
        stage=Path(folder);output=stage/'English.rvz'
        env=os.environ.copy();env['RETRO_TRANS_DATA_DIR']=str(stage/'app-data')
        assert not (stage/'app-data').exists()
        result=subprocess.run([str(a.executable.resolve()),'--automatic-binary',str(a.source.resolve()),
            '--output',str(output),'--format','rvz','--target',a.expected_version],
            env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=900)
        assert result.returncode==0,('Packaged Automatic failed',result.returncode)
        assert output.is_file()
        print('Packaged Automatic produced RVZ; independently checking complete ISO bytes.',flush=True)
        packed_bytes=output.stat().st_size;packed_hash=sha256_file(output)
        binary=rvz.extract(output,stage)
        target_hash=sha256_file(binary)
        assert binary.stat().st_size==expected.size and target_hash==expected.hashes['sha256']
        found=[n for n in recognize(binary,catalog) if n.id==expected.id]
        assert len(found)==1 and not catalog.plan(found[0]).edges
        before=packed_hash
        # The packaged entry point must reject overwrites without changing bytes.
        rejected=subprocess.run([str(a.executable.resolve()),'--automatic-binary',str(a.source.resolve()),
            '--output',str(output),'--format','rvz','--target',a.expected_version],
            env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=60)
        assert rejected.returncode!=0 and sha256_file(output)==before
        assert sha256_file(a.source)==source_hash
        report=dict(app_version='0.5.21',game_id=a.game_id,target_version=a.expected_version,
            executable_sha256=sha256_file(a.executable),source_rvz_sha256=source_hash,source_iso_bytes=info.size,
            target_iso_sha256=target_hash,target_iso_bytes=binary.stat().st_size,
            target_rvz_sha256=packed_hash,target_rvz_bytes=packed_bytes,
            packaged_automatic_real_rvz_input=True,live_patch_download=True,isolated_empty_app_cache=True,
            rvz_output_independent_full_roundtrip=True,recognized_as_current=True,
            source_preserved=True,existing_output_refused=True,temporary_discs_removed=True,
            game_emulator_launched=False,game_audio_used=False,hardware_tested=False,
            seconds=round(time.monotonic()-started,2))
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2),flush=True)

if __name__=='__main__':main()
