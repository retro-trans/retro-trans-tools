"""Refresh direct Vita entries for registered games; users never scan releases.

python -m retro_trans.game_library_builder --library retro_trans/resources/game-library.json
"""
import argparse
import copy
from pathlib import Path
import re

from . import game_library as library
from .catalog import atomic_json
from .core import PatchError, cache_directory


def validate_release(path, repo, data):
    """Pre-publication registration gate for binary, DCP and Vita profiles."""
    import json
    from .core import MAX_METADATA, validate_repo
    from . import vita_translation, vita_repatch
    library.validate(data)
    repo = validate_repo(repo)
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_METADATA + 1)
    library.require(len(raw) <= MAX_METADATA, 'Release profile is too large.')
    manifest = json.loads(raw)
    library.require(isinstance(manifest, dict), 'Release profile must be a JSON object.')
    if manifest.get('schema') in (vita_translation.SCHEMA, vita_repatch.SCHEMA):
        profile = vita_translation if manifest['schema'] == vita_translation.SCHEMA else vita_repatch
        manifest = profile.read_description(raw)
        content = manifest.get('content_id', manifest.get('package', {}).get('content_id'))
        matches = [g for g in data['games'] if g['repo'] == repo and
            ('PS Vita', 'vita-content-id', content) in library.package_ids(g['package_ids'])]
        library.require(len(matches) == 1, 'Register the Vita content ID before releasing.')
    else:
        if manifest.get('format') == 'DCP':
            from .dcp_automatic import validate_manifest
        else:
            from .catalog import validate_manifest
        library.validate_registration(validate_manifest(manifest), repo, data)


def release_entries(repo, release, client, cache, games):
    from . import vita_translation, vita_repatch
    from .vita_downloads import asset
    tag = release.get('tag_name', '')
    if release.get('draft') or release.get('prerelease') or not re.fullmatch(r'v0\.\d+\.\d+', tag):
        return []
    items = release.get('assets', [])
    library.require(isinstance(items, list) and all(isinstance(i, dict) for i in items), 'Invalid release assets.')
    library.require(len({i['name'] for i in items}) == len(items), 'Duplicate release asset names.')
    result = []
    for mode, profile in (('pkg', vita_translation), ('repatch', vita_repatch)):
        profiles = [i for i in items if i['name'] == profile.MANIFEST]
        if not profiles:
            continue
        metadata = asset(profiles[0], repo, tag, profile.MAX_METADATA)
        data = profile.read_description(client.download(metadata, cache).read_bytes())
        package = data.get('package', {})
        # Old hardware-only overlays are still available through the legacy path.
        if not package:
            continue
        content = data.get('content_id', package.get('content_id'))
        matching = [g for g in games if g['repo'] == repo and
            ('PS Vita', 'vita-content-id', content) in library.package_ids(g['package_ids'])]
        library.require(len(matching) == 1, 'Register the Vita content ID in game-library.json before releasing: ' + repo)
        library.require(data['build'] == tag[1:], 'Vita profile version differs from release.')
        zips = [i for i in items if i['name'].endswith(library.MODES[mode][1])]
        library.require(len(zips) == 1, 'Vita release requires one matching patch ZIP.')
        archive = asset(zips[0], repo, tag, profile.MAX_ZIP)
        def record(item, checked):
            return dict(id=item['id'], name=checked.name, bytes=checked.size, sha256=checked.sha256)
        result.append(dict(game_id=matching[0]['game_id'], repo=repo, version=tag[1:], mode=mode,
            content_id=content, package={k: package[k] for k in ('bytes', 'sha256')},
            profile=record(profiles[0], metadata), archive=record(zips[0], archive)))
    return result


def refresh(previous, client, cache, allow_private=False):
    library.validate(previous)
    result = copy.deepcopy(previous)
    repos = sorted({g['repo'] for g in previous['games']
                    if any(p['kind'] == 'vita-content-id' for p in g['package_ids'])})
    entries = []
    for repo in repos:
        # Never export private release metadata into the public, bundled library.
        info = client.json('https://api.github.com/repos/' + repo)
        library.require(isinstance(info, dict) and type(info.get('private')) is bool and
                        info.get('full_name', '').casefold() == repo.casefold(), 'Invalid repository visibility metadata.')
        library.require(allow_private or not info['private'], 'Private releases require a separate local library.')
        for release in client.releases(repo):
            entries.extend(release_entries(repo, release, client, cache, previous['games']))
    result['vita_releases'] = entries
    return library.merge(previous, result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', default=str(library.PATH))
    parser.add_argument('--output')
    parser.add_argument('--cache')
    parser.add_argument('--allow-private', action='store_true', help='Only for a separate local library, never public resources.')
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--check', action='store_true', help='Validate the library without using the network.')
    actions.add_argument('--validate-release', help='Validate new-release registration from a binary, DCP or Vita manifest.')
    parser.add_argument('--repo', help='Release repository, required with --validate-release.')
    args = parser.parse_args()
    output = Path(args.output or args.library).resolve()
    try:
        previous = library.read(args.library)
        if args.validate_release:
            library.require(args.repo, '--validate-release requires --repo.')
            validate_release(args.validate_release, args.repo, previous)
            print('Release package IDs are registered in the game library.')
            return
        if args.check:
            print('Game library valid:', len(previous['games']), 'games,', len(previous['vita_releases']), 'Vita routes')
            return
        if args.allow_private:
            library.require(output.name == 'game-library.private.json' and
                library.PATH.parent.resolve() not in output.parents,
                'Private output must be game-library.private.json outside bundled resources.')
        from .vita_downloads import VitaReleaseClient
        cache = Path(args.cache) if args.cache else cache_directory() / 'library-builder'
        result = refresh(previous, VitaReleaseClient(cache=cache), cache, args.allow_private)
        atomic_json(output, result)
        print('Game library updated:', len(result['games']), 'games,', len(result['vita_releases']), 'Vita routes')
    except (PatchError, OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, 'Game library unchanged: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
