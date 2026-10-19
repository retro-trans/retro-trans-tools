"""Fetch standard release manifests and publish a complete immutable catalog."""

import argparse
import copy
import hashlib
import json
import os
import re
import sys
from pathlib import Path
import shutil
import tempfile
import urllib.parse

from .core import GitHubClient, PatchError, Cancelled, Asset, safe_name, validate_repo, valid_hash
from .catalog import Catalog, RESOURCE_DIR, assert_immutable, atomic_json, validate_manifest
from .release import validate_directory


def release_record(repo, release, client, reviewed=None):
    tag = release["tag_name"]
    assets = {a["name"]: a for a in release["assets"]}
    if len(assets) != len(release['assets']):
        raise PatchError('Duplicate release assets.')
    manifests = [name for name in assets if name.startswith("BUILD-MANIFEST") and name.endswith(".json")]
    if not manifests:
        if reviewed:
            raise PatchError('Published BUILD-MANIFEST.json was removed.')
        return None
    if manifests != ["BUILD-MANIFEST.json"]:
        raise PatchError("New releases require exactly one canonical BUILD-MANIFEST.json: " + repo + " " + tag)
    with tempfile.TemporaryDirectory(prefix="catalog-validation-") as temporary:
        directory = Path(temporary)
        def fetch(name):
            safe_name(name)
            if name not in assets:
                raise PatchError("Missing release asset: " + name)
            a = assets[name]
            url = a["browser_download_url"]
            expected = "https://github.com/{}/releases/download/{}/{}".format(
                repo, urllib.parse.quote(tag, safe=""), urllib.parse.quote(name))
            if url != expected:
                raise PatchError("Unexpected release download URL.")
            return a, url
        def read_verified(name):
            a, url = fetch(name)
            raw = client.read(url)
            if len(raw) != a["size"] or (a.get("digest") and a["digest"] != "sha256:" + hashlib.sha256(raw).hexdigest()):
                raise PatchError("Release asset integrity mismatch: " + name)
            return raw
        raw = read_verified("BUILD-MANIFEST.json")
        manifest = validate_manifest(json.loads(raw))
        imported = None
        if reviewed and 'solution_import' in reviewed:
            evidence = reviewed['solution_import']
            if (not isinstance(evidence, dict) or type(evidence.get('schema_version')) is not int
                    or evidence['schema_version'] != 1 or not isinstance(evidence.get('reason'), str)
                    or not evidence['reason'].strip()):
                raise PatchError('Invalid reviewed solution import.')
            digest = valid_hash(evidence.get('manifest_sha256'))
            if manifest['schema_version'] != 1 or hashlib.sha256(raw).hexdigest() != digest:
                raise PatchError('The published manifest changed since its solution metadata was reviewed.')
            imported = copy.deepcopy(manifest)
            imported['schema_version'] = 2
            imported['solutions'] = copy.deepcopy(reviewed['manifest'].get('solutions'))
            validate_manifest(imported)
        vita_record, vita_archive, vita_names = None, None, set()
        from . import vita_repatch as vita
        vita_zips = [name for name in assets if name == vita.ARCHIVE or name.endswith(vita.ZIP_SUFFIX)]
        if len(vita_zips) > 1:
            raise PatchError('Release must contain at most one Vita patch ZIP.')
        archive_name = vita_zips[0] if vita_zips else None
        legacy_vita = (repo, tag) == (vita.REPO, vita.TAG)
        if archive_name and vita.MANIFEST not in assets:
            raise PatchError('Vita ZIP requires its published profile.')
        if vita.MANIFEST in assets:
            if not legacy_vita and not re.fullmatch(r'v0\.\d+\.\d+', tag):
                raise PatchError('Vita extras require a numeric v0.x.y release tag.')
            vita_raw = read_verified(vita.MANIFEST)
            description = vita.read_description(vita_raw)
            if not legacy_vita:
                minimum = description.get('minimum_app_version', '')
                if (description['build'] != tag[1:] or manifest['version'] != tag[1:]
                        or 'package' not in description or not archive_name
                        or not archive_name.endswith(vita.ZIP_SUFFIX)
                        or not minimum or tuple(map(int, minimum.split('.'))) < (0, 5, 14)):
                    raise PatchError('Vita extras require matching versions, original PKG identity, '
                                     'one discoverable ZIP and a supported minimum app version.')
                if repo == vita.REPO and (description['title_id'] != 'PCSG00264' or minimum != '0.5.16'):
                    raise PatchError('New Z3 Vita releases require matching versions, original PKG identity, '
                                     'one discoverable ZIP and app 0.5.16.')
            metadata, metadata_url = fetch(vita.MANIFEST)
            metadata_hash = hashlib.sha256(vita_raw).hexdigest()
            if metadata.get('digest') != 'sha256:' + metadata_hash:
                raise PatchError('Vita metadata requires a publisher checksum.')
            vita_record = dict(url=metadata_url, bytes=len(vita_raw), sha256=metadata_hash,
                               title_id=description['title_id'], app_version=description['app_version'],
                               build=description['build'])
            if reviewed and reviewed.get('vita_repatch') and reviewed['vita_repatch'] != vita_record:
                raise PatchError('Published Vita profile identity changed.')
            for row in description['files']:
                patch = row['patch']
                name = patch['name']
                if not name.startswith('VITA-') or name in {p['patch'] for p in manifest['patches']}:
                    raise PatchError('Vita extras must use separate VITA- patch names.')
                # A verified complete ZIP replaces missing individual assets.
                # Existing bare assets, if any, must still match the profile.
                if name not in assets and archive_name:
                    continue
                a, url = fetch(name)
                if a['size'] != patch['bytes'] or a.get('digest') != 'sha256:' + patch['sha256']:
                    raise PatchError('Vita asset disagrees with its profile: ' + name)
                client.download(Asset(name, url, patch['bytes'], patch['sha256']), directory/'vita-cache')
                vita_names.add(name)
            if archive_name:
                a, url = fetch(archive_name)
                digest = a.get('digest') or ''
                if not digest.startswith('sha256:') or not 0 < a['size'] <= vita.MAX_ARCHIVE:
                    raise PatchError('Vita patch ZIP requires a checksum and bounded size.')
                asset = Asset(archive_name, url, a['size'], valid_hash(digest[7:]))
                vita_archive = dict(url=url, bytes=asset.size, sha256=asset.sha256)
                if reviewed and reviewed.get('vita_archive') and reviewed['vita_archive'] != vita_archive:
                    raise PatchError('Published Vita ZIP identity changed.')
                path = client.download(asset, directory/'vita-cache')
                with vita.archive_description(path, description):
                    pass
            elif reviewed and reviewed.get('vita_archive'):
                raise PatchError('Published Vita ZIP was removed.')
        elif reviewed and reviewed.get('vita_repatch'):
            raise PatchError('Published Vita profile was removed.')
        if {p["patch"] for p in manifest["patches"]} | vita_names != {n for n in assets if n.lower().endswith((".xdelta", ".vcdiff"))}:
            raise PatchError("Uploaded patches do not exactly match the manifest.")
        (directory / "BUILD-MANIFEST.json").write_bytes(raw)
        for name in ("SHA256SUMS.txt", "VALIDATION.json"):
            (directory / name).write_bytes(read_verified(name))
        for patch in manifest["patches"]:
            a, url = fetch(patch["patch"])
            if a["size"] != patch["patch_bytes"] or (a.get("digest") and a["digest"] != "sha256:" + patch["patch_sha256"]):
                raise PatchError("Published asset disagrees with manifest: " + patch["patch"])
            path = client.download(Asset(patch["patch"], url, a["size"], patch["patch_sha256"]), directory / "cache")
            shutil.copyfile(path, directory / patch["patch"])
        # Supplemental credits/check reports can share the canonical checksum
        # file. Verify them too; never omit lines to make validation pass.
        checksummed = set()
        for line in (directory / 'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines():
            parts = line.split('  ', 1)
            if len(parts) != 2:
                raise PatchError('Invalid SHA256SUMS.txt.')
            digest, name = valid_hash(parts[0]), safe_name(parts[1])
            if name in checksummed:
                raise PatchError('Duplicate checksum entry.')
            checksummed.add(name)
            if not (directory / name).is_file():
                a, url = fetch(name)
                if (Path(name).suffix.lower() not in ('.json', '.txt', '.md', '.png', '.zip')
                        or not 0 < a['size'] <= 64 * 1024**2):
                    raise PatchError('Unsupported or oversized checksummed release extra: ' + name)
                if a.get('digest') and a['digest'] != 'sha256:' + digest:
                    raise PatchError('Checksummed release extra disagrees with publisher metadata: ' + name)
                path = client.download(Asset(name, url, a['size'], digest), directory / 'cache')
                shutil.copyfile(path, directory / name)
        validate_directory(directory)
    record = {"repo": repo, "tag": tag, "manifest": imported or manifest,
              "assets": {p["patch"]: assets[p["patch"]]["browser_download_url"] for p in manifest["patches"]}}
    if imported:
        record['solution_import'] = copy.deepcopy(reviewed['solution_import'])
    if vita_record:
        record['vita_repatch'] = vita_record
    if vita_archive:
        record['vita_archive'] = vita_archive
        minimum = description.get('minimum_app_version', '0.5.16')
        record['vita_min_app_version'] = ('0.5.4' if legacy_vita else
            '.'.join(map(str, max((0, 5, 16), tuple(map(int, minimum.split('.')))))))
    return record


def build_catalog(previous, client=None, repositories=None, rejections=None):
    """Strict by default; a supplied rejection list isolates failed releases."""
    client = client or GitHubClient()
    old = Catalog(previous)
    records = {(r["repo"], r["tag"]): copy.deepcopy(r) for r in previous["releases"]}
    selected = client.repositories() if repositories is None else [validate_repo(r) for r in repositories]
    def rejected(repo, tag, error):
        if rejections is None:
            raise error
        known = (repo, tag) in records if tag is not None else any(key[0] == repo for key in records)
        rejections.append(dict(repo=repo, tag=tag, error=str(error), action='retained' if known else 'skipped'))

    def catalog_data(items):
        data = dict(schema_version=1, releases=[items[k] for k in sorted(items)])
        if previous.get('withdrawn_releases'):
            data['withdrawn_releases'] = copy.deepcopy(previous['withdrawn_releases'])
        return data

    for repo in selected:
        if repo == "retro-trans/retro-trans-tools":
            continue
        try:
            releases = client.releases(repo)
        except Cancelled:
            raise
        except (PatchError, OSError, ValueError, KeyError, TypeError) as error:
            rejected(repo, None, error)
            continue
        for release in releases:
            tag = release.get('tag_name') if isinstance(release, dict) else None
            if not isinstance(tag, str):
                rejected(repo, None, PatchError('Release has an invalid tag.'))
                continue
            try:
                key = (repo, tag)
                existing = records.get(key)
                assets = {a["name"]: a for a in release["assets"]}
                # Legacy metadata has been reviewed/imported once. Still check
                # that remote patch bytes have not been replaced or removed.
                if existing and existing.get("legacy"):
                    for p in existing["manifest"]["patches"]:
                        asset = assets.get(p["patch"])
                        if not asset or asset["size"] != p["patch_bytes"] or (asset.get("digest") and asset["digest"] != "sha256:" + p["patch_sha256"]):
                            raise PatchError("A historical release asset changed: " + p["patch"])
                    continue
                record = release_record(repo, release, client, reviewed=existing)
                if record:
                    candidate = dict(records)
                    candidate[key] = record
                    # Catch cross-release identity/solution conflicts at the
                    # same boundary, before any candidate enters the catalog.
                    assert_immutable(old, Catalog(catalog_data(candidate)))
                    records = candidate
            except Cancelled:
                raise
            except (PatchError, OSError, ValueError, KeyError, TypeError) as error:
                rejected(repo, tag, error)
    result = catalog_data(records)
    assert_immutable(old, Catalog(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(RESOURCE_DIR / "catalog.json"))
    parser.add_argument("--repo", action="append", help="Validate only this repository; preserve other catalog entries.")
    parser.add_argument('--continue-on-error', action='store_true',
                        help='Report rejected releases and preserve their cached records; continue validating others.')
    parser.add_argument('--report', help='Write a JSON refresh report alongside the catalog.')
    args = parser.parse_args()
    path = Path(args.output)
    if args.report and Path(args.report).resolve() == path.resolve():
        parser.error('The refresh report must not overwrite the catalog.')
    try:
        previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"schema_version": 1, "releases": []}
        rejections = [] if args.continue_on_error else None
        result = build_catalog(previous, repositories=args.repo, rejections=rejections)
        if args.report:
            atomic_json(args.report, dict(schema_version=1, status='partial' if rejections else 'complete',
                releases=len(result['releases']), rejections=rejections or []))
        atomic_json(path, result)
        for item in rejections or []:
            message = '{} {}: {} ({})'.format(item['repo'], item['tag'] or '(repository)',
                                              item['error'], item['action'])
            if os.environ.get('GITHUB_ACTIONS') == 'true':
                escaped = message.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
                print('::warning::' + escaped)
            else:
                print('Catalog warning: ' + message, file=sys.stderr)
        print("Catalog validated:", len(result["releases"]), "releases")
    except (PatchError, OSError, ValueError, KeyError) as exc:
        parser.exit(1, "Catalog unchanged: " + str(exc) + "\n")


if __name__ == "__main__":
    main()
