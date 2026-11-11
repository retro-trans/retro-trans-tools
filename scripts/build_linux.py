"""Build and test an offline portable Linux x86-64 package. Never publish."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retro_trans import __version__
from retro_trans.catalog import atomic_json
from retro_trans.core import Asset, GitHubClient, sha256_file
from retro_trans.linux import archive_name

TOOLS = ('xdelta3', 'chdman', 'dolphin-tool')
NATIVE = ROOT/'retro_trans/resources/native/linux-x86_64'
XDELTA_NAME = 'xdelta3-3.2.0-linux-x86_64.tar.gz'
XDELTA_SHA = 'ef65aafaa6daaf1f04ebe0028609f4eddf470cc1f7588fcf8298b65e1cfd5fd8'
PYTHON_VERSION = '3.12.16'


def manifest(root):
    atomic_json(root/'manifest.json', dict(architecture='x86_64',
        sha256={name:sha256_file(root/name) for name in TOOLS}))


def system_notices(destination, binaries):
    """Retain Debian copyright files and exact source-package provenance."""
    packages = set()
    paths = set(map(Path, binaries))
    for binary in binaries:
        output = subprocess.run(['ldd', str(binary)], capture_output=True, text=True).stdout
        paths.update(Path(p) for p in re.findall(r'(/[^\s()]+)', output))
    for path in paths:
        for spelling in (str(path), str(path.resolve())):
            result = subprocess.run(['dpkg-query', '-S', spelling], capture_output=True, text=True)
            for row in result.stdout.splitlines():
                if ': ' in row:
                    # dpkg also prints diversion descriptions, which are not
                    # package names. Multiple real owners use a comma list.
                    for owner in row.split(': ',1)[0].split(', '):
                        if re.fullmatch(r'[a-z0-9][a-z0-9+.-]*(?::[a-z0-9-]+)?', owner):
                            packages.add(owner)
    records = []
    for package in sorted(packages):
        info = subprocess.check_output(['dpkg-query','-W','-f=${binary:Package}\t${Version}\t${source:Package}\t${source:Version}',package], text=True).split('\t')
        notice = Path('/usr/share/doc')/package.split(':')[0]/'copyright'
        if not notice.is_file():
            raise RuntimeError('Missing dependency copyright: '+package)
        target = destination/'system'/package.replace(':','-')
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(notice, target/'copyright')
        records.append(dict(package=info[0],version=info[1],source_package=info[2],source_version=info[3],
                            source_url='https://launchpad.net/ubuntu/+source/'+info[2]+'/'+info[3]))
    # Debian copyright files refer to these complete license texts.
    shutil.copytree('/usr/share/common-licenses', destination/'common-licenses', dirs_exist_ok=True)
    atomic_json(destination/'system-provenance.json', records)


def prepare():
    NATIVE.mkdir(parents=True, exist_ok=True)
    archive = GitHubClient().download(Asset(XDELTA_NAME,
        'https://github.com/jmacd/xdelta/releases/download/v3.2.0/'+XDELTA_NAME,
        248931, XDELTA_SHA), ROOT/'.build-tools')
    with tarfile.open(archive,'r:gz') as tar:
        entries = [e for e in tar.getmembers() if e.isfile() and Path(e.name).name == 'xdelta3']
        if len(entries) != 1 or entries[0].size > 10*1024**2:
            raise RuntimeError('Invalid pinned xdelta archive')
        (NATIVE/'xdelta3').write_bytes(tar.extractfile(entries[0]).read())
    sources = []
    from bundle_linux_dolphin import BUILD, copy_notices as dolphin_notices
    for name in ('chdman','dolphin-tool'):
        path = (BUILD/'Binaries/dolphin-tool') if name == 'dolphin-tool' else (shutil.which(name) or '/usr/games/'+name)
        if not Path(path).is_file():
            raise RuntimeError('Install mame-tools and build the pinned Dolphin tool first')
        sources.append(Path(path))
        shutil.copy2(path,NATIVE/name)
    for name in TOOLS:
        (NATIVE/name).chmod(0o755)
    subprocess.run([str(NATIVE/'xdelta3'),'-V'], check=True)
    manifest(NATIVE)
    notices = NATIVE/'licenses'
    notices.mkdir(exist_ok=True)
    dolphin_notices(notices/'dolphin')
    for path in (ROOT/'THIRD_PARTY_NOTICES.md',ROOT/'retro_trans/resources/XDELTA-LICENSE.txt'):
        shutil.copy2(path,notices/path.name)
    from retro_trans.dependency_notices import copy_notices
    copy_notices(notices)
    for package in ('certifi','pyinstaller'):
        dist = importlib.metadata.distribution(package)
        for entry in dist.files or []:
            if Path(entry).name.lower().startswith(('license','copying')):
                source = Path(dist.locate_file(entry))
                if source.is_file():
                    shutil.copy2(source,notices/(package+'-'+source.name))
    import _tkinter
    system_notices(notices,sources+[Path(sys.executable),Path(_tkinter.__file__)])
    GitHubClient().download(Asset('Python-'+PYTHON_VERSION+'-LICENSE.txt',
        'https://raw.githubusercontent.com/python/cpython/v'+PYTHON_VERSION+'/LICENSE',
        13936, '3b2f81fe21d181c499c59a256c8e1968455d6689d269aa85373bfb6af41da3bf'), notices)
    (notices/'XDELTA-SOURCE.txt').write_text('Pinned xdelta 3.2.0: https://github.com/jmacd/xdelta/releases/tag/v3.2.0\n'
        'Source: https://github.com/jmacd/xdelta/releases/download/v3.2.0/xdelta3-3.2.0.tar.gz\n'
        'Source SHA-256: 628cfa920fb5cf9f0c61b2c91a036b713fc08c7858fc53f1cc87e0921d74ffa1\n',encoding='utf-8')


def main():
    if sys.platform != 'linux' or platform.machine().lower() != 'x86_64':
        raise SystemExit('Build natively on Linux x86-64.')
    if platform.python_version() != PYTHON_VERSION:
        raise SystemExit('Use the pinned Python '+PYTHON_VERSION+' build runtime.')
    os.chdir(ROOT)
    prepare()
    if '--prepare-only' in sys.argv:return
    if not (ROOT/'retro_trans/resources/native/dcp/linux-x64/engine.json').is_file():
        raise RuntimeError('Build the pinned Linux DCP helper first.')
    subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-v'],check=True)
    resources = ROOT/'build/linux-resources'
    if resources.exists():
        if resources.resolve().parent != (ROOT/'build').resolve():raise RuntimeError('Invalid resource staging directory')
        shutil.rmtree(resources)
    shutil.copytree(ROOT/'retro_trans/resources',resources,ignore=shutil.ignore_patterns('native','*-windows.zip'))
    shutil.copytree(NATIVE,resources/'native/linux-x86_64')
    shutil.copytree(ROOT/'retro_trans/resources/native/dcp/linux-x64',resources/'native/dcp/linux-x64')
    args=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--name','Retro-Trans',
          '--collect-data','certifi','--add-data',str(resources)+':retro_trans/resources']
    for name in TOOLS:args+=['--add-binary',str(NATIVE/name)+':retro_trans/resources/native/linux-x86_64']
    # PyInstaller excludes Wayland libraries by default. Ubuntu's command-line
    # chdman links SDL, which requires these even without opening a window.
    dependencies = subprocess.check_output(['ldd', str(NATIVE/'chdman')], text=True)
    for name in ('libwayland-egl.so.1', 'libwayland-client.so.0', 'libwayland-cursor.so.0'):
        match = re.search(re.escape(name)+r'\s+=>\s+(/\S+)', dependencies)
        if not match or not Path(match.group(1)).is_file():
            raise RuntimeError('Missing CHD runtime dependency: '+name)
        args += ['--add-binary', match.group(1)+':.']
    subprocess.run(args+['launch.py'],check=True)
    app=ROOT/'dist/Retro-Trans'
    packaged=app/'_internal/retro_trans/resources/native'
    for name in TOOLS:(packaged/'linux-x86_64'/name).chmod(0o755)
    for source in (ROOT/'retro_trans/resources/native/dcp/linux-x64').iterdir():
        if source.is_file() and os.access(source,os.X_OK):
            (packaged/'dcp/linux-x64'/source.name).chmod(0o755)
    manifest(packaged/'linux-x86_64')
    shutil.copy2(ROOT/'docs/LINUX.md',app/'README-Linux.md')
    shutil.copy2(ROOT/'THIRD_PARTY_NOTICES.md',app/'THIRD_PARTY_NOTICES.md')
    health=ROOT/'dist/LINUX-HEALTH.json'
    with tempfile.TemporaryDirectory(prefix='retro-linux-check-') as temporary:
        env=os.environ.copy();env['RETRO_TRANS_DATA_DIR']=temporary
        env['DOTNET_SYSTEM_GLOBALIZATION_INVARIANT']='1'
        subprocess.run([str(app/'Retro-Trans'),'--health-check',str(health)],check=True,env=env,timeout=180)
        subprocess.run([str(app/'Retro-Trans'),'--network-check',str(ROOT/'dist/LINUX-NETWORK.json')],check=True,env=env,timeout=120)
    report=json.loads(health.read_text())
    if not report['ok']:raise RuntimeError('Packaged Linux health check failed')
    output=ROOT/'dist'/archive_name(__version__)
    with tarfile.open(output,'w:gz') as tar:tar.add(app,arcname='Retro-Trans')
    checksum=sha256_file(output)
    (ROOT/'dist'/('SHA256SUMS-Linux-'+__version__+'.txt')).write_text(checksum+'  '+output.name+'\n',encoding='utf-8')
    atomic_json(ROOT/'dist'/('LINUX-'+__version__+'-VALIDATION.json'),dict(version=__version__,
        source_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        platform='linux-x86_64',minimum_glibc='2.39',python=PYTHON_VERSION,build_os=platform.freedesktop_os_release(),
        archive=dict(name=output.name,bytes=output.stat().st_size,sha256=checksum),
        health=report,tests_passed=True,engines=TOOLS,standalone=True,auto_app_install=False))
    print('Verified Linux archive:',output)


if __name__=='__main__':main()
