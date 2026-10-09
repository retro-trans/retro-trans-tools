"""Native macOS paths and verified, packaged tools (no Homebrew at runtime)."""
import json
import os
from pathlib import Path
import platform
import sys


def architecture():
    value = platform.machine().lower()
    if value in ('arm64', 'aarch64'):
        return 'arm64'
    if value in ('x86_64', 'amd64'):
        return 'x86_64'
    raise RuntimeError('This Mac architecture is not supported.')


def app_bundle(executable=None):
    executable = Path(executable or sys.executable).resolve()
    for parent in executable.parents:
        if parent.suffix == '.app' and (parent/'Contents/Info.plist').is_file():
            return parent
    return None


def native_tool(name):
    from .core import PatchError, sha256_file
    if name not in ('xdelta3', 'chdman'):
        raise PatchError('Unknown native tool.')
    root = Path(__file__).parent/'resources/native'
    try:
        manifest = json.loads((root/'manifest.json').read_text())
        path = root/name
        if (manifest['architecture'] != architecture() or not path.is_file()
                or sha256_file(path) != manifest['sha256'][name]
                or not os.access(path, os.X_OK)):
            raise ValueError('tool identity')
        return path
    except (OSError, KeyError, ValueError) as exc:
        raise PatchError('The bundled Mac tools are missing or damaged. Reinstall Retro Trans.') from exc
