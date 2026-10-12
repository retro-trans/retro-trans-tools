"""Discover hash-verified Vita release profiles without a game registry.

Original packages and licenses never leave the computer. Optional GitHub CLI
credentials are held in memory and sent only to api.github.com.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import re
import shutil
import subprocess
import urllib.parse
import urllib.request

from . import __version__, diagnostics
from .core import (Asset, GitHubClient, PatchError, cache_directory, check_cancel,
                   report, sha256_file, valid_hash, valid_size, validate_repo)
from .solutions import output_name
from .vita_repatch import no_links, require


class ApiRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        parsed = urllib.parse.urlsplit(new_url)
        require(parsed.scheme == 'https' and parsed.port in (None, 443) and not parsed.username and not parsed.password
                and (parsed.hostname in ('api.github.com', 'github.com', 'release-assets.githubusercontent.com')
                     or (parsed.hostname or '').endswith('.githubusercontent.com')),
                'Unexpected GitHub asset redirect.')
        redirected = super().redirect_request(request, fp, code, message, headers, new_url)
        if redirected is not None and parsed.hostname != urllib.parse.urlsplit(request.full_url).hostname:
            redirected.remove_header('Authorization')
        return redirected


class VitaReleaseClient(GitHubClient):
    """Use the existing local gh sign-in for private releases, when available."""
    def __init__(self):
        self._token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN') or ''
        if not self._token and shutil.which('gh'):
            try:
                result = subprocess.run(['gh', 'auth', 'token', '--hostname', 'github.com'],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    timeout=10, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if result.returncode == 0:
                    self._token = result.stdout.decode('ascii').strip()
            except (OSError, subprocess.TimeoutExpired, UnicodeError):
                pass

    def open(self, url):
        parsed = urllib.parse.urlsplit(url)
        if parsed.hostname != 'api.github.com' or not parsed.path.startswith(
                ('/repos/retro-trans/', '/orgs/retro-trans/')):
            return super().open(url)
        require(parsed.scheme == 'https' and parsed.port in (None, 443) and not parsed.username and not parsed.password
                and (not parsed.query or '/releases/assets/' not in parsed.path),
                'Unexpected Vita release API address.')
        headers = {'User-Agent': 'RetroTrans-Patcher/' + __version__,
                   'Accept': 'application/octet-stream' if '/releases/assets/' in parsed.path
                             else 'application/vnd.github+json'}
        if self._token:
            headers['Authorization'] = 'Bearer ' + self._token
        request = urllib.request.Request(url, headers=headers)
        handlers = [ApiRedirect()]
        context = self.tls_context()
        if context is not None:
            handlers.append(urllib.request.HTTPSHandler(context=context))
        try:
            diagnostics.event('network_open', host='api.github.com', endpoint='api')
            response = urllib.request.build_opener(*handlers).open(request, timeout=30)
            diagnostics.event('network_ok', host='api.github.com', http_status=response.status)
            return response
        except OSError as exc:
            diagnostics.exception(exc)
            raise PatchError('Could not download the Vita release from GitHub. Check your connection, '
                             'request limit or sign-in. Private releases require access through '
                             'GitHub CLI; a downloaded local patch ZIP also works.') from exc


def package_content(pkg):
    pkg = no_links(pkg)
    require(pkg.is_file(), 'Choose your original Vita PKG.')
    with pkg.open('rb') as stream:
        header = stream.read(256)
    require(len(header) == 256 and header[:4] == b'\x7fPKG', 'Choose your original Vita PKG.')
    try:
        content = header[48:96].rstrip(b'\0').decode('ascii')
    except UnicodeError as exc:
        raise PatchError('The PKG has an invalid content ID.') from exc
    require(re.fullmatch(r'[A-Z]{2}[0-9]{4}-[A-Z]{4}[0-9]{5}_00-[A-Z0-9_]{16}', content),
            'The PKG has an invalid content ID.')
    require(not content[7:16].startswith(('NP', 'BL', 'BC')),
            'This is a PS3 package. Use the Automatic tab for PS3 games.')
    require(header[192:196] == b'\x7fext' and header[231] & 7 == 2,
            'This PKG is not a supported Vita key-type-2 package.')
    return content


def asset(item, repo, tag, maximum):
    try:
        name = output_name(item['name'])
        expected = 'https://github.com/' + repo + '/releases/download/' + tag + '/' + name
        require(item['browser_download_url'] == expected, 'Unexpected Vita release download address.')
        require(type(item['id']) is int and item['id'] > 0 and
                (item.get('digest') or '').startswith('sha256:'), 'Vita release lacks verified publisher metadata.')
        size = valid_size(item['size'])
        require(0 < size <= maximum, 'Vita release asset is too large.')
        # Asset API supports private downloads and public downloads alike.
        url = 'https://api.github.com/repos/' + repo + '/releases/assets/' + str(item['id'])
        return Asset(name, url, size, valid_hash(item['digest'][7:]))
    except (KeyError, TypeError, ValueError) as exc:
        raise PatchError('Invalid Vita release asset metadata.') from exc


@contextmanager
def automatic_description(pkg, client=None, cache=None, cancel=None, progress=None):
    from . import vita_translation as vita
    content = package_content(pkg)
    client = client or VitaReleaseClient()
    cache = Path(cache) if cache else cache_directory()
    report(progress, 'Finding translation for ' + content[7:16] + '…', None)
    candidates = {}
    for repo in client.repositories(cancel):
        check_cancel(cancel)
        repo = validate_repo(repo)
        if repo == 'retro-trans/retro-trans-tools':
            continue
        releases = client.json('https://api.github.com/repos/' + repo + '/releases?per_page=10', cancel)
        require(isinstance(releases, list) and len(releases) <= 10, 'Invalid Vita release list.')
        for release in releases:
            require(isinstance(release, dict), 'Invalid Vita release metadata.')
            tag = release.get('tag_name', '')
            if release.get('draft') or release.get('prerelease') or not isinstance(tag,str) or not re.fullmatch(r'v0\.\d+\.\d+', tag):
                continue
            items = release.get('assets', [])
            require(isinstance(items, list) and all(isinstance(item, dict) for item in items),
                    'Invalid Vita release inventory.')
            profiles = [item for item in items if item.get('name') == vita.MANIFEST]
            if not profiles:
                continue
            require(len(profiles) == 1, 'Ambiguous Vita release profile.')
            metadata = asset(profiles[0], repo, tag, vita.MAX_METADATA)
            path = client.download(metadata, cache, cancel, progress)
            data = vita.read_description(path.read_bytes())
            require(data['build'] == tag[1:], 'Vita profile version differs from release.')
            if data['content_id'] != content or data['package']['bytes'] != Path(pkg).stat().st_size:
                continue
            zips = [item for item in items if isinstance(item.get('name'), str)
                    and item['name'].endswith('-Vita-PKG-patches.zip')]
            require(len(zips) == 1, 'This Vita release needs exactly one patch ZIP.')
            archive = asset(zips[0], repo, tag, vita.MAX_ZIP)
            candidates.setdefault(repo, []).append((data, archive))
    require(candidates, 'No automatic Vita translation was found for ' + content[7:16] + '. '
            'Private releases need an existing GitHub CLI sign-in with access. '
            'You can also select a downloaded local translation ZIP.')
    checksum = sha256_file(pkg, cancel, progress, 'Checking original Vita package')
    matches = {}
    for repo, options in candidates.items():
        exact = [(data, archive) for data, archive in options if data['package']['sha256'] == checksum]
        if exact:
            matches[repo] = max(exact, key=lambda pair: tuple(map(int, pair[0]['build'].split('.'))))
    require(matches, 'A translation exists, but this PKG revision does not match its verified original.')
    require(len(matches) == 1, 'Several projects translate this game. Choose the desired project\'s local patch ZIP.')
    data, archive = next(iter(matches.values()))
    report(progress, 'Downloading ' + data['name'] + '…', None)
    path = client.download(archive, cache, cancel, progress)
    with vita.archive_description(path, cancel, progress) as resolved:
        require(resolved[0] == data, 'Downloaded Vita ZIP differs from its published profile.')
        yield resolved
