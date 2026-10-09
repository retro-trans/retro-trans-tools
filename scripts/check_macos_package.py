"""Real packaged Mac startup, whole-app update and official Vita3K CLI checks.

Only synthetic fixtures are used; no game PKG or license leaves the user's PC.
"""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retro_trans import __version__, mac_updater as u, vita_pkg as v
from retro_trans.catalog import atomic_json
from retro_trans.core import GitHubClient
from retro_trans.updater import update_directory
from scripts.build_macos import manifest


def next_launch_update(root, dist, metadata):
    """Build an old-version fixture, then let its real detached helper update it."""
    root.mkdir()
    hook = root/'old_version.py'
    hook.write_text("import retro_trans\nretro_trans.__version__ = '0.0.0'\n")
    args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onedir', '--windowed',
        '--name', 'Retro-Trans', '--osx-bundle-identifier', u.IDENTIFIER,
        '--codesign-identity', '-', '--runtime-hook', str(hook),
        '--distpath', str(root/'old'), '--workpath', str(root/'build'), '--specpath', str(root),
        '--add-data', str(ROOT/'retro_trans/resources')+':retro_trans/resources']
    for name in ('xdelta3', 'chdman'):
        args.extend(['--add-binary', str(ROOT/'retro_trans/resources/native'/name)+':retro_trans/resources/native'])
    subprocess.run(args+[str(ROOT/'launch.py')], cwd=ROOT, check=True)
    target = root/'old'/u.APP
    manifest(target/'Contents/Resources/retro_trans/resources/native')
    subprocess.run(['codesign', '--force', '--sign', '-', str(target)], check=True)
    old_digest = __import__('hashlib').sha256(u.executable(target).read_bytes()).hexdigest()
    env = dict(os.environ, RETRO_TRANS_DATA_DIR=str(root/'data'))
    with patch.dict(os.environ, {'RETRO_TRANS_DATA_DIR': env['RETRO_TRANS_DATA_DIR']}):
        directory = update_directory(u.executable(target))
    directory.mkdir(parents=True)
    shutil.copyfile(dist/metadata['asset'], directory/(metadata['sha256']+'.zip'))
    atomic_json(directory/'pending-mac.json', metadata)
    settings = root/'data/settings.json'
    atomic_json(settings, {'keep_fixture_setting': True})
    process = subprocess.Popen([str(u.executable(target))], env=env, start_new_session=True)
    launched_pid = None
    try:
        deadline = time.monotonic()+120
        while time.monotonic() < deadline:
            if (directory/'status.json').exists():
                break
            time.sleep(.2)
        status = json.loads((directory/'status.json').read_text())
        assert status.get('message') == 'Updated to '+__version__, status
        startup = json.loads((directory/'startup.json').read_text())
        launched_pid = startup['pid']
        assert startup['ok'] and startup['version'] == __version__
        backup = Path(status['backup'])
        assert __import__('hashlib').sha256(u.executable(backup).read_bytes()).hexdigest() == old_digest
        assert json.loads(settings.read_text())['keep_fixture_setting']
        assert not (directory/'pending-mac.json').exists()
        process.wait(timeout=15)
    finally:
        if launched_pid:
            try:
                os.kill(launched_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=15)


def main():
    dist = ROOT/'dist'
    reports = {'version': __version__, 'real_game_pkg_tested': False}
    metadata = json.loads((dist/u.names()[0]).read_text())
    with tempfile.TemporaryDirectory(prefix='retro-mac-package-') as temp:
        root = Path(temp)
        target = root/u.APP
        shutil.copytree(dist/u.APP, target, symlinks=True)
        directory = root/'updates'; directory.mkdir()
        shutil.copyfile(dist/metadata['asset'], directory/(metadata['sha256']+'.zip'))
        atomic_json(directory/'pending-mac.json', metadata)
        real_pending = u.pending
        # Same-version package fixture; production still rejects non-newer versions.
        with patch.object(u, 'pending', lambda d: real_pending(d, current='0.0.0')):
            def health(exe, version, path, launch=False):
                result = subprocess.run([str(exe), '--health-check', str(path)], timeout=120)
                return result.returncode == 0 and json.loads(path.read_text()).get('version') == version
            assert u.install(target, directory, health), (directory/'status.json').read_text()
        reports['packaged_bundle_update'] = True
        assert list(root.glob('*.previous-*'))
        reports['previous_app_retained'] = True
        next_launch_update(root/'launch-fixture', dist, metadata)
        reports['packaged_next_launch_update'] = True
    client = GitHubClient()
    asset = v.runtime_asset(client, None)
    archive = client.download(asset, ROOT/'.test-cache')
    with tempfile.TemporaryDirectory(prefix='retro-vita-cli-') as temp:
        root = Path(temp)
        exe = v.extract_mac_runtime(archive, root/'engine')
        portable = v.portable_directory(exe)
        portable.mkdir()
        # --help initializes only the isolated portable directory, not a user's Vita3K.
        child_env = {k: value for k, value in os.environ.items() if k not in ('GH_TOKEN', 'GITHUB_TOKEN')}
        result = subprocess.run([str(exe), '--help'], cwd=exe.parent, env=child_env, capture_output=True, timeout=60)
        text = (result.stdout+result.stderr).decode('utf-8', errors='replace')
        assert result.returncode == 0 and '--pkg' in text and '--zrif' in text, text[-3000:]
        reports['official_vita3k_cli'] = {'asset': asset.name, 'sha256': asset.sha256, 'bytes':asset.size}
    atomic_json(dist/'MAC-VALIDATION.json', reports)
    print(json.dumps(reports, indent=2))


if __name__ == '__main__':
    main()
