"""Verified DCP discovery for Automatic, without disguising DCPs as xdelta edges."""
from dataclasses import dataclass
import copy
import json
import os
from pathlib import Path
import re
import shlex
import urllib.parse

from .core import Asset, GitHubClient, PatchError, cache_directory, check_cancel, safe_name, sha256_file, valid_hash, valid_size, validate_repo
from . import dcp

MANIFEST = 'DCP-AUTOMATIC.json'
MINIMUM = '0.5.20'


def validate_manifest(data):
    from .catalog import clean_version, text_field, version_key
    try:
        if not isinstance(data, dict) or type(data.get('schema_version')) is not int or data['schema_version'] != 1:
            raise PatchError('Unsupported Automatic DCP manifest.')
        if data.get('format') != 'DCP' or data.get('platform') != 'Dreamcast':
            raise PatchError('Automatic DCP profiles must describe Dreamcast DCP packages.')
        for key in ('game_id', 'game_name', 'language'):
            text_field(data[key], key)
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', data['game_id']):
            raise PatchError('Invalid Automatic DCP game identity.')
        if clean_version(data['version']) == 'original' or data['minimum_app_version'] != MINIMUM:
            raise PatchError('Invalid Automatic DCP version requirements.')
        if not re.fullmatch(r'[a-f0-9]{40}', data['source_commit']):
            raise PatchError('Automatic DCP source commit is missing.')
        patches = data['patches']
        if not isinstance(patches, list) or not 1 <= len(patches) <= 20:
            raise PatchError('Invalid Automatic DCP patch list.')
        names, identities = set(), set()
        for row in patches:
            name = safe_name(row['patch'])
            if not name.endswith('.dcp') or name.casefold() in names:
                raise PatchError('Automatic DCP assets must be unique .dcp packages.')
            names.add(name.casefold())
            text_field(row['edition'], 'edition')
            if not re.fullmatch(r'[a-z0-9][a-z0-9-]*',row['edition']):
                raise PatchError('Automatic DCP edition must be a safe slug.')
            source_version = clean_version(row['metadata']['source_version'])
            if version_key(source_version) >= version_key(data['version']):
                raise PatchError('Automatic DCP profiles must move to a newer version.')
            key = (row['edition'], source_version)
            if key in identities:
                raise PatchError('Duplicate Automatic DCP source edition.')
            identities.add(key)
            valid_hash(row['sha256']); valid_size(row['bytes'])
            if not 0 < row['bytes'] <= 4 * 1024**3:
                raise PatchError('Automatic DCP package size is invalid.')
            metadata = row['metadata']
            if (type(metadata.get('retro_trans_dcp')) is not int or metadata['retro_trans_dcp'] != 1
                    or metadata['game_id'] != data['game_id'] or metadata['game_name'] != data['game_name']
                    or metadata['version'] != data['version'] or metadata['target_version'] != data['version']
                    or type(metadata['disc']) is not int or not 1 <= metadata['disc'] <= 99):
                raise PatchError('Automatic DCP package identity disagrees with its manifest.')
            for key in ('source_tree_sha256', 'target_tree_sha256', 'bootsector_invariant_sha256'):
                valid_hash(metadata[key])
            tracks = row['source_tracks']
            if not isinstance(tracks, list) or not 3 <= len(tracks) <= 99:
                raise PatchError('Automatic DCP requires every original companion track.')
            for track in tracks:
                valid_hash(track['sha256']); valid_size(track['bytes'])
                if track['bytes'] <= 0:
                    raise PatchError('Automatic DCP source tracks must not be empty.')
        return data
    except (KeyError, TypeError, AttributeError) as exc:
        raise PatchError('Incomplete Automatic DCP metadata.') from exc


def load_records(records):
    from .catalog import clean_version
    if not isinstance(records, list):
        raise PatchError('Invalid Automatic DCP catalog.')
    result, seen, sources, targets = [], set(), {}, {}
    for record in records:
        try:
            valid_hash(record['manifest_sha256'])
            repo = validate_repo(record['repo'])
            tag = clean_version(record['tag'])
            manifest = validate_manifest(record['manifest'])
            if tag != manifest['version'] or (repo, tag) in seen:
                raise PatchError('Duplicate or mismatched Automatic DCP release.')
            seen.add((repo, tag))
            prefix = 'https://github.com/'+repo+'/releases/download/'+urllib.parse.quote(record['tag'],safe='')+'/'
            if set(record['assets']) != {p['patch'] for p in manifest['patches']}:
                raise PatchError('Automatic DCP catalog has an unexpected asset inventory.')
            for row in manifest['patches']:
                family = (manifest['game_id'],row['edition'],manifest['language'])
                source_key = family+(row['metadata']['source_version'],)
                source_identity = (tuple((t['bytes'],t['sha256']) for t in row['source_tracks']),row['metadata']['source_tree_sha256'])
                if sources.setdefault(source_key,source_identity) != source_identity:
                    raise PatchError('Automatic DCP changed a known original/source identity.')
                target_key = family+(manifest['version'],)
                target_identity = (row['metadata']['target_tree_sha256'],row['metadata']['bootsector_invariant_sha256'],row['metadata']['disc'])
                if targets.setdefault(target_key,target_identity) != target_identity:
                    raise PatchError('Automatic DCP changed a known target game-file identity.')
                url = prefix+urllib.parse.quote(row['patch'])
                if record['assets'][row['patch']] != url:
                    raise PatchError('Automatic DCP download points outside its release.')
                result.append(dict(repo=repo, tag=record['tag'], game_id=manifest['game_id'],
                    game_name=manifest['game_name'], language=manifest['language'], version=manifest['version'],
                    prerelease=record.get('prerelease') is True,
                    row=copy.deepcopy(row), asset=Asset(row['patch'],url,row['bytes'],row['sha256'])))
        except (KeyError,TypeError,AttributeError) as exc:
            raise PatchError('Incomplete Automatic DCP catalog record.') from exc
    return result


def descriptor_tracks(path):
    """Read only flat, complete CUE/GDI sets. Never extract while scanning."""
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.suffix.lower() not in ('.cue','.gdi'):
        return []
    if path.stat().st_size > 256 * 1024:
        raise PatchError('Disc descriptor is oversized.')
    rows = path.read_text(encoding='utf-8-sig').splitlines()
    names = []
    if path.suffix.lower() == '.gdi':
        count = int(rows[0].strip())
        if not 3 <= count <= 99 or len([r for r in rows[1:] if r.strip()]) != count:
            raise PatchError('Invalid Dreamcast GDI track count.')
        for index,line in enumerate(r for r in rows[1:] if r.strip()):
            fields = shlex.split(line)
            if len(fields) != 6 or int(fields[0]) != index+1 or any(int(fields[i]) < 0 for i in (1,2,3,5)):
                raise PatchError('Invalid Dreamcast GDI track row.')
            # Nonzero GDI offsets require separate raw-track fingerprints.
            if int(fields[5]) != 0:
                return []
            names.append(fields[4])
    else:
        for line in rows:
            if re.match(r'^\s*FILE\s',line,re.I):
                fields = shlex.split(line)
                if len(fields) != 3 or fields[2].upper() != 'BINARY':
                    raise PatchError('Automatic DCP expects binary CUE companion tracks.')
                names.append(fields[1])
    for name in names:
        safe_name(name)
    if not 3 <= len(names) <= 99 or len(set(n.casefold() for n in names)) != len(names):
        return []
    files = []
    for name in names:
        safe_name(name)
        track = path.parent/name
        if track.is_symlink() or not track.is_file():
            raise PatchError('Missing original disc companion track: '+name)
        files.append(track)
    return files


@dataclass
class DcpSource:
    descriptor: Path
    profiles: tuple

    @property
    def version(self): return self.profiles[0]['row']['metadata']['source_version']
    @property
    def label(self):
        p = self.profiles[0]
        return '{} / {} / {} / {} ({})'.format(p['game_name'],p['row']['edition'],p['language'],self.version,
            'experimental DCP' if p['prerelease'] else 'DCP')


@dataclass
class DcpPlan:
    source: DcpSource
    profile: dict

    @property
    def edges(self): return (self.profile['asset'],)
    @property
    def version(self): return self.profile['version']
    @property
    def summary(self): return self.source.version+' → '+self.version+' • DCP download, rebuilt disc verified'
    @property
    def details(self): return self.source.label+'\n'+self.summary+'\n'+self.profile['asset'].name


@dataclass(frozen=True)
class DcpVersion:
    version: str


def recognize(path, profiles, cancel=None, progress=None):
    from .catalog import version_key
    path = Path(path)
    check_cancel(cancel)
    if path.is_dir() or path.suffix.lower() not in ('.cue','.gdi') or not profiles:
        return []
    try:
        tracks = descriptor_tracks(path)
    except (OSError, UnicodeError,ValueError) as exc:
        raise PatchError('Could not read the Dreamcast disc descriptor.') from exc
    sizes = [p.stat().st_size for p in tracks]
    candidates = [p for p in profiles if [r['bytes'] for r in p['row']['source_tracks']] == sizes]
    if not candidates:
        return []
    hashes = [sha256_file(p,cancel,progress,'Identifying '+p.name) for p in tracks]
    found = {}
    for profile in candidates:
        if [r['sha256'] for r in profile['row']['source_tracks']] == hashes:
            key = (profile['game_id'],profile['row']['edition'],profile['language'],profile['row']['metadata']['source_version'])
            found.setdefault(key,[]).append(profile)
    return [DcpSource(path.resolve(),tuple(sorted(p,key=lambda v:version_key(v['version']),reverse=True))) for p in found.values()]


def versions(source):
    from .catalog import version_key
    return sorted({p['version'] for p in source.profiles},key=version_key,reverse=True)


def plan(source, target='Latest'):
    from .catalog import clean_version, version_key
    values = versions(source)
    selected = values[0] if target == 'Latest' else values[-1] if target == 'Next version only' else clean_version(target)
    candidates = [p for p in source.profiles if p['version'] == selected]
    if not candidates:
        raise PatchError('No compatible DCP from this source to the selected version.')
    return DcpPlan(source,min(candidates,key=lambda p:p['asset'].size))


def apply(plan, output, *, format='GDI', client=None, cache=None, cancel=None, progress=None):
    if os.path.lexists(output):
        raise PatchError('Choose a new DCP output folder; existing outputs are preserved.')
    if format not in ('GDI','CUE/BIN','CHD'):
        raise PatchError('Unsupported Automatic DCP output format.')
    profile = plan.profile
    # Rehash all tracks again at Patch, not just when the UI selected the disc.
    found = recognize(plan.source.descriptor,[profile],cancel,progress)
    if not found:
        raise PatchError('The selected original disc changed. Select it again before patching.')
    client = client or GitHubClient()
    patch = client.download(profile['asset'],Path(cache or cache_directory())/'dcp',cancel,progress)
    checked = dcp.inspect_patch(patch)
    if checked['metadata'] != profile['row']['metadata']:
        raise PatchError('Downloaded DCP metadata does not match the Automatic catalog.')
    return dcp.apply(plan.source.descriptor,patch,output,format=format,cancel=cancel,progress=progress)


def release_record(repo, release, client, reviewed=None):
    """Validate publisher metadata, every actual DCP and its embedded tree IDs."""
    import tempfile
    from .catalog import clean_version
    assets = {a['name']:a for a in release['assets']}
    if len(assets) != len(release['assets']):
        raise PatchError('Duplicate DCP release assets.')
    if MANIFEST not in assets:
        if reviewed: raise PatchError('Published Automatic DCP manifest was removed.')
        return None
    repo = validate_repo(repo)
    prefix = 'https://github.com/'+repo+'/releases/download/'+urllib.parse.quote(release['tag_name'],safe='')+'/'
    def fetch(name):
        a = assets[name]
        if a['browser_download_url'] != prefix+urllib.parse.quote(name) or not str(a.get('digest','')).startswith('sha256:'):
            raise PatchError('DCP asset requires a publisher checksum and canonical release URL.')
        return Asset(name,a['browser_download_url'],valid_size(a['size']),valid_hash(a['digest'][7:]))
    description = fetch(MANIFEST)
    raw = client.read(description.url)
    import hashlib
    if len(raw) != description.size or hashlib.sha256(raw).hexdigest() != description.sha256:
        raise PatchError('Automatic DCP manifest failed its publisher checksum.')
    try: manifest = validate_manifest(json.loads(raw))
    except (ValueError,UnicodeError) as exc: raise PatchError('Invalid Automatic DCP manifest JSON.') from exc
    if clean_version(release['tag_name']) != manifest['version']:
        raise PatchError('Automatic DCP release version does not match its tag.')
    if release.get('prerelease') and manifest.get('allow_prerelease') is not True:
        raise PatchError('Experimental DCP releases must explicitly opt into Automatic discovery.')
    if {n for n in assets if n.lower().endswith('.dcp')} != {p['patch'] for p in manifest['patches']}:
        raise PatchError('Automatic DCP manifest must declare every DCP package.')
    with tempfile.TemporaryDirectory(prefix='dcp-catalog-validation-') as temporary:
        for row in manifest['patches']:
            asset = fetch(row['patch'])
            if (asset.size,asset.sha256) != (row['bytes'],row['sha256']):
                raise PatchError('Published DCP asset differs from Automatic metadata.')
            downloaded = client.download(asset,temporary)
            if dcp.inspect_patch(downloaded)['metadata'] != row['metadata']:
                raise PatchError('DCP package tree identities differ from Automatic metadata.')
    record = dict(repo=repo,tag=release['tag_name'],manifest=manifest,prerelease=bool(release.get('prerelease')),
        manifest_sha256=description.sha256,assets={p['patch']:prefix+urllib.parse.quote(p['patch']) for p in manifest['patches']})
    if reviewed and reviewed != record:
        raise PatchError('Published Automatic DCP identity was replaced.')
    load_records([record])
    return record
