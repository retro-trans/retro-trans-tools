"""Real packaged Mac startup, whole-app update and official Vita3K CLI checks.

Only synthetic fixtures are used; no game PKG or license leaves the user's PC.
"""
import json
import os
from pathlib import Path
import shutil
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
    client = GitHubClient()
    asset = v.runtime_asset(client, None)
    archive = client.download(asset, ROOT/'.test-cache')
    with tempfile.TemporaryDirectory(prefix='retro-vita-cli-') as temp:
        root = Path(temp)
        exe = v.extract_mac_runtime(archive, root/'engine')
        portable = v.portable_directory(exe)
        portable.mkdir()
        # --help initializes only the isolated portable directory, not a user's Vita3K.
        result = subprocess.run([str(exe), '--help'], cwd=exe.parent, capture_output=True, timeout=60)
        text = (result.stdout+result.stderr).decode('utf-8', errors='replace')
        assert result.returncode == 0 and '--pkg' in text and '--zrif' in text, text[-3000:]
        reports['official_vita3k_cli'] = {'asset': asset.name, 'sha256': asset.sha256, 'bytes':asset.size}
    atomic_json(dist/'MAC-VALIDATION.json', reports)
    print(json.dumps(reports, indent=2))


if __name__ == '__main__':
    main()
