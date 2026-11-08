"""Hash-locked PS3 DLC overlays. No installation, decryption or license access.

Profiles are declarative. Only known EDAT inputs are patched; unrelated files
are neither copied nor modified. Base-game dependencies are checked by bytes.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import zipfile

from .core import (Asset, GitHubClient, PatchError, cache_directory, check_cancel,
                   decode, engine_context, report, sha256_file, valid_hash, valid_size)
from .solutions import output_name, publish_directory
from .vita_repatch import no_links, require

SCHEMA = 'retro-trans-ps3-dlc-v1'
PROFILE = 'PS3-DLC.json'
SUFFIX = '-PS3-DLC-patches.zip'
MAX_PROFILE = 256 * 1024
MAX_ZIP = 512 * 1024**2
MAX_EDAT = 256 * 1024**2
GUIDE = ('Install the matching English base game and original DLC first. Close the game/emulator. '
         'Back up the installed DLC files, then copy ONLY the generated .EDAT files into '
         'dev_hdd0/game/<DLC title ID>/USRDIR/DLC (RPCS3 or your modified PS3). '
         'Keep existing licenses, other DLC and saved games. No installation is performed by this tool. '
         'When updating the base game, refresh only its old installation cache; do not delete the DLC. '
         'PS3 hardware gameplay needs separate testing.')


def version(value):
    require(isinstance(value, str) and re.fullmatch(r'0\.\d+\.\d+', value), 'Invalid DLC build version.')
    return tuple(map(int, value.split('.')))


def identity(row, maximum=MAX_EDAT):
    require(isinstance(row, dict) and set(row) == {'bytes', 'sha256'}, 'Invalid DLC file identity.')
    require(0 < valid_size(row['bytes']) <= maximum, 'DLC file exceeds its size limit.')
    require(row['sha256'] == valid_hash(row['sha256']), 'Use lowercase SHA-256 identities.')


def validate(data):
    try:
        require(isinstance(data, dict) and set(data) ==
                {'schema', 'game_id', 'name', 'version', 'disc_id', 'dlc_title_id', 'base', 'packs'},
                'Unsupported DLC profile fields.')
        require(data['schema'] == SCHEMA, 'Unsupported DLC profile schema.')
        version(data['version'])
        require(isinstance(data['game_id'], str) and re.fullmatch(r'[a-z0-9-]{1,100}', data['game_id']),
                'Invalid DLC game ID.')
        require(isinstance(data['name'], str) and 0 < len(data['name']) <= 150 and
                all(ord(c) >= 32 for c in data['name']), 'Invalid DLC title.')
        for key in ('disc_id', 'dlc_title_id'):
            require(isinstance(data[key], str) and re.fullmatch(r'[A-Z]{4}\d{5}', data[key]), 'Invalid PS3 title ID.')
        base = data['base']
        require(isinstance(base, dict) and set(base) == {'version', 'iso', 'files'}, 'Invalid base-game dependency.')
        version(base['version']); identity(base['iso'], 64 * 1024**3)
        # Exact executable AND font assets; never trust a version label or local manifest alone.
        require(isinstance(base['files'], dict) and set(base['files']) == {'EBOOT.BIN', 'TPACKPS3.CPK'},
                'DLC dependency must identify the executable and fonts.')
        for item in base['files'].values():
            identity(item, 4 * 1024**3)
        require(isinstance(data['packs'], list) and 1 <= len(data['packs']) <= 256, 'Invalid DLC pack count.')
        names, ids, patches = set(), set(), set()
        for row in data['packs']:
            require(isinstance(row, dict) and set(row) == {'file', 'content_id', 'source', 'target', 'patch'},
                    'Invalid DLC pack fields.')
            name = output_name(row['file'])
            require(re.fullmatch(r'[A-Za-z0-9_-]+\.EDAT', name), 'Only flat .EDAT outputs are supported.')
            cid = row['content_id']
            require(isinstance(cid, str) and re.fullmatch(r'[A-Z]{2}\d{4}-' + data['dlc_title_id'] +
                    r'_00-[A-Z0-9_]{16}', cid), 'DLC content ID does not match its title.')
            require(name.casefold() not in names and cid not in ids, 'Duplicate DLC file or content ID.')
            names.add(name.casefold()); ids.add(cid)
            identity(row['source']); identity(row['target'])
            patch = row['patch']
            require(isinstance(patch, dict) and set(patch) == {'name', 'bytes', 'sha256'}, 'Invalid DLC delta.')
            output_name(patch['name'])
            require(patch['name'].endswith('.xdelta') and patch['name'].casefold() not in patches,
                    'Duplicate or invalid DLC delta name.')
            patches.add(patch['name'].casefold())
            identity({k: patch[k] for k in ('bytes', 'sha256')})
        require(sum(p['patch']['bytes'] for p in data['packs']) <= MAX_ZIP, 'DLC payload is too large.')
        return data
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise PatchError('Malformed DLC profile.') from exc


def read_profile(raw):
    require(len(raw) <= MAX_PROFILE, 'DLC profile is too large.')
    def unique(pairs):
        result = {}
        for k, v in pairs:
            require(k not in result, 'Duplicate JSON field in DLC profile.')
            result[k] = v
        return result
    try:
        return validate(json.loads(raw, object_pairs_hook=unique))
    except (ValueError, UnicodeError) as exc:
        raise PatchError('Unreadable DLC profile.') from exc


def matches(path, expected, cancel=None, progress=None):
    no_links(path)
    return (path.is_file() and path.stat().st_size == expected['bytes'] and
            sha256_file(path, cancel, progress) == expected['sha256'])


def edat_header(path, cid):
    with Path(path).open('rb') as stream:
        header = stream.read(128)
    require(len(header) == 128 and header[:4] == b'NPD\0' and
            header[16:64].rstrip(b'\0') == cid.encode('ascii'), 'DLC content ID/header mismatch: ' + Path(path).name)
    return header


def base_files(base, data, cancel=None, progress=None):
    base = no_links(base)
    if base.is_file():
        require(matches(base, data['base']['iso'], cancel, progress),
                'Base ISO does not match required English build ' + data['base']['version'] + '.')
        return [(base, data['base']['iso'])]
    require(base.is_dir(), 'Select the matching English ISO or extracted game folder.')
    roots = [base, base / 'USRDIR', base / 'PS3_GAME' / 'USRDIR']
    roots = [p for p in roots if (p / 'EBOOT.BIN').is_file()]
    require(len(roots) == 1, 'Select one extracted game folder containing EBOOT.BIN and TPACKPS3.CPK.')
    fonts = [roots[0] / 'TPACKPS3.CPK', roots[0] / 'DATA/TABATA/TPACKPS3.CPK']
    fonts = [p for p in fonts if p.is_file()]
    require(len(fonts) == 1, 'Select a game folder with exactly one matching TPACKPS3.CPK.')
    checked = [(roots[0] / 'EBOOT.BIN', data['base']['files']['EBOOT.BIN']),
               (fonts[0], data['base']['files']['TPACKPS3.CPK'])]
    for path, info in checked:
        require(matches(path, info, cancel, progress),
                'Base executable/fonts do not match required English build ' + data['base']['version'] + '.')
    return checked


def select_packs(source, data, cancel=None, progress=None):
    source = no_links(source)
    require(source.is_dir(), 'Select your original DLC folder (not a PKG or license).')
    roots = [source, source / 'USRDIR' / 'DLC', source / data['dlc_title_id'] / 'USRDIR' / 'DLC']
    found, ignored = [], []
    by_name = {p['file'].casefold(): p for p in data['packs']}
    seen = set()
    for root in roots:
        no_links(root)
        if not root.is_dir():
            continue
        for path in sorted(root.iterdir()):
            check_cancel(cancel)
            if path.suffix.lower() != '.edat':
                continue
            no_links(path)
            row = by_name.get(path.name.casefold())
            if row is None:
                ignored.append(path.name)
                continue
            require(row['file'] not in seen, 'Duplicate DLC pack in the selected folder: ' + row['file'])
            seen.add(row['file'])
            edat_header(path, row['content_id'])
            if matches(path, row['target'], cancel, progress):
                mode = 'current'
            else:
                require(matches(path, row['source'], cancel, progress),
                        'Unsupported or modified DLC: ' + path.name + '. Restore its exact original file.')
                mode = 'patch'
            found.append((path, row, mode))
    require(found, 'No supported DLC packs found. Select the folder containing the original .EDAT files.')
    return found, ignored


def open_bundle(path, expected=None, cancel=None):
    """Validate the ENTIRE flat archive before decoding any component."""
    path = no_links(path)
    require(path.is_file() and 0 < path.stat().st_size <= MAX_ZIP, 'Invalid DLC patch ZIP size.')
    try:
        archive = zipfile.ZipFile(path)
        infos = archive.infolist()
        require(1 < len(infos) <= 257, 'Invalid DLC ZIP inventory.')
        seen = set()
        for info in infos:
            output_name(info.filename)
            require(info.filename.casefold() not in seen and not info.is_dir() and not info.flag_bits & 1 and
                    stat.S_IFMT(info.external_attr >> 16) in (0, stat.S_IFREG), 'Unsafe or duplicate DLC ZIP entry.')
            seen.add(info.filename.casefold())
            require(info.file_size <= MAX_EDAT, 'DLC ZIP member too large.')
        profile_info = archive.getinfo(PROFILE)
        require(profile_info.file_size <= MAX_PROFILE, 'DLC profile is too large.')
        raw = archive.read(PROFILE)
        data = read_profile(raw)
        require(expected is None or raw == expected, 'Downloaded and embedded DLC profiles differ.')
        expected_names = {PROFILE} | {p['patch']['name'] for p in data['packs']}
        require({i.filename for i in infos} == expected_names, 'Undeclared or missing DLC ZIP files.')
        require(sum(i.file_size for i in infos) <= MAX_ZIP + MAX_PROFILE, 'DLC ZIP expands beyond its limit.')
        for row in data['packs']:
            item = archive.getinfo(row['patch']['name'])
            require(item.file_size == row['patch']['bytes'], 'DLC delta size mismatch.')
            h = hashlib.sha256()
            with archive.open(item) as stream:
                while True:
                    check_cancel(cancel)
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    h.update(chunk)
            require(h.hexdigest() == row['patch']['sha256'], 'DLC delta checksum mismatch.')
        return archive, data
    except BaseException as exc:
        if 'archive' in locals():
            archive.close()
        if isinstance(exc, (zipfile.BadZipFile, KeyError)):
            raise PatchError('Invalid DLC patch ZIP.') from exc
        raise


def discover(source, base, client=None, cache=None, cancel=None, progress=None):
    """Only query the registered Z3 repository, never scan an organization.

    First implementation: public releases only; a local ZIP is always usable.
    No catalog schema changes or publication side effects.
    """
    from . import game_library
    client, cache = client or GitHubClient(), cache or cache_directory()
    library = game_library.load(client, cache, cancel, progress)
    games = [g for g in library['games'] if g['game_id'] == 'srw-z3-jigoku-ps3' and
             {'platform': 'PS3', 'kind': 'title-id', 'id': 'BLJS10256'} in g['package_ids']]
    require(len(games) == 1, 'Z3 PS3 is not uniquely registered. Use a reviewed local DLC patch ZIP.')
    repo = games[0]['repo']
    from .catalog import load_catalog
    known = {(r['repo'], r['tag']): r.get('ps3_dlc') for r in load_catalog(cache).data.get('releases', [])}
    candidates = [r for r in client.releases(repo, cancel) if re.fullmatch(r'v?0\.\d+\.\d+', r.get('tag_name', ''))]
    candidates.sort(key=lambda r: version(r['tag_name'].lstrip('v')), reverse=True)
    reasons = []
    for release in candidates:
        check_cancel(cancel)
        assets = release.get('assets', [])
        profiles = [a for a in assets if a.get('name') == PROFILE]
        if not profiles:
            continue
        zips = [a for a in assets if a.get('name', '').endswith(SUFFIX)]
        require(len(profiles) == len(zips) == 1, 'Ambiguous DLC release assets.')
        def asset(item, maximum):
            name = output_name(item['name'])
            url = 'https://github.com/{}/releases/download/{}/{}'.format(repo, release['tag_name'], name)
            require(item.get('browser_download_url') == url, 'Invalid DLC download address.')
            require(isinstance(item.get('digest'), str) and item['digest'].startswith('sha256:'),
                    'DLC release lacks publisher checksums.')
            require(0 < valid_size(item['size']) <= maximum, 'DLC download exceeds its limit.')
            return Asset(name, url, item['size'], valid_hash(item['digest'][7:]))
        profile_asset, zip_asset = asset(profiles[0], MAX_PROFILE), asset(zips[0], MAX_ZIP)
        pinned = known.get((repo, release['tag_name']))
        if pinned:
            for key, value in (('profile', profile_asset), ('archive', zip_asset)):
                require(pinned.get(key) == dict(url=value.url, bytes=value.size, sha256=value.sha256),
                        'Published DLC assets differ from the verified catalog.')
        profile = client.download(profile_asset, cache, cancel, progress)
        raw = profile.read_bytes(); data = read_profile(raw)
        require(data['game_id'] == games[0]['game_id'] and data['disc_id'] == 'BLJS10256' and
                data['dlc_title_id'] == 'NPJB00520' and data['version'] == release['tag_name'].lstrip('v'),
                'DLC profile/release identity mismatch.')
        try:
            base_files(base, data, cancel, progress)
            select_packs(source, data, cancel, progress)
        except PatchError as exc:
            from .core import Cancelled
            if isinstance(exc, Cancelled):
                raise
            reasons.append(str(exc)); continue
        return client.download(zip_asset, cache, cancel, progress), raw
    raise PatchError('No compatible public DLC translation found. Use a local DLC patch ZIP.' +
                     (' ' + reasons[0] if reasons else ''))


def apply(source, base, output, bundle=None, client=None, cache=None, cancel=None, progress=None):
    client, cache = client or GitHubClient(), cache or cache_directory()
    source, base, output = no_links(source), no_links(base), no_links(output)
    require(not os.path.lexists(output) and output.parent.is_dir(), 'Choose a new output folder in an existing parent.')
    for input_path in (source, base):
        require(output.resolve() != input_path.resolve() and input_path.resolve() not in output.resolve().parents,
                'Output must be outside the selected input folders.')
    raw = None
    if not bundle:
        bundle, raw = discover(source, base, client, cache, cancel, progress)
    archive, data = open_bundle(bundle, raw, cancel)
    with archive:
        checked_base = base_files(base, data, cancel, progress)
        selected, ignored = select_packs(source, data, cancel, progress)
        report(progress, '{} supported DLC packs; {} unrelated EDAT files left alone.'.format(len(selected), len(ignored)), 0)
        required = sum(r['target']['bytes'] for _, r, _ in selected) + sum(r['patch']['bytes'] for r in data['packs'])
        require(shutil.disk_usage(output.parent).free > required + 32 * 1024**2, 'Not enough space for DLC output.')
        with tempfile.TemporaryDirectory(prefix='.retro-trans-dlc-', dir=str(output.parent)) as tmp:
            stage = Path(tmp); result = stage / 'result'; result.mkdir()
            # Verify all deltas, even those the user does not own. Never extract arbitrary ZIP paths.
            for row in data['packs']:
                check_cancel(cancel)
                patch = row['patch']; h = hashlib.sha256()
                with archive.open(patch['name']) as stream, (stage / patch['name']).open('xb') as dest:
                    while True:
                        check_cancel(cancel)
                        chunk = stream.read(1024 * 1024)
                        if not chunk:
                            break
                        h.update(chunk); dest.write(chunk)
                require(h.hexdigest() == patch['sha256'], 'DLC delta checksum mismatch.')
            with engine_context(client, cache, cancel, progress) as engine:
                for index, (path, row, mode) in enumerate(selected):
                    check_cancel(cancel)
                    original_header = edat_header(path, row['content_id'])
                    target = result / row['file']
                    if mode == 'current':
                        shutil.copyfile(path, target)
                    else:
                        decode(engine, path, stage / row['patch']['name'], target, row['target']['bytes'], cancel, progress)
                    require(matches(target, row['target'], cancel, progress), 'Translated DLC checksum mismatch.')
                    require(edat_header(target, row['content_id']) == original_header,
                            'DLC license/content header changed; output rejected.')
                    report(progress, 'Verified ' + row['file'], (index + 1) / len(selected))
            # Recheck sources and dependencies before exposing any completed output.
            for path, row, mode in selected:
                require(matches(path, row['target'] if mode == 'current' else row['source'], cancel), 'DLC input changed.')
            for path, info in checked_base:
                require(matches(path, info, cancel), 'Base game changed during DLC patching.')
            receipt = {'schema': 1, 'version': data['version'], 'base_version': data['base']['version'],
                       'dlc_title_id': data['dlc_title_id'], 'files': {r['file']: r['target'] for _, r, _ in selected},
                       'ignored_edat_files': ignored, 'installed': False}
            (result / 'DLC-RESULT.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
            (result / 'INSTALL.txt').write_text(GUIDE.replace('<DLC title ID>', data['dlc_title_id']) + '\n', encoding='utf-8')
            check_cancel(cancel); no_links(output)
            require(not os.path.lexists(output), 'Output appeared while patching; nothing overwritten.')
            publish_directory(result, output)
    return output, '{} DLC packs verified. Not installed.\n{}'.format(len(selected), GUIDE.replace('<DLC title ID>', data['dlc_title_id']))
