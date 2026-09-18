"""Network, manifest validation, and safe streaming xdelta patching.

No game images are uploaded. Downloads and outputs are verified with SHA-256.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import sys
from contextlib import contextmanager
from . import __version__

DEFAULT_REPO = "retro-trans/SRW-Z"
CHUNK = 4 * 1024 * 1024
MAX_METADATA = 4 * 1024 * 1024
ENGINE_URL = "https://github.com/jmacd/xdelta/releases/download/v3.2.0/xdelta3-3.2.0-windows-x86_64.zip"
ENGINE_SHA256 = "af8ef036cb077a48df080c9a8ac1be4a6e7511c32d11f8bec89b6803a9e52576"
ENGINE_SIZE = 184374
ENGINE_MEMBER = "xdelta3-3.2.0-windows-x86_64/xdelta3.exe"


class PatchError(Exception):
    """An actionable error suitable for display to the user."""


class Cancelled(PatchError):
    pass


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise Cancelled("Cancelled. Your original file is unchanged.")


def report(progress, message, fraction=None):
    if progress:
        progress(message, fraction)


def cache_directory():
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".cache")))
    return root / "RetroTrans" / "cache"


def sha256_file(path, cancel=None, progress=None, message="Checking file"):
    size = Path(path).stat().st_size
    digest = hashlib.sha256()
    done = 0
    with open(path, "rb") as stream:
        while True:
            check_cancel(cancel)
            chunk = stream.read(CHUNK)
            if not chunk:
                break
            digest.update(chunk)
            done += len(chunk)
            report(progress, message, done / max(size, 1))
    return digest.hexdigest()


def validate_repo(repo):
    if not re.fullmatch(r"retro-trans/[A-Za-z0-9_.-]+", repo):
        raise PatchError("Choose a repository in the retro-trans GitHub organization.")
    return repo


def safe_name(value):
    if (not isinstance(value, str) or not value or len(value) > 200
            or value in (".", "..") or value.endswith((".", " "))
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', value)):
        raise PatchError("The release contains an invalid asset filename.")
    return value


def valid_hash(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise PatchError("The release manifest contains an invalid SHA-256 hash.")
    return value.lower()


def valid_size(value):
    if type(value) is not int or value < 0 or value > 2**44:
        raise PatchError("The release manifest contains an invalid file size.")
    return value


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    size: int
    sha256: str = ""


@dataclass(frozen=True)
class Patch:
    asset: Asset
    edition: str
    source_version: str
    source_sha256: str
    source_bytes: int
    target_sha256: str
    target_bytes: int

    @property
    def description(self):
        edition = {"original": "Original edition", "best": "The Best edition"}.get(self.edition, self.edition)
        return edition + (" · upgrade from " + self.source_version if self.source_version else " · full patch")


@dataclass(frozen=True)
class Release:
    repo: str
    tag: str
    url: str
    patches: tuple


class GitHubClient:
    def open(self, url):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in ("api.github.com", "github.com", "raw.githubusercontent.com") or parsed.username or parsed.password:
            raise PatchError("The release has an unexpected download address.")
        headers = {
            "User-Agent": "RetroTrans-Patcher/" + __version__,
            "Accept": "application/vnd.github+json" if parsed.hostname == "api.github.com" else "application/octet-stream",
        }
        # CI tokens are sent only to the GitHub API, never to asset redirects.
        if parsed.hostname == "api.github.com" and os.environ.get("GH_TOKEN"):
            headers["Authorization"] = "Bearer " + os.environ["GH_TOKEN"]
        request = urllib.request.Request(url, headers=headers)
        try:
            return urllib.request.urlopen(request, timeout=30)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise PatchError("No published release was found for this repository.") from exc
            if exc.code in (403, 429):
                raise PatchError("GitHub has limited requests. Please try again later.") from exc
            raise PatchError("GitHub returned HTTP {}. Please try again.".format(exc.code)) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PatchError("Could not reach GitHub. Check your connection and try again.") from exc

    def read(self, url, cancel=None):
        check_cancel(cancel)
        with self.open(url) as response:
            data = response.read(MAX_METADATA + 1)
        check_cancel(cancel)
        if len(data) > MAX_METADATA:
            raise PatchError("Release metadata is too large.")
        return data

    def json(self, url, cancel=None):
        try:
            return json.loads(self.read(url, cancel).decode("utf-8-sig"))
        except (ValueError, UnicodeError) as exc:
            raise PatchError("GitHub returned invalid release metadata.") from exc

    def repositories(self, cancel=None):
        names = []
        for page in range(1, 11):
            items = self.json("https://api.github.com/orgs/retro-trans/repos?per_page=100&page={}".format(page), cancel)
            if not isinstance(items, list):
                raise PatchError("GitHub returned an invalid repository list.")
            names.extend(validate_repo(item["full_name"]) for item in items)
            if len(items) < 100:
                break
        return sorted(names)

    def releases(self, repo, cancel=None):
        validate_repo(repo)
        result = []
        for page in range(1, 101):
            items = self.json("https://api.github.com/repos/{}/releases?per_page=100&page={}".format(repo, page), cancel)
            if not isinstance(items, list):
                raise PatchError("Invalid GitHub release list.")
            result.extend(r for r in items if not r.get("draft") and not r.get("prerelease"))
            if len(items) < 100:
                return result
        raise PatchError("Too many releases; catalog refresh stopped without truncating history.")

    def latest(self, repo, cancel=None):
        validate_repo(repo)
        data = self.json("https://api.github.com/repos/{}/releases/latest".format(repo), cancel)
        try:
            if data.get("draft") or data.get("prerelease"):
                raise PatchError("Choose a published stable release.")
            tag = data["tag_name"]
            if not isinstance(tag, str) or not tag:
                raise PatchError("The release has no version tag.")
            assets = {}
            for item in data["assets"]:
                name = safe_name(item["name"])
                url = item["browser_download_url"]
                prefix = "https://github.com/{}/releases/download/".format(repo)
                if not isinstance(url, str) or not url.startswith(prefix):
                    raise PatchError("A release asset points outside this repository.")
                digest = item.get("digest") or ""
                sha = valid_hash(digest[7:]) if digest.startswith("sha256:") else ""
                if name in assets:
                    raise PatchError("The release has duplicate asset names.")
                assets[name] = Asset(name, url, valid_size(item["size"]), sha)
            manifests = [a for a in assets.values() if re.fullmatch(r"BUILD-MANIFEST(?:-.+)?\.json", a.name, re.I)]
            if len(manifests) != 1:
                raise PatchError("This release needs one BUILD-MANIFEST.json (or BUILD-MANIFEST-version.json) with source, patch, and output hashes. See the project README.")
            asset = manifests[0]
            raw = self.read(asset.url, cancel)
            if len(raw) != asset.size or (asset.sha256 and hashlib.sha256(raw).hexdigest() != asset.sha256):
                raise PatchError("The downloaded release manifest failed verification.")
            manifest = json.loads(raw.decode("utf-8-sig"))
            patches = parse_manifest(manifest, assets)
            return Release(repo, tag, "https://github.com/{}/releases/tag/{}".format(repo, urllib.parse.quote(tag, safe="")), tuple(patches))
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise PatchError("The release manifest is incomplete or invalid. See the project README for the required format.") from exc

    def download(self, asset, cache, cancel=None, progress=None):
        expected = valid_hash(asset.sha256)
        cache = Path(cache)
        cache.mkdir(parents=True, exist_ok=True)
        destination = cache / (expected + ".download")
        if destination.is_file() and destination.stat().st_size == asset.size:
            if sha256_file(destination, cancel) == expected:
                report(progress, "Using verified download: " + asset.name, 1)
                return destination
        check_cancel(cancel)
        if shutil.disk_usage(cache).free < asset.size + 8 * 1024 * 1024:
            raise PatchError("Not enough free space in the download cache folder.")
        fd, temporary = tempfile.mkstemp(prefix="download-", suffix=".part", dir=str(cache))
        try:
            with os.fdopen(fd, "wb") as stream, self.open(asset.url) as response:
                digest = hashlib.sha256()
                done = 0
                while True:
                    check_cancel(cancel)
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    done += len(chunk)
                    if done > asset.size:
                        raise PatchError("The download is larger than the published file size.")
                    stream.write(chunk)
                    digest.update(chunk)
                    report(progress, "Downloading " + asset.name, done / max(asset.size, 1))
            check_cancel(cancel)
            if done != asset.size or digest.hexdigest() != expected:
                raise PatchError("Download verification failed. Please try again.")
            os.replace(temporary, destination)
            return destination
        finally:
            Path(temporary).unlink(missing_ok=True)


def parse_manifest(data, assets):
    if not isinstance(data, dict) or not isinstance(data.get("patches"), list) or not data["patches"]:
        raise PatchError("The release manifest does not list any patches.")
    patches = []
    names = set()
    try:
        for item in data["patches"]:
            name = safe_name(item["patch"])
            if not name.lower().endswith((".xdelta", ".vcdiff")) or name in names:
                raise PatchError("The manifest must list unique xdelta patch filenames.")
            names.add(name)
            asset = assets[name]
            sha = valid_hash(item["patch_sha256"])
            size = valid_size(item["patch_bytes"])
            if size != asset.size or (asset.sha256 and asset.sha256 != sha):
                raise PatchError("Patch metadata disagrees with the GitHub release.")
            edition = item.get("edition", "Game")
            version = item.get("source_version", "")
            if not isinstance(edition, str) or not isinstance(version, str):
                raise PatchError("The manifest contains an invalid edition or version.")
            patches.append(Patch(Asset(name, asset.url, size, sha), edition, version,
                valid_hash(item["source_sha256"]), valid_size(item["source_bytes"]),
                valid_hash(item["target_sha256"]), valid_size(item["target_bytes"])))
    except (KeyError, TypeError) as exc:
        raise PatchError("The manifest is missing a required field or release asset.") from exc
    return patches


def identify_source(source, release, cancel=None, progress=None):
    source = Path(source)
    if not source.is_file():
        raise PatchError("Select an existing binary or disc image.")
    if source.suffix.lower() in (".chd", ".zip", ".7z", ".gz", ".cue"):
        raise PatchError("Select the unpacked ISO or BIN. Extract CHD files with chdman first; see the README.")
    size = source.stat().st_size
    candidates = [p for p in release.patches if p.source_bytes == size]
    targets = [p for p in release.patches if p.target_bytes == size]
    if not candidates and not targets:
        raise PatchError("This file's size does not match a supported image for {}. Select the correct unpacked edition or supported upgrade source.".format(release.tag))
    sha = sha256_file(source, cancel, progress, "Identifying your file")
    if any(p.target_sha256 == sha for p in targets):
        raise PatchError("This file is already patched to {}.".format(release.tag))
    matches = [p for p in candidates if p.source_sha256 == sha]
    if not matches:
        raise PatchError("This file does not match a supported source for {}. It may be a different edition, an unsupported older translation, or a modified image. SHA-256: {}".format(release.tag, sha))
    return min(matches, key=lambda patch: patch.asset.size)


def ensure_engine(client, cache, cancel=None, progress=None):
    if os.name != "nt" or platform.machine().lower() not in ("amd64", "x86_64", "arm64"):
        raise PatchError("Automatic engine setup requires 64-bit Windows.")
    bundled = Path(__file__).parent / "resources" / "xdelta3-windows.zip"
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    if bundled.is_file():
        if sha256_file(bundled, cancel) != ENGINE_SHA256:
            raise PatchError("The bundled patch engine failed verification. Reinstall the app.")
        archive = bundled
    else:
        archive = client.download(Asset("xdelta3 3.2.0", ENGINE_URL, ENGINE_SIZE, ENGINE_SHA256), cache, cancel, progress)
    # Read only the named member, never extract archive paths. Recreate the executable
    # from the verified ZIP for each run, so an altered cached executable is not used.
    with zipfile.ZipFile(archive) as bundle:
        binary = bundle.read(ENGINE_MEMBER)
    check_cancel(cancel)
    engine_dir = Path(tempfile.mkdtemp(prefix="engine-", dir=str(cache)))
    executable = engine_dir / "xdelta3.exe"
    try:
        executable.write_bytes(binary)
    except BaseException:
        shutil.rmtree(engine_dir)
        raise
    return executable


def decode(engine, source, patch_file, temporary, target_size, cancel=None, progress=None):
    # -D and -R disable external decompression/recompression. Checksum verification
    # stays enabled. No shell and no force/overwrite flag are used.
    check_cancel(cancel)
    command = [str(engine), "-d", "-D", "-R", "-s", str(source), str(patch_file), str(temporary)]
    env = os.environ.copy()
    env.pop("XDELTA", None)  # Do not inherit flags that can disable checksums.
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=errors, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            while process.poll() is None:
                check_cancel(cancel)
                size = temporary.stat().st_size if temporary.exists() else 0
                if target_size is not None and size > target_size:
                    raise PatchError("The patch produced more data than the manifest allows.")
                report(progress, "Applying patch", min(size / max(target_size, 1), 0.99) if target_size is not None else None)
                time.sleep(0.1)
            check_cancel(cancel)
            if process.returncode:
                errors.seek(0)
                details = errors.read(4096).decode("utf-8", errors="replace").strip()
                raise PatchError("The patch could not be applied. Your source may have changed. " + details)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()


def publish_output(temporary, output):
    # Windows rename refuses existing destinations, including a file created after
    # our initial check. On POSIX, hard-link creation provides the same guarantee.
    if os.name == "nt":
        os.rename(temporary, output)
    else:
        os.link(temporary, output)
        temporary.unlink()


def patch_binary(source, output, release, client=None, cache=None, cancel=None, progress=None):
    source, output = Path(source).resolve(), Path(output).absolute()
    if source == output.resolve():
        raise PatchError("Choose a different output file to keep your original safe.")
    if os.path.lexists(output):
        raise PatchError("The output file already exists. Choose a new filename.")
    if not output.parent.is_dir():
        raise PatchError("Choose an existing output folder.")
    client = client or GitHubClient()
    cache = Path(cache) if cache is not None else cache_directory()
    patch = identify_source(source, release, cancel, progress)
    report(progress, "Matched: " + patch.description)
    if shutil.disk_usage(output.parent).free < patch.target_bytes + 64 * 1024 * 1024:
        raise PatchError("There is not enough free space in the output folder for the patched copy.")
    patch_file = client.download(patch.asset, cache, cancel, progress)
    engine = ensure_engine(client, cache, cancel, progress)
    # A private directory on the destination volume keeps incomplete output hidden
    # and allows the final verified file to be moved without another full copy.
    try:
        with tempfile.TemporaryDirectory(prefix=".retro-trans-", dir=str(output.parent)) as stage:
            temporary = Path(stage) / "output.part"
            decode(engine, source, patch_file, temporary, patch.target_bytes, cancel, progress)
            if not temporary.is_file() or temporary.stat().st_size != patch.target_bytes:
                raise PatchError("Output size verification failed. No patched copy was saved.")
            sha = sha256_file(temporary, cancel, progress, "Verifying patched copy")
            if sha != patch.target_sha256:
                raise PatchError("Output SHA-256 verification failed. No patched copy was saved.")
            check_cancel(cancel)
            try:
                publish_output(temporary, output)
            except FileExistsError as exc:
                raise PatchError("The output file now exists. Choose a new filename.") from exc
    finally:
        engine.unlink(missing_ok=True)
        engine.parent.rmdir()
    report(progress, "Patched copy saved and verified", 1)
    return patch


@contextmanager
def engine_context(client=None, cache=None, cancel=None, progress=None):
    engine = ensure_engine(client or GitHubClient(), cache or cache_directory(), cancel, progress)
    try:
        yield engine
    finally:
        engine.unlink(missing_ok=True)
        engine.parent.rmdir()


def encode(engine, source, modified, destination, cancel=None, progress=None):
    check_cancel(cancel)
    env = os.environ.copy()
    env.pop("XDELTA", None)
    with tempfile.TemporaryFile() as errors:
        # No application header containing private paths; operate on raw bytes.
        process = subprocess.Popen([str(engine), "-e", "-D", "-A", "-s", str(source), str(modified), str(destination)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors, env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            while process.poll() is None:
                check_cancel(cancel)
                report(progress, "Creating xdelta patch", None)
                time.sleep(0.1)
            check_cancel(cancel)
            if process.returncode:
                errors.seek(0)
                raise PatchError("Could not create patch: " + errors.read(4096).decode("utf-8", errors="replace"))
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()


def output_path(path, inputs=()):
    output = Path(path).absolute()
    if any(output.resolve() == Path(source).resolve() for source in inputs):
        raise PatchError("Choose a different output file to preserve your inputs.")
    if os.path.lexists(output):
        raise PatchError("The output already exists. Choose a new filename.")
    if not output.parent.is_dir():
        raise PatchError("Choose an existing output folder.")
    return output


def manual_patch(source, second, output, create=False, cancel=None, progress=None, cache=None):
    source, second = Path(source).resolve(), Path(second).resolve()
    if not source.is_file() or not second.is_file():
        raise PatchError("Select both input files first.")
    output = output_path(output, (source, second))
    required = second.stat().st_size if create else 0
    if shutil.disk_usage(output.parent).free < required + 64 * 1024 * 1024:
        raise PatchError("Not enough free space in the output folder.")
    with engine_context(cache=cache, cancel=cancel, progress=progress) as engine:
        with tempfile.TemporaryDirectory(prefix=".retro-trans-", dir=str(output.parent)) as stage:
            temporary = Path(stage) / "output.part"
            if create:
                encode(engine, source, second, temporary, cancel, progress)
            else:
                decode(engine, source, second, temporary, None, cancel, progress)
            check_cancel(cancel)
            digest = sha256_file(temporary, cancel, progress, "Hashing output")
            publish_output(temporary, output)
    return digest
