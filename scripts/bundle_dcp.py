"""Build the GPL DCP process helper from pinned upstream sources. Dry by default."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
COMMIT = '8b352f959bcc56ab39174c9e311b7ab7f0d522a2'
REPO = 'https://github.com/DerekPascarella/UniversalDreamcastPatcher.git'


def copy_runtime_notices(output, package_folders):
    dependencies = json.loads((output / 'RetroTrans.Dcp.deps.json').read_text(encoding='utf-8'))['libraries']
    for match, prefix in (('runtimepack.Microsoft.NETCore.App.Runtime.', 'DOTNET'),
                          ('System.IO.Hashing/', 'System.IO.Hashing')):
        names = [name for name in dependencies if name.startswith(match)]
        if len(names) != 1:
            raise RuntimeError('Cannot identify the exact DCP dependency: ' + match)
        name = names[0]
        if name.startswith('runtimepack.'):
            name = name[len('runtimepack.'):]
        package, version = name.split('/')
        for source, suffix in (('LICENSE.TXT', '-LICENSE.txt'),
                               ('THIRD-PARTY-NOTICES.TXT', '-THIRD-PARTY-NOTICES.txt')):
            candidates = [Path(folder) / package.lower() / version / source for folder in package_folders]
            notice = next((p for p in candidates if p.is_file()), None)
            if notice is None or not notice.stat().st_size:
                raise RuntimeError('Missing DCP dependency notice: ' + name + '/' + source)
            shutil.copyfile(notice, output / (prefix + suffix))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--rid', default='win-x64', choices=('win-x64', 'linux-x64', 'osx-x64', 'osx-arm64'))
    ap.add_argument('--write', action='store_true')
    a = ap.parse_args()
    source = ROOT / '.integration/dcp/upstream'
    output = ROOT / 'retro_trans/resources/native/dcp' / a.rid
    print('Pinned Universal Dreamcast Patcher 2.1.8:', COMMIT)
    print('Build self-contained helper and include corresponding source/licenses:', output)
    if not a.write:
        print('DRY RUN: no downloads or output changes.'); return
    if not source.exists():
        subprocess.run(['git', 'clone', '--depth', '1', '--branch', '2.1.8', REPO, str(source)], check=True)
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip() == COMMIT
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=source, text=True).strip()
    assert not output.exists(), 'Use a new helper output; do not overwrite a bundled engine.'
    subprocess.run(['dotnet', 'publish', str(ROOT / 'integrations/dcp/RetroTrans.Dcp.csproj'),
                    '-c', 'Release', '-r', a.rid, '--self-contained', 'true', '-o', str(output),
                    '-p:UdpSource=' + str(source).replace('\\', '/'), '-p:PublishSingleFile=false'], check=True)
    assets = json.loads((ROOT / 'integrations/dcp/obj/project.assets.json').read_text(encoding='utf-8'))
    copy_runtime_notices(output, assets['packageFolders'])
    shutil.copyfile(source / 'LICENSE.txt', output / 'UDP-GPL-3.0.txt')
    # Keep the complete pinned upstream tree and bridge source alongside the executable.
    with zipfile.ZipFile(output / 'CORRESPONDING-SOURCE.zip', 'x', zipfile.ZIP_DEFLATED) as z:
        tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=source).decode().split('\0')
        for name in filter(None, tracked): z.write(source / name, 'UniversalDreamcastPatcher/' + name)
        for p in (ROOT / 'integrations/dcp').glob('*'):
            if p.is_file(): z.write(p, 'RetroTrans.Dcp/' + p.name)
        z.write(Path(__file__), 'bundle_dcp.py')
    records = {p.name: {'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
               for p in output.iterdir() if p.is_file()}
    (output / 'engine.json').write_text(json.dumps({'upstream_commit': COMMIT, 'upstream_version': '2.1.8',
        'rid': a.rid, 'files': records}, indent=2) + '\n', encoding='utf-8')
    print('Bundled', len(records), 'verified files; no .NET installation needed at runtime.')


if __name__ == '__main__': main()
