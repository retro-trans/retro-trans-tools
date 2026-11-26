"""Synthetic binaries and route expectations from the existing desktop engine."""
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from retro_trans.catalog import Catalog
from retro_trans.core import engine_context
from test_catalog import record, DATA
from test_solutions import grouped_record


def main():
    resources = ROOT / 'android/patch-core/src/test/resources'
    assets = ROOT / 'android/app/src/androidTest/assets'
    resources.mkdir(parents=True, exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)
    raw = json.loads((ROOT / 'retro_trans/resources/catalog.json').read_text('utf-8'))
    (resources / 'catalog.json').write_text(json.dumps(raw), 'utf-8')
    catalog = Catalog(raw)
    expected = []
    for node in catalog.nodes.values():
        if node.id not in catalog.available_ids:
            continue
        for target in ['Latest', 'Next version only'] + [n.version for n in catalog.versions(node)]:
            row = {'source': list(node.id), 'choice': target}
            try:
                plan = catalog.plan(node, target)
                row.update(target=list(plan.target.id), latest=list(plan.latest.id),
                           reachable=plan.latest_reachable, edges=[e.asset.url for e in plan.edges])
            except Exception:
                row['error'] = True
            expected.append(row)
    (resources / 'routes.json').write_text(json.dumps(expected), 'utf-8')
    rng=random.Random(200)
    source = rng.randbytes(3*1024*1024)
    modified = source[:1500000] + b'Translated game text! '*4000 + source[1560000:]
    (assets/'source.bin').write_bytes(source)
    (assets/'modified.bin').write_bytes(modified)
    final=b'FINAL VERSION'+modified[13:]
    second=rng.randbytes(32768)
    second_target=second[:1000]+b'English text'+second[1012:]
    for name,content in [('final.bin',final),('second.bin',second),('second-target.bin',second_target)]:
        (assets/name).write_bytes(content)
    with engine_context() as engine:
        for mode in ['none','djw','lzma']:
            subprocess.run([str(engine),'-f','-e','-D','-A','-S',mode,'-s',str(assets/'source.bin'),str(assets/'modified.bin'),str(assets/(mode+'.xdelta'))],check=True,capture_output=True)
        for source_name,target_name,name in [('modified.bin','final.bin','incremental.xdelta'),('second.bin','second-target.bin','second.xdelta')]:
            subprocess.run([str(engine),'-f','-e','-D','-A','-s',str(assets/source_name),str(assets/target_name),str(assets/name)],check=True,capture_output=True)
    cue=b'FILE "track01.bin" BINARY\n  TRACK 01 MODE1/2352\n    INDEX 01 00:00:00\nFILE "track02.bin" BINARY\n  TRACK 02 AUDIO\n    INDEX 01 00:00:00\n'
    (assets/'disc.cue').write_bytes(cue)
    def patch(name,edition,source_version,source_name,target_name):
        row={'patch':name,'edition':edition,'language':'English','source_version':source_version,'source_format':'bin','target_format':'bin'}
        for prefix,filename in [('source',source_name),('target',target_name),('patch',name)]:
            data=(assets/filename).read_bytes();row[prefix+'_bytes']=len(data);row[prefix+'_sha256']=hashlib.sha256(data).hexdigest()
        return row
    records=[]
    for v,patches in [('1.0',[patch('lzma.xdelta','track01','original','source.bin','modified.bin'),patch('second.xdelta','track02','original','second.bin','second-target.bin')]),('1.1',[patch('incremental.xdelta','track01','1.0','modified.bin','final.bin'),patch('second.xdelta','track02','original','second.bin','second-target.bin')])]:
        manifest={'schema_version':2,'game_id':'android-fixture','game_name':'Synthetic Android game','platform':'dreamcast','version':v,'source_commit':'1'*40,'patches':patches,
          'solutions':[{'id':'disc','name':'Synthetic disc','edition':'Original','language':'English','files':[{'edition':'track01','output_name':'track01.bin'},{'edition':'track02','output_name':'track02.bin'}],
          'copy_files':[{'name':'disc.cue','bytes':len(cue),'sha256':hashlib.sha256(cue).hexdigest()}]}]}
        records.append({'repo':'retro-trans/android-fixture','tag':'v'+v,'manifest':manifest,'assets':{p['patch']:f"https://github.com/retro-trans/android-fixture/releases/download/v{v}/{p['patch']}" for p in patches}})
    fixture={'schema_version':1,'releases':records};Catalog(fixture)
    (assets/'fixture-catalog.json').write_text(json.dumps(fixture),'utf-8')
    (assets/'identity.json').write_text(json.dumps({'source_sha256':hashlib.sha256(source).hexdigest(),
        'target_sha256':hashlib.sha256(modified).hexdigest(), 'target_bytes':len(modified)}),'utf-8')
    print(f'Generated {len(expected)} desktop route cases and three native decoder fixtures.')


if __name__ == '__main__':
    main()
