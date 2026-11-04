"""Resolve hash-verified Vita profiles through the central game library.

Original packages and licenses never leave the computer. Optional GitHub CLI
credentials are held in memory and sent only to api.github.com.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__, diagnostics
from .core import (Asset, GitHubClient, PatchError, MAX_METADATA, cache_directory, check_cancel,
                   github_http_error, report, sha256_file, valid_hash, valid_size, validate_repo)
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
    """Reuse local sign-in and cache discovery; never persist credentials."""
    def __init__(self, cache=None):
        self.metadata_cache = (Path(cache) if cache else cache_directory()) / 'github-vita'
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

    @staticmethod
    def api_allowed(parsed):
        return (parsed.hostname == 'api.github.com' and
                (parsed.path.startswith(('/repos/retro-trans/', '/orgs/retro-trans/')) or
                 parsed.path == '/repos/Vita3K/Vita3K/releases/tags/continuous'))

    def json(self, url, cancel=None):
        parsed = urllib.parse.urlsplit(url)
        if not self.api_allowed(parsed) or '/releases/assets/' in parsed.path:
            return super().json(url, cancel)
        require(parsed.scheme == 'https' and parsed.port in (None, 443) and not parsed.username and not parsed.password,
                'Unexpected Vita release API address.')
        check_cancel(cancel)
        # Separate sign-ins (and signed-out use) without writing the token itself.
        key = hashlib.sha256((url + '\0' + self._token).encode()).hexdigest()
        path = self.metadata_cache / (key + '.json')
        try:
            with path.open('rb') as stream:
                raw = stream.read(MAX_METADATA + 1025)
            cached = json.loads(raw) if len(raw) <= MAX_METADATA + 1024 else {}
            if (type(cached.get('fetched_at')) in (int, float) and
                    0 <= time.time() - cached['fetched_at'] < 3600 and
                    isinstance(cached.get('data'), (dict, list))):
                check_cancel(cancel)
                return cached['data']
        except (OSError, ValueError, AttributeError):
            pass
        data = super().json(url, cancel)
        check_cancel(cancel)
        if isinstance(data, (dict, list)):
            from .catalog import atomic_json
            try:
                cached = {'fetched_at': time.time(), 'data': data}
                if len(json.dumps(cached, indent=2, ensure_ascii=False).encode('utf-8')) + 1 <= MAX_METADATA + 1024:
                    atomic_json(path, cached)
            except OSError:
                pass  # A read-only cache must not prevent a verified download.
        return data

    def open(self, url):
        parsed = urllib.parse.urlsplit(url)
        if not self.api_allowed(parsed):
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
        except urllib.error.HTTPError as exc:
            diagnostics.exception(exc)
            raise github_http_error(exc) from exc
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
def automatic_description(pkg, client=None, cache=None, cancel=None, progress=None, profile=None):
    from . import game_library
    if profile is None:
        from . import vita_translation as profile
    vita = profile
    content = package_content(pkg)
    client = client or VitaReleaseClient(cache=cache)
    cache = Path(cache) if cache else cache_directory()
    report(progress, 'Finding translation for ' + content[7:16] + '…', None)
    library = game_library.load(client, cache, cancel, progress)
    mode = 'pkg' if vita.MANIFEST == 'VITA-PKG.json' else 'repatch'
    candidates = [row for row in library['vita_releases'] if row['mode'] == mode and row['content_id'] == content
                  and row['package']['bytes'] == Path(pkg).stat().st_size]
    require(candidates, 'No automatic Vita translation was found for ' + content[7:16] + '. '
            'The game needs a registered package ID and release in the game library. '
            'Private releases need a local private library and GitHub CLI access. '
            'You can also select a downloaded local translation ZIP.')
    checksum = sha256_file(pkg, cancel, progress, 'Checking original Vita package')
    matches = {}
    for row in candidates:
        if row['package']['sha256'] == checksum:
            current = matches.get(row['repo'])
            if current is None or game_library.version_key(row['version']) > game_library.version_key(current['version']):
                matches[row['repo']] = row
    require(matches, 'A translation exists, but this PKG revision does not match its verified original.')
    require(len(matches) == 1, 'Several projects translate this game. Choose the desired project\'s local patch ZIP.')
    entry = next(iter(matches.values()))
    metadata = game_library.asset(entry['profile'], entry['repo'], mode)
    data = vita.read_description(client.download(metadata, cache, cancel, progress).read_bytes())
    package = data.get('package', {})
    require(data.get('content_id', package.get('content_id')) == content and
            data['build'] == entry['version'] and
            {k: package.get(k) for k in ('bytes', 'sha256')} == entry['package'],
            'Downloaded Vita profile differs from the game library.')
    archive = game_library.asset(entry['archive'], entry['repo'], mode, archive=True)
    report(progress, 'Downloading ' + data['name'] + '…', None)
    path = client.download(archive, cache, cancel, progress)
    with vita.archive_description(path, cancel=cancel, progress=progress) as resolved:
        require(resolved[0] == data, 'Downloaded Vita ZIP differs from its published profile.')
        yield resolved
