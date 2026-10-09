"""Verified whole-app updates. Preserve the previous bundle on failed startup."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
import zipfile

from . import __version__
from .catalog import APP_REPO, atomic_json, version_key
from .core import Asset, GitHubClient, PatchError, check_cancel, sha256_file, valid_hash, valid_size
from .macos import app_bundle, architecture

APP = 'Retro-Trans.app'
IDENTIFIER = 'org.retro-trans.tools'


def names():
    arch = architecture()
    return 'UPDATE-macos-' + arch + '.json', 'Retro-Trans-macos-' + arch + '.zip', 'macos-' + arch


def executable(bundle):
    return Path(bundle)/'Contents/MacOS/Retro-Trans'


def extract_app(archive, destination, version):
    """Bounded extraction; create internal relative symlinks only after files."""
    destination = Path(destination)
    links, seen, total = [], set(), 0
    with zipfile.ZipFile(archive) as z:
        entries = z.infolist()
        if len(entries) > 30000:
            raise PatchError('Mac update contains too many files.')
        for item in entries:
            name = PurePosixPath(item.filename)
            parts = name.parts
            if (not parts or parts[0] != APP or name.is_absolute() or
                    any(p in ('.', '..') for p in parts) or '\\' in item.filename or
                    '\0' in item.filename or str(name).casefold() in seen):
                raise PatchError('Unsafe Mac update archive path.')
            seen.add(str(name).casefold())
            total += item.file_size
            if total > 1024**3:
                raise PatchError('Mac update is too large.')
            mode = item.external_attr >> 16
            target = destination.joinpath(*parts)
            if stat.S_ISLNK(mode):
                if item.file_size > 4096:
                    raise PatchError('Invalid Mac update link.')
                link = z.read(item).decode('utf-8')
                if os.path.isabs(link) or '\\' in link:
                    raise PatchError('External Mac update link.')
                resolved = (target.parent/link).resolve()
                if (destination/APP).resolve() not in resolved.parents:
                    raise PatchError('External Mac update link.')
                links.append((target, link))
            elif item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif stat.S_IFMT(mode) not in (0, stat.S_IFREG):
                raise PatchError('Unsupported Mac update file type.')
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(item) as src, target.open('xb') as dst:
                    shutil.copyfileobj(src, dst)
                target.chmod(0o755 if mode & 0o111 else 0o644)
        for target, link in links:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(link)
    bundle = destination/APP
    for path in bundle.rglob('*'):
        if path.is_symlink() and (bundle.resolve() not in path.resolve().parents or not path.exists()):
            raise PatchError('Invalid Mac application link.')
    info = plistlib.loads((bundle/'Contents/Info.plist').read_bytes())
    if (info.get('CFBundleIdentifier') != IDENTIFIER or
            info.get('CFBundleShortVersionString') != version or
            info.get('CFBundleExecutable') != 'Retro-Trans' or not executable(bundle).is_file()):
        raise PatchError('Mac application identity does not match its update.')
    return bundle


def stage_update(client=None, directory=None, current=__version__, cancel=None):
    from .updater import update_directory
    client, directory = client or GitHubClient(), Path(directory) if directory else update_directory()
    release = client.json('https://api.github.com/repos/' + APP_REPO + '/releases/latest', cancel)
    if release.get('draft') or release.get('prerelease'):
        return None
    version = release['tag_name'].lstrip('v')
    if version_key(version) <= version_key(current):
        return None
    try:
        if json.loads((directory/'status.json').read_text()).get('failed_version') == version:
            return 'Update {} needs attention; see About / Updates.'.format(version)
    except (OSError, ValueError):
        pass
    metadata_name, asset_name, platform_id = names()
    assets = {a['name']: a for a in release['assets']}
    if metadata_name not in assets:
        return 'No newer Mac build is available.'
    prefix = 'https://github.com/' + APP_REPO + '/releases/download/' + release['tag_name'] + '/'
    meta = assets[metadata_name]
    if meta['browser_download_url'] != prefix + metadata_name:
        raise PatchError('Unexpected Mac update metadata URL.')
    raw = client.read(meta['browser_download_url'], cancel)
    if len(raw) != meta['size'] or meta.get('digest') != 'sha256:' + hashlib.sha256(raw).hexdigest():
        raise PatchError('Mac update metadata failed verification.')
    data = json.loads(raw)
    if (data.get('schema_version') != 1 or data.get('version') != version or
            data.get('platform') != platform_id or data.get('asset') != asset_name):
        raise PatchError('Unsupported Mac update metadata.')
    digest, size = valid_hash(data['sha256']), valid_size(data['bytes'])
    asset = assets.get(asset_name, {})
    if (size > 512*1024**2 or asset.get('size') != size or asset.get('digest') != 'sha256:' + digest
            or asset.get('browser_download_url') != prefix + asset_name):
        raise PatchError('Mac update disagrees with its release metadata.')
    download = client.download(Asset(asset_name, prefix+asset_name, size, digest), directory/'downloads', cancel)
    check_cancel(cancel)
    candidate = directory/(digest + '.zip')
    with tempfile.NamedTemporaryFile(dir=directory, suffix='.part', delete=False) as f:
        temporary = Path(f.name)
    try:
        shutil.copyfile(download, temporary)
        if sha256_file(temporary) != digest:
            raise PatchError('Copied Mac update failed verification.')
        os.replace(temporary, candidate)
    finally:
        temporary.unlink(missing_ok=True)
    check_cancel(cancel)
    atomic_json(directory/'pending-mac.json', data)
    return 'App {} downloaded; installs on next launch.'.format(version)


def pending(directory, current=__version__):
    data = json.loads((Path(directory)/'pending-mac.json').read_text())
    meta, asset, platform_id = names()
    if version_key(data['version']) <= version_key(current):
        return None
    digest, size = valid_hash(data['sha256']), valid_size(data['bytes'])
    candidate = Path(directory)/(digest+'.zip')
    if (data.get('platform') != platform_id or data.get('asset') != asset or
            candidate.stat().st_size != size or sha256_file(candidate) != digest):
        raise PatchError('Staged Mac update failed verification.')
    return data, candidate


def install(target, directory, health=None):
    import fcntl
    from .updater import _health_check
    health = health or _health_check
    target, directory = Path(target).resolve(), Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    with (directory/'install.lock').open('a+b') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        backup = target.with_name(target.name + '.previous-' + uuid.uuid4().hex)
        moved, data = False, {}
        try:
            result = pending(directory)
            if result is None:
                return False
            data, archive = result
            info = plistlib.loads((target/'Contents/Info.plist').read_bytes())
            if info.get('CFBundleIdentifier') != IDENTIFIER or target.suffix != '.app':
                raise PatchError('Update target is not Retro Trans.')
            with tempfile.TemporaryDirectory(prefix='.retro-update-', dir=target.parent) as folder:
                replacement = extract_app(archive, folder, data['version'])
                if not health(executable(replacement), data['version'], directory/'preflight.json'):
                    raise PatchError('Mac update failed its startup check.')
                os.rename(target, backup)
                moved = True
                os.rename(replacement, target)
                if not health(executable(target), data['version'], directory/'startup.json', launch=True):
                    # Retain the failed candidate in the private staging directory.
                    os.rename(target, replacement)
                    raise PatchError('New Mac app failed to start; previous app restored.')
            atomic_json(directory/'status.json', {'message': 'Updated to '+data['version'], 'backup': str(backup)})
            (directory/'pending-mac.json').unlink(missing_ok=True)
            return True
        except Exception as exc:
            if moved:
                if target.exists():
                    os.rename(target, target.with_name(target.name+'.failed-'+uuid.uuid4().hex))
                os.rename(backup, target)
            atomic_json(directory/'status.json', {'failed_version': data.get('version'),
                'message': 'Automatic Mac update failed: {}. Existing app retained.'.format(exc)})
            (directory/'pending-mac.json').unlink(missing_ok=True)
            return False


def maybe_install_pending():
    from .updater import update_directory
    target = app_bundle()
    if not getattr(sys, 'frozen', False) or target is None:
        return False
    directory = update_directory()
    try:
        if pending(directory) is None:
            return False
        root = Path(tempfile.mkdtemp(prefix='helper-', dir=directory))
        helper = root/APP
        shutil.copytree(target, helper, symlinks=True)
        subprocess.Popen([str(executable(helper)), '--apply-update', str(target), str(directory)], start_new_session=True)
        return True
    except FileNotFoundError:
        return False
    except (PatchError, OSError, ValueError, KeyError) as exc:
        atomic_json(directory/'status.json', {'message': 'Could not install staged Mac update: '+str(exc)})
        return False


def helper_main(target, directory):
    from .updater import update_directory
    if Path(directory).resolve() != update_directory(executable(target)).resolve():
        raise PatchError('Invalid Mac update helper directory.')
    success = install(target, directory)
    if not success:
        subprocess.Popen([str(executable(target)), '--skip-update'], start_new_session=True)
    return 0 if success else 1
