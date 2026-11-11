"""Verified portable Linux tools and release notices; no Windows updater."""
import json
import os
from pathlib import Path
import platform

from .core import PatchError, sha256_file

ROOT = Path(__file__).parent / 'resources/native/linux-x86_64'


def system_environment():
    env = os.environ.copy()
    if 'LD_LIBRARY_PATH_ORIG' in env:
        env['LD_LIBRARY_PATH'] = env.pop('LD_LIBRARY_PATH_ORIG')
    else:
        env.pop('LD_LIBRARY_PATH', None)
    return env


def native_tool(name):
    if name not in ('xdelta3', 'chdman', 'dolphin-tool'):
        raise PatchError('Unknown Linux tool.')
    try:
        manifest = json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))
        path = ROOT/name
        if (platform.machine().lower() not in ('x86_64', 'amd64') or
                manifest['architecture'] != 'x86_64' or path.is_symlink() or
                not path.is_file() or not os.access(path, os.X_OK) or
                sha256_file(path) != manifest['sha256'][name]):
            raise ValueError('tool identity')
        return path
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise PatchError('The bundled Linux tools are missing or damaged. Extract a fresh Retro Trans package.') from exc


def archive_name(version):
    return 'Retro-Trans-Linux-x86_64-' + version + '.tar.gz'


def update_notice(client, current, cancel=None):
    from .catalog import APP_REPO, version_key
    data = client.json('https://api.github.com/repos/' + APP_REPO + '/releases/latest', cancel)
    if data.get('draft') or data.get('prerelease'):
        return None
    version = data['tag_name'].lstrip('v')
    if version_key(version) <= version_key(current):
        return None
    if any(a.get('name') == archive_name(version) for a in data.get('assets', [])):
        return 'Linux app ' + version + ' is available. Download and extract it from App and releases below.'
    return None
