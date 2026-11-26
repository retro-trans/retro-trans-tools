"""Gate publication on complete, current, verified artifacts for every platform."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retro_trans import __version__

PREVIEW_SIGNER = '32fcd938f3658c416b38bfae12d4c5de22f7811cab981ca9a2854244926ea5f7'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare(source, output):
    selected = {}
    proofs = {}

    def find(name, folder=source):
        paths = list(folder.rglob(name))
        if len(paths) != 1 or not paths[0].is_file() or paths[0].is_symlink():
            raise ValueError('Missing or ambiguous release artifact: '+name)
        return paths[0]

    def read(name, folder=source):
        return json.loads(find(name, folder).read_text(encoding='utf-8'))

    def take(name, folder=source):
        path = find(name, folder)
        if name in selected:
            raise ValueError('Duplicate publication asset: '+name)
        selected[name] = path
        return path

    def identity(path, record):
        if path.stat().st_size != record['bytes'] or sha(path) != record['sha256']:
            raise ValueError('Release artifact integrity failed: '+path.name)

    def version(record):
        if record['version'] != __version__:
            raise ValueError('A platform build is stale.')

    win = read('UPDATE.json'); version(win)
    if win['platform'] != 'windows-x86_64' or win['asset'] != 'Retro-Trans.exe':
        raise ValueError('Wrong Windows update target.')
    identity(take('Retro-Trans.exe'), win)
    with zipfile.ZipFile(take('Retro-Trans-Windows.zip')) as archive:
        entries = [n for n in archive.namelist() if n == 'Retro-Trans.exe']
        if len(entries) != 1:
            raise ValueError('Missing Windows EXE in ZIP.')
        with archive.open(entries[0]) as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != win['sha256']:
                raise ValueError('Windows ZIP contains a different EXE.')
    take('UPDATE.json')
    for name in ('packaged-health.json', 'packaged-network.json'):
        report = read(name); version(report)
        if not report['ok'] or report['tls']['provider'] != 'windows-native':
            raise ValueError('Windows packaged checks failed.')
        proofs[name] = report
    for arch in ('arm64', 'x86_64'):
        meta_name = 'UPDATE-macos-'+arch+'.json'
        meta_path = find(meta_name)
        meta = json.loads(meta_path.read_text()); version(meta)
        if meta['platform'] != 'macos-'+arch or meta['asset'] != 'Retro-Trans-macos-'+arch+'.zip':
            raise ValueError('Wrong Mac update target.')
        take(meta_name)
        identity(take('Retro-Trans-macos-'+arch+'.zip'), meta)
        for name in ('APP-HEALTH.json', 'NETWORK-HEALTH.json', 'MAC-VALIDATION.json'):
            report = read(name, meta_path.parent); version(report)
            if name == 'MAC-VALIDATION.json':
                if not report.get('packaged_next_launch_update'):
                    raise ValueError('Mac update checks failed.')
            elif not report.get('ok'):
                raise ValueError('Mac packaged checks failed.')
            proofs['macos-'+arch+'-'+name] = report
    linux_name = 'LINUX-'+__version__+'-VALIDATION.json'
    linux = read(linux_name); version(linux)
    identity(take(linux['archive']['name']), linux['archive'])
    take(linux_name); take('SHA256SUMS-Linux-'+__version__+'.txt')
    if not linux['tests_passed'] or not linux['health']['ok']:
        raise ValueError('Linux package checks failed.')
    proofs['linux'] = linux
    # This is the independent clean-container check without installed engines.
    clean = read('CLEAN-LINUX-HEALTH.json')
    if not clean['ok'] or clean['version'] != __version__:
        raise ValueError('Linux clean-container check failed.')
    proofs['linux-clean'] = clean
    android_name = 'ANDROID-'+__version__+'-VALIDATION.json'
    android = read(android_name); version(android)
    if (android['version_name'] != __version__+'-preview' or not android['preview'] or
            set(android['abis']) != {'arm64-v8a', 'x86_64'} or android['signer_sha256'] != PREVIEW_SIGNER or
            not android['native_16kb_alignment'] or not android['apk_16kb_alignment'] or android['lint_errors']):
        raise ValueError('Android preview validation failed.')
    for kind in ('jvm_tests', 'emulator_tests'):
        if not android[kind] or any(r['errors'] or r['failures'] for r in android[kind]):
            raise ValueError('Android test validation failed.')
    identity(take(android['apk']['name']), android['apk'])
    take(android_name); take('README-Android.md')
    proofs['android'] = android
    if output.exists():
        raise ValueError('Use a new release staging directory.')
    output.mkdir(parents=True)
    for name, path in selected.items():
        shutil.copyfile(path, output/name)
    report = dict(version=__version__, all_platforms_verified=True,
                  platforms=['windows-x64', 'macos-arm64', 'macos-x86_64', 'linux-x86_64', 'android-preview'],
                  checks=proofs)
    (output/'RELEASE-VALIDATION.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    rows = [sha(path)+'  '+path.name+'\n' for path in sorted(output.iterdir()) if path.is_file()]
    (output/'SHA256SUMS.txt').write_text(''.join(rows), encoding='ascii')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifacts', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    prepare(args.artifacts, args.output)
    print('All platforms verified; release assets staged in', args.output)
