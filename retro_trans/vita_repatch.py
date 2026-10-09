"""Declarative, hash-locked Vita overlays. Never execute package-supplied code.

Separate optional release extras, not a v2 disc solution or a PKG decryptor.
Only explicitly listed files are read; nothing is installed onto a Vita.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import tempfile
import zipfile
import zlib

from .core import (Asset, GitHubClient, MAX_METADATA, PatchError, cache_directory,
                   check_cancel, decode, engine_context, report, sha256_file,
                   valid_hash, valid_size)
from .solutions import output_name, copy_verified

REPO = 'retro-trans/SRW-Z3'
TAG = 'v0.9.0'
MANIFEST = 'VITA-REPATCH.json'
ARCHIVE = 'SRW-Z3-v0.9.0-Vita-patches.zip'
MAX_ARCHIVE = 256 * 1024**2
SCHEMA = 'retro-trans-vita-repatch-v1'
GUIDE = ('Close the game and back up saves and any existing overlay. Copy the generated '
         'rePatch/PCSG00264 folder into ux0:rePatch/PCSG00264 using VitaShell. '
         'Do not merge old mods or overwrite app, official updates, or savedata. '
         'Launch the existing game with compatible rePatch enabled. '
         'This test build still needs gameplay testing; Vita staff roll and ending teaser '
         'remain Japanese. It is not a Vita3K installer.')


def require(condition, message):
    if not condition:
        raise PatchError(message)


def relative_name(name):
    require(isinstance(name, str) and len(name) <= 240, 'Invalid Vita file path.')
    parts = name.split('/')
    require(1 <= len(parts) <= 10, 'Invalid Vita path depth.')
    for part in parts:
        output_name(part)
    require(name == 'eboot.bin' or (name.startswith(('DATA/', 'CommonData/')) and
            name.lower().endswith(('.bin', '.cpk'))), 'Unsupported Vita payload: ' + name)
    return name


def no_links(path):
    """Reject symlinks and Windows junctions, including existing ancestor folders."""
    path = Path(path).absolute()
    for item in (path,) + tuple(path.parents):
        if os.path.lexists(item):
            info = item.lstat()
            require(not stat.S_ISLNK(info.st_mode) and not
                    (getattr(info, 'st_file_attributes', 0) & 0x400),
                    'Use ordinary files/folders, not symbolic links or junctions: ' + str(item))
    return path


def beneath(root, name):
    path = no_links(Path(root) / name)
    require(Path(root).resolve() in path.resolve().parents, 'Path escapes its selected folder.')
    return path


def identity(row):
    require(isinstance(row, dict) and set(row) == {'bytes', 'sha256'}, 'Invalid file identity.')
    require(0 < valid_size(row['bytes']) <= 4 * 1024**3, 'Unsupported Vita file size.')
    valid_hash(row['sha256'])


def validate(data):
    try:
        require(isinstance(data, dict) and set(data) ==
                {'schema', 'title_id', 'app_version', 'name', 'build', 'files', 'auth'},
                'Incomplete or unsupported Vita patch description.')
        require(data['schema'] == SCHEMA and data['title_id'] == 'PCSG00264' and
                data['app_version'] == '01.00', 'This profile requires PCSG00264 v01.00.')
        for key in ('name', 'build'):
            require(isinstance(data[key], str) and 0 < len(data[key]) <= 150 and
                    all(ord(c) >= 32 for c in data[key]), 'Invalid Vita patch label.')
        files = data['files']
        require(isinstance(files, list) and 1 <= len(files) <= 589, 'Invalid Vita patch inventory.')
        paths, assets = set(), set()
        for row in files:
            require(isinstance(row, dict) and set(row) == {'path', 'source', 'target', 'patch'},
                    'Invalid Vita component.')
            path = relative_name(row['path'])
            require(path.casefold() not in paths, 'Duplicate Vita output path.')
            paths.add(path.casefold())
            identity(row['source']); identity(row['target'])
            patch = row['patch']
            require(isinstance(patch, dict) and set(patch) == {'name', 'bytes', 'sha256'},
                    'Invalid Vita patch asset.')
            name = output_name(patch['name'])
            require(name.endswith('.xdelta') and name.casefold() not in assets,
                    'Duplicate or invalid Vita patch asset.')
            assets.add(name.casefold())
            identity({k: patch[k] for k in ('bytes', 'sha256')})
        require('eboot.bin' in paths, 'Vita overlay must include its executable.')
        for path in paths:
            require(not any('/'.join(path.split('/')[:i]) in paths
                            for i in range(1, len(path.split('/')))), 'Conflicting file/folder paths.')
        require(sum(r['target']['bytes'] for r in files) <= 16 * 1024**3, 'Vita overlay is too large.')
        auth = data['auth']
        require(isinstance(auth, dict) and set(auth) == {'hex', 'sha256'}, 'Missing sanitized auth data.')
        require(isinstance(auth['hex'], str) and re.fullmatch('[0-9a-f]{288}', auth['hex']),
                'Invalid sanitized auth data.')
        binary = bytes.fromhex(auth['hex'])
        require(hashlib.sha256(binary).hexdigest() == valid_hash(auth['sha256']) and
                any(binary[:8]) and any(binary[16:80]) and not any(binary[8:16] + binary[80:]),
                'Auth data is not sanitized or failed verification. Do not supply a raw dump.')
        return data
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise PatchError('Invalid Vita patch description.') from exc


def read_description(raw):
    require(len(raw) <= MAX_METADATA, 'Vita patch description is too large.')
    try:
        return validate(json.loads(raw.decode('utf-8')))
    except (ValueError, UnicodeError) as exc:
        raise PatchError('Invalid Vita patch JSON.') from exc


def local_description(path):
    path = no_links(path)
    with path.open('rb') as stream:
        data = read_description(stream.read(MAX_METADATA + 1))
    return data, path.parent, None


def online_description(client=None, cancel=None, progress=None, cache=None):
    client = client or GitHubClient()
    release = client.json('https://api.github.com/repos/{}/releases/tags/{}'.format(REPO, TAG), cancel)
    require(isinstance(release, dict) and release.get('tag_name') == TAG and not
            release.get('draft') and not release.get('prerelease'), 'Vita release is not published.')
    assets = {}
    prefix = 'https://github.com/{}/releases/download/{}/'.format(REPO, TAG)
    for item in release.get('assets', []):
        name = item.get('name')
        if name in (MANIFEST, ARCHIVE) or (isinstance(name, str) and name.startswith('VITA-') and name.endswith('.xdelta')):
            output_name(name)
            require(name not in assets and item.get('browser_download_url') == prefix + name,
                    'Invalid Vita release asset address.')
            digest = item.get('digest', '') or ''
            require(digest.startswith('sha256:'), 'Vita release lacks asset checksums.')
            assets[name] = Asset(name, prefix + name, valid_size(item['size']), valid_hash(digest[7:]))
    require(MANIFEST in assets, 'The Vita rePatch download is not published yet. '
            'Use a reviewed local VITA-REPATCH.json with its patch files for testing.')
    require(assets[MANIFEST].size <= MAX_METADATA, 'Vita metadata is too large.')
    if ARCHIVE in assets:
        require(0 < assets[ARCHIVE].size <= MAX_ARCHIVE, 'Vita patch ZIP is too large.')
    path = client.download(assets[MANIFEST], cache or cache_directory(), cancel, progress)
    data, _, _ = local_description(path)
    for row in data['files']:
        p = row['patch']; asset = assets.get(p['name'])
        require(asset is not None and asset.size == p['bytes'] and asset.sha256 == p['sha256'],
                'Vita release asset differs from its description.')
    return data, None, assets


@contextmanager
def archive_description(path, expected=None, cancel=None, progress=None):
    """Extract only a bounded, exact flat inventory into a private temporary folder."""
    path = no_links(path)
    require(path.is_file() and 0 < path.stat().st_size <= MAX_ARCHIVE, 'Invalid Vita patch ZIP size.')
    with tempfile.TemporaryDirectory(prefix='retro-vita-patches-') as temporary:
        package = Path(temporary)
        try:
            with zipfile.ZipFile(path) as archive:
                entries = archive.infolist()
                require(2 <= len(entries) <= 590, 'Invalid Vita ZIP inventory.')
                names = set()
                for entry in entries:
                    name = output_name(entry.filename)
                    require(name == entry.orig_filename and name.casefold() not in names and
                            not entry.is_dir() and not entry.flag_bits & 1 and
                            stat.S_IFMT(entry.external_attr >> 16) in (0, stat.S_IFREG) and
                            entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                            'Unsafe or duplicate Vita ZIP entry.')
                    names.add(name.casefold())
                require(MANIFEST.casefold() in names, 'Vita ZIP has no patch description.')
                metadata = archive.getinfo(MANIFEST)
                require(0 < metadata.file_size <= MAX_METADATA, 'Vita ZIP metadata is too large.')
                raw = archive.read(metadata)
                data = read_description(raw)
                require(expected is None or data == expected, 'Vita ZIP profile differs from published metadata.')
                inventory = {r['patch']['name']: r['patch'] for r in data['files']}
                require(set(e.filename for e in entries) == set(inventory) | {MANIFEST},
                        'Vita ZIP must contain exactly the described patches and metadata.')
                require(sum(e.file_size for e in entries) <= MAX_ARCHIVE, 'Expanded Vita ZIP is too large.')
                require(shutil.disk_usage(package).free >= sum(e.file_size for e in entries) + 16 * 1024**2,
                        'Not enough temporary space for Vita patches.')
                for entry in entries:
                    check_cancel(cancel)
                    row = inventory.get(entry.filename)
                    require(row is None or entry.file_size == row['bytes'], 'Vita ZIP entry size mismatch.')
                    with archive.open(entry) as src, (package / entry.filename).open('xb') as dst:
                        remaining = entry.file_size
                        while remaining:
                            check_cancel(cancel)
                            chunk = src.read(min(1024**2, remaining))
                            require(bool(chunk), 'Truncated Vita ZIP entry.')
                            dst.write(chunk)
                            remaining -= len(chunk)
                        require(not src.read(1), 'Oversized Vita ZIP entry.')
                    if row is not None:
                        verify(package / entry.filename, row, cancel, progress)
                require((package / MANIFEST).read_bytes() == raw, 'Vita ZIP metadata changed.')
        except (zipfile.BadZipFile, zlib.error, KeyError, RuntimeError, NotImplementedError, EOFError) as exc:
            raise PatchError('Invalid or damaged Vita patch ZIP.') from exc
        yield data, package, None


@contextmanager
def description_context(description=None, client=None, cache=None, cancel=None, progress=None):
    if description:
        if Path(description).suffix.lower() == '.zip':
            with archive_description(description, cancel=cancel, progress=progress) as resolved:
                yield resolved
        else:
            yield local_description(description)
        return
    client = client or GitHubClient()
    data, package, assets = online_description(client, cancel, progress, cache)
    if ARCHIVE in assets:
        asset = assets[ARCHIVE]
        path = client.download(asset, cache or cache_directory(), cancel, progress)
        verify(path, dict(bytes=asset.size, sha256=asset.sha256), cancel, progress)
        with archive_description(path, data, cancel, progress) as resolved:
            yield resolved
    else:
        yield data, package, assets


def verify(path, row, cancel=None, progress=None):
    path = no_links(path)
    require(path.is_file() and path.stat().st_size == row['bytes'] and
            sha256_file(path, cancel, progress, 'Verifying ' + path.name) == row['sha256'].lower(),
            'File mismatch: {}. Use the original decrypted PCSG00264 v01.00 files and intact patches.'.format(path.name))


def auth_matches(eboot, auth):
    with eboot.open('rb') as stream:
        header = stream.read(4096)
    require(len(header) >= 0x80 and header[:4] == b'SCE\0', 'Output is not a SELF executable.')
    offset = struct.unpack_from('<Q', header, 0x38)[0]
    require(0x80 <= offset <= len(header) - 32 and header[offset:offset+8] == auth[:8],
            'Sanitized authentication does not match the patched executable.')


def independent(a, b):
    return a != b and a not in b.parents and b not in a.parents


def apply(source, output, description=None, client=None, cache=None, cancel=None, progress=None, work_bin=None):
    # Resolve once, before package conversion; keep extracted patches alive until completion.
    if description:
        require(independent(Path(output).resolve(), no_links(description).resolve().parent),
                'Output must be outside the patch package.')
    with description_context(description, client, cache, cancel, progress) as resolved:
        if work_bin is not None:
            from .vita_pkg import decrypted_source
            with decrypted_source(source, work_bin, output, client, cache, cancel, progress) as decrypted:
                return _apply_files(decrypted, output, resolved, client, cache, cancel, progress)
        return _apply_files(source, output, resolved, client, cache, cancel, progress)


def _apply_files(source, output, resolved, client=None, cache=None, cancel=None, progress=None):
    client = client or GitHubClient()
    cache = Path(cache) if cache else cache_directory()
    source, output = no_links(source).resolve(), no_links(output)
    require(source.is_dir(), 'Choose the decrypted game folder containing eboot.bin, not a PKG.')
    require(not os.path.lexists(output) and output.parent.is_dir() and independent(source, output.resolve()),
            'Choose a NEW output folder outside the source game folder. Existing folders are never replaced.')
    data, package, assets = resolved
    if package:
        require(independent(output.resolve(), package.resolve()), 'Output must be outside the patch package.')
    check_cancel(cancel)
    for row in data['files']:
        verify(beneath(source, row['path']), row['source'], cancel, progress)
    needed = sum(r['target']['bytes'] + r['patch']['bytes'] for r in data['files']) + 64 * 1024**2
    require(shutil.disk_usage(output.parent).free >= needed, 'Not enough free space for the verified overlay.')
    downloads = {}
    for row in data['files']:
        p = row['patch']
        path = beneath(package, p['name']) if package else client.download(assets[p['name']], cache, cancel, progress)
        verify(path, p, cancel, progress)
        downloads[p['name']] = path
    auth = bytes.fromhex(data['auth']['hex'])
    with tempfile.TemporaryDirectory(prefix='.retro-vita-', dir=str(output.parent)) as temp:
        result = Path(temp) / 'result'
        tree = result / 'rePatch' / data['title_id']
        tree.mkdir(parents=True)
        with engine_context(client, cache, cancel, progress) as engine:
            for index, row in enumerate(data['files'], 1):
                name = row['path']
                check_cancel(cancel)
                src = beneath(source, name)
                verify(src, row['source'], cancel)
                delta = downloads[row['patch']['name']]
                verify(delta, row['patch'], cancel)
                dest = tree / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                def part_progress(message, fraction):
                    report(progress, 'Vita file {}/{}: {}'.format(index, len(data['files']), name),
                           (index - 1 + (fraction or 0)) / len(data['files']))
                decode(engine, src, delta, dest, row['target']['bytes'], cancel, part_progress)
                verify(dest, row['target'], cancel)
        auth_matches(tree / 'eboot.bin', auth)
        (tree / 'self_auth.bin').write_bytes(auth)
        verify(tree / 'self_auth.bin', dict(bytes=144, sha256=data['auth']['sha256']), cancel)
        for row in data['files']:
            verify(beneath(source, row['path']), row['source'], cancel)
        (result / 'README-INSTALL.txt').write_text(GUIDE + '\n', encoding='utf-8')
        (result / 'VERIFIED.json').write_text(json.dumps(dict(schema=data['schema'], build=data['build'],
            title_id=data['title_id'], files={r['path']: r['target'] for r in data['files']},
            sanitized_auth_sha256=data['auth']['sha256'], originals_unchanged=True,
            physical_runtime_verified=False), indent=2) + '\n', encoding='utf-8')
        check_cancel(cancel)
        no_links(output)
        require(not os.path.lexists(output), 'Output now exists; choose a new folder.')
        if os.name == 'nt':
            os.rename(result, output)  # Exclusive, atomic directory publication on Windows.
        else:
            # Reserve exclusively rather than overwrite an existing POSIX directory.
            output.mkdir()
            try:
                for path in result.rglob('*'):
                    dest = output / path.relative_to(result)
                    if path.is_dir():
                        dest.mkdir()
                    else:
                        copy_verified(path, dest, path.stat().st_size, sha256_file(path), cancel)
            except BaseException:
                shutil.rmtree(output)
                raise
    report(progress, 'Verified rePatch folder created. Original game unchanged.', 1)
    return output
