"""Central cross-platform game IDs and direct, hash-locked Vita downloads."""
import copy
import json
from pathlib import Path
import re
import time

from .core import (Asset, Cancelled, GitHubClient, MAX_METADATA, PatchError,
                   cache_directory, check_cancel, report, valid_hash, valid_size, validate_repo)
from .catalog import RESOURCE_DIR, atomic_json, text_field, version_key

PATH = RESOURCE_DIR / 'game-library.json'
URL = 'https://raw.githubusercontent.com/retro-trans/retro-trans-tools/main/retro_trans/resources/game-library.json'
CONTENT_ID = r'[A-Z]{2}[0-9]{4}-[A-Z]{4}[0-9]{5}_00-[A-Z0-9_]{16}'
MODES = {'pkg': ('VITA-PKG.json', '-Vita-PKG-patches.zip', 64*1024**2),
         'repatch': ('VITA-REPATCH.json', '-Vita-rePatch-patches.zip', 256*1024**2)}


def require(condition, message):
    if not condition:
        raise PatchError(message)


def package_ids(rows):
    require(isinstance(rows, list) and 0 < len(rows) <= 100, 'Release needs package_ids for every platform.')
    seen = set()
    for row in rows:
        require(isinstance(row, dict) and set(row) == {'platform', 'kind', 'id'}, 'Invalid package ID record.')
        for key in row:
            text_field(row[key], 'package_ids.' + key)
        require(re.fullmatch(r'[a-z][a-z0-9-]{0,39}', row['kind']), 'Invalid package ID kind.')
        if row['kind'] == 'vita-content-id':
            require(row['platform'] == 'PS Vita' and re.fullmatch(CONTENT_ID, row['id']), 'Invalid Vita content ID.')
        key = (row['platform'], row['kind'], row['id'])
        require(key not in seen, 'Duplicate package ID.')
        seen.add(key)
    return seen


def identity(row, maximum):
    require(isinstance(row, dict) and set(row) == {'bytes', 'sha256'}, 'Invalid library binary identity.')
    require(0 < valid_size(row['bytes']) <= maximum, 'Invalid library binary size.')
    require(valid_hash(row['sha256']) == row['sha256'], 'Library hashes must be lowercase SHA-256.')


def asset(row, repo, mode, archive=False):
    require(isinstance(row, dict) and set(row) == {'id', 'name', 'bytes', 'sha256'}, 'Invalid library asset.')
    from .solutions import output_name
    name = output_name(row['name'])
    require(type(row['id']) is int and row['id'] > 0, 'Invalid library asset ID.')
    manifest, suffix, maximum = MODES[mode]
    require(name.endswith(suffix) if archive else name == manifest, 'Unexpected library asset name.')
    profile_limit = 256*1024 if mode == 'pkg' else MAX_METADATA
    identity({k: row[k] for k in ('bytes', 'sha256')}, maximum if archive else profile_limit)
    return Asset(name, 'https://api.github.com/repos/' + repo + '/releases/assets/' + str(row['id']),
                 row['bytes'], row['sha256'])


def release_key(row):
    return row['repo'], row['version'], row['mode']


def validate(data):
    require(isinstance(data, dict) and set(data) == {'schema_version', 'games', 'vita_releases'}
            and type(data['schema_version']) is int and data['schema_version'] == 1, 'Unsupported game library.')
    require(isinstance(data['games'], list) and len(data['games']) <= 10000 and
            isinstance(data['vita_releases'], list) and len(data['vita_releases']) <= 10000, 'Invalid game library inventory.')
    require(len(json.dumps(data, indent=2, ensure_ascii=False).encode('utf-8')) + 1 <= MAX_METADATA,
            'Game library is too large.')
    games = {}
    for game in data['games']:
        require(isinstance(game, dict) and set(game) == {'game_id', 'name', 'repo', 'package_ids'}, 'Invalid library game.')
        require(isinstance(game['game_id'], str) and re.fullmatch(r'[a-z0-9][a-z0-9-]*', game['game_id']), 'Invalid library game ID.')
        text_field(game['name'], 'name')
        validate_repo(game['repo'])
        key = (game['repo'], game['game_id'])
        require(key not in games, 'Duplicate library game.')
        games[key] = package_ids(game['package_ids'])
    seen = set()
    asset_ids = {}
    for row in data['vita_releases']:
        require(isinstance(row, dict) and set(row) == {'game_id', 'repo', 'version', 'mode', 'content_id',
                'package', 'profile', 'archive'}, 'Invalid library Vita release.')
        require(all(isinstance(row[k], str) for k in ('game_id', 'repo', 'version', 'mode', 'content_id')),
                'Invalid Vita library identity fields.')
        require(row['mode'] in MODES and
                re.fullmatch(r'0\.\d+\.\d+', row['version']), 'Invalid Vita release version or mode.')
        key = release_key(row)
        require(key not in seen, 'Conflicting library release identity.')
        seen.add(key)
        require(('PS Vita', 'vita-content-id', row['content_id']) in games.get((row['repo'], row['game_id']), set()),
                'Vita package ID is not registered in the game library.')
        identity(row['package'], 16*1024**3)
        for field in ('profile', 'archive'):
            value = row[field]
            asset(value, row['repo'], row['mode'], archive=field == 'archive')
            key = row['repo'], value['id']
            require(key not in asset_ids or asset_ids[key] == value, 'Conflicting published asset identity.')
            asset_ids[key] = value
    return data


def read(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_METADATA + 1)
    require(len(raw) <= MAX_METADATA, 'Game library is too large.')
    try:
        return validate(json.loads(raw))
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise PatchError('Invalid game library.') from exc


def merge(old, new):
    """Preserve known releases and reject changed published identities."""
    validate(old); validate(new)
    result = copy.deepcopy(old)
    games = {(g['repo'], g['game_id']): g for g in result['games']}
    for game in new['games']:
        key = game['repo'], game['game_id']
        if key in games:
            ids = package_ids(games[key]['package_ids'])
            games[key]['package_ids'].extend(copy.deepcopy(row) for row in game['package_ids']
                if (row['platform'], row['kind'], row['id']) not in ids)
            games[key]['name'] = game['name']
        else:
            games[key] = copy.deepcopy(game)
    releases = {release_key(row): row for row in result['vita_releases']}
    for row in new['vita_releases']:
        key = release_key(row)
        require(key not in releases or releases[key] == row, 'Published library release identity changed.')
        releases[key] = copy.deepcopy(row)
    result['games'] = [games[k] for k in sorted(games)]
    result['vita_releases'] = [releases[k] for k in sorted(releases)]
    return validate(result)


def load(client=None, cache=None, cancel=None, progress=None):
    """One raw-file refresh per hour; never enumerate repositories or releases."""
    check_cancel(cancel)
    client = client or GitHubClient()
    cache = Path(cache) if cache else cache_directory()
    current = read(PATH)
    path = cache / 'game-library-cache.json'
    checked_at = None
    try:
        with path.open('rb') as stream:
            raw = stream.read(MAX_METADATA + 1025)
        require(len(raw) <= MAX_METADATA + 1024, 'Cached game library is too large.')
        record = json.loads(raw)
        current = merge(current, record['data'])
        checked_at = record['checked_at']
    except (OSError, ValueError, KeyError, TypeError, PatchError):
        pass
    if not (type(checked_at) in (int, float) and 0 <= time.time() - checked_at < 3600):
        try:
            updated = merge(current, validate(client.json(URL, cancel)))
            check_cancel(cancel)
            current = updated
        except Cancelled:
            raise
        except (OSError, ValueError, KeyError, TypeError, PatchError):
            report(progress, 'Using the saved game library; online refresh is unavailable.', None)
        check_cancel(cancel)
        try:
            # Also back off after a failed refresh, without replacing valid data.
            atomic_json(path, {'checked_at': time.time(), 'data': current})
        except OSError:
            pass
    private = cache / 'game-library.private.json'
    if private.exists():
        current = merge(current, read(private))
    check_cancel(cancel)
    return current


def validate_registration(manifest, repo=None, library=None):
    """New releases must declare registered IDs for every platform edition."""
    library = read(PATH) if library is None else validate(library)
    declared = package_ids(manifest.get('package_ids'))
    platforms = {p.get('platform', manifest['platform']) for p in manifest.get('patches', [])} or {manifest['platform']}
    require(platforms <= {p[0] for p in declared}, 'Register package IDs for every release platform.')
    matches = [g for g in library['games'] if g['game_id'] == manifest.get('game_id') and
               (repo is None or g['repo'] == repo) and declared <= package_ids(g['package_ids'])]
    require(len(matches) == 1, 'Register this game and its package_ids in game-library.json before releasing.')
    return matches[0]
