"""Build a native, offline-capable Mac app and test ZIP; never publish."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retro_trans import __version__
from retro_trans.core import Asset, GitHubClient, sha256_file
from retro_trans.catalog import atomic_json
from retro_trans.macos import architecture
from retro_trans.mac_updater import APP, IDENTIFIER, names

XDELTA = {
    'arm64': (195888, '1d865224f5e316ce7486bf1e98b4531dc13721b8fcafcbf2ecc08f4e2f83e1da'),
    'x86_64': (222674, '62f936bbb2679a5602b7434d8fc643ff4f4293ade3dcc9024a99ca6f7e42f093'),
}


def zip_app(app, output):
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
        for path in sorted(app.rglob('*')):
            name = str(path.relative_to(app.parent)).replace(os.sep, '/')
            if path.is_symlink():
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                z.writestr(info, os.readlink(path).encode())
            elif path.is_file():
                z.write(path, name)


def manifest(native):
    atomic_json(native/'manifest.json', {'architecture': architecture(),
        'sha256': {name: sha256_file(native/name) for name in ('xdelta3', 'chdman')}})


def prepare():
    native = ROOT/'retro_trans/resources/native'
    native.mkdir(parents=True, exist_ok=True)
    name = 'xdelta3-3.2.0-macos-' + architecture() + '.tar.gz'
    size, digest = XDELTA[architecture()]
    archive = GitHubClient().download(Asset(name,
        'https://github.com/jmacd/xdelta/releases/download/v3.2.0/'+name, size, digest), ROOT/'.build-tools')
    with tarfile.open(archive, 'r:gz') as tar:
        entries = [e for e in tar.getmembers() if e.isfile() and Path(e.name).name == 'xdelta3']
        if len(entries) != 1 or entries[0].size > 10*1024**2:
            raise RuntimeError('Invalid official xdelta archive')
        (native/'xdelta3').write_bytes(tar.extractfile(entries[0]).read())
    chdman = shutil.which('chdman')
    if not chdman:
        raise RuntimeError('Build machine needs brew install rom-tools')
    shutil.copy2(chdman, native/'chdman')
    for name in ('xdelta3', 'chdman'):
        (native/name).chmod(0o755)
    manifest(native)
    licenses = native/'licenses'
    licenses.mkdir(exist_ok=True)
    for name in ('README.md', 'THIRD_PARTY_NOTICES.md'):
        shutil.copy2(ROOT/name, licenses/name)
    shutil.copy2(ROOT/'retro_trans/resources/XDELTA-LICENSE.txt', licenses/'XDELTA-LICENSE.txt')
    # Retain Homebrew receipts and every shipped dependency's license files.
    packages = ['rom-tools'] + subprocess.check_output(['brew', 'deps', 'rom-tools'], text=True).splitlines()
    for package in packages:
        prefix = Path(subprocess.check_output(['brew', '--prefix', package], text=True).strip()).resolve()
        dest = licenses/package
        dest.mkdir(exist_ok=True)
        for path in prefix.rglob('*'):
            if path.is_file() and (path.name.lower().startswith(('license', 'copying', 'copyright'))
                                  or path.name == 'INSTALL_RECEIPT.json'):
                relative = path.relative_to(prefix)
                (dest/relative).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest/relative)
    atomic_json(licenses/'homebrew-provenance.json', json.loads(subprocess.check_output(
        ['brew', 'info', '--json=v2'] + packages, text=True)))
    for base in (Path(sys.base_prefix), Path(sys.base_prefix)/'Resources'):
        for path in base.glob('LICENSE*'):
            if path.is_file():
                shutil.copy2(path, licenses/('Python-'+path.name))
    import tkinter
    tcl = tkinter.Tcl()
    tcl_dir = Path(tcl.eval('info library'))
    for parent in (tcl_dir, tcl_dir.parent/'tk8.6'):
        for path in parent.glob('license*'):
            shutil.copy2(path, licenses/(parent.name+'-'+path.name))
    return native


def main():
    if sys.platform != 'darwin':
        raise SystemExit('Run on macOS; this does not cross-compile.')
    os.chdir(ROOT)
    native = prepare()
    if '--prepare-only' in sys.argv:
        return
    subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], check=True)
    args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed',
        '--name', 'Retro-Trans', '--osx-bundle-identifier', IDENTIFIER,
        '--target-architecture', architecture(), '--codesign-identity', '-',
        '--add-data', 'retro_trans/resources:retro_trans/resources']
    for name in ('xdelta3', 'chdman'):
        args.extend(['--add-binary', str(native/name)+':retro_trans/resources/native'])
    subprocess.run(args+['launch.py'], check=True)
    app = ROOT/'dist'/APP
    info_path = app/'Contents/Info.plist'
    info = plistlib.loads(info_path.read_bytes())
    minimum = platform.mac_ver()[0].split('.')[0] + '.0'
    info.update(CFBundleShortVersionString=__version__, CFBundleVersion=__version__,
                LSMinimumSystemVersion=minimum)
    info_path.write_bytes(plistlib.dumps(info))
    # PyInstaller fixes dylib paths and signs nested binaries; hash final bytes.
    manifest(app/'Contents/Resources/retro_trans/resources/native')
    subprocess.run(['codesign', '--force', '--deep', '--sign', '-', str(app)], check=True)
    # Deep signing may re-sign tools: refresh and sign the outer resource seal.
    manifest(app/'Contents/Resources/retro_trans/resources/native')
    subprocess.run(['codesign', '--force', '--sign', '-', str(app)], check=True)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    metadata, asset, platform_id = names()
    output = ROOT/'dist'/asset
    zip_app(app, output)
    atomic_json(ROOT/'dist'/metadata, {'schema_version': 1, 'version': __version__,
        'platform': platform_id, 'asset': asset, 'bytes': output.stat().st_size,
        'sha256': sha256_file(output), 'minimum_macos': minimum})
    subprocess.run([str(app/'Contents/MacOS/Retro-Trans'), '--health-check', str(ROOT/'dist/APP-HEALTH.json')],
                   check=True, timeout=120)
    if not json.loads((ROOT/'dist/APP-HEALTH.json').read_text()).get('ok'):
        raise RuntimeError('Packaged Mac health check failed')
    print('Local test package: '+str(output))


if __name__ == '__main__':
    main()
