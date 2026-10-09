"""Original PKG -> temporary decrypted source via an unmodified official Vita3K.

The emulator is downloaded from its publisher, not bundled or re-hosted. Never
run a user's existing installation, and never log subprocess arguments/output.
"""
import base64
from contextlib import contextmanager, ExitStack
import ctypes
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import struct
import subprocess
import tempfile
import time
import zipfile
import zlib

from .core import Asset, GitHubClient, cache_directory, check_cancel, report, valid_hash, valid_size
from .vita_repatch import require, no_links, independent, output_name, verify

PKG = dict(bytes=2338423472,
           sha256='3a13c11c0097ea8faa864c03add89cf7fb6e9c10bce352396ce105df884ac2fd')
API = 'https://api.github.com/repos/Vita3K/Vita3K/releases/tags/continuous'
URL = 'https://github.com/Vita3K/Vita3K/releases/download/continuous/windows-latest.zip'


def license_bytes(pkg, license_path):
    with pkg.open('rb') as f:
        header = f.read(128)
    with license_path.open('rb') as f:
        data = f.read(513)
    require(len(data) == 512, 'Select your matching 512-byte work.bin from NoNpDrm.')
    require(len(header) == 128 and header[:4] == b'\x7fPKG' and
            struct.unpack_from('>Q', header, 0x18)[0] == pkg.stat().st_size,
            'The PKG is incomplete or unsupported.')
    require(header[0x30:0x60] == data[0x10:0x40] and
            header[0x37:0x40] == b'PCSG00264', 'The PKG and work.bin do not match PCSG00264.')
    require(struct.unpack_from('>HHH', data) == (1, 1, 1) and
            struct.unpack_from('<Q', data, 8)[0] == 0x0123456789abcdef and any(data[0x50:0x60]),
            'Use the matching NoNpDrm work.bin, not an account-bound or empty license.')
    return data


def encoded_license(data):
    # RFC 1950/1951 stream. The interoperable zRIF format requires FDICT and
    # dictionary ID 0x627d1d5d. This independently generated stream references
    # no dictionary bytes; no third-party encoder or dictionary is copied.
    compressor = zlib.compressobj(9, zlib.DEFLATED, -10)
    header = 0x28e0
    header += (31 - header % 31) % 31
    stream = (struct.pack('>HI', header, 0x627d1d5d) + compressor.compress(data) +
              compressor.flush() + struct.pack('>I', zlib.adler32(data)))
    require(len(stream) < 512, 'License encoding failed.')
    return base64.b64encode(stream).decode('ascii')


@contextmanager
def read_lock(path):
    """On Windows deny writes/deletion while the original file is in use."""
    if os.name != 'nt':
        yield
        return
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    handle = create(str(path), 0x80000000, 1, None, 3, 0x80, None)
    require(handle != ctypes.c_void_p(-1).value, 'Close programs writing to the PKG or work.bin and retry.')
    try:
        yield
    finally:
        close(handle)


def runtime_asset(client, cancel):
    data = client.json(API, cancel)
    require(isinstance(data, dict) and data.get('tag_name') == 'continuous' and not data.get('draft'),
            'Official Vita3K download metadata is unavailable.')
    candidates = [a for a in data.get('assets', []) if isinstance(a, dict) and a.get('name') == 'windows-latest.zip']
    require(len(candidates) == 1, 'Official Vita3K Windows download is unavailable.')
    item = candidates[0]
    digest = item.get('digest', '') or ''
    require(item.get('browser_download_url') == URL and digest.startswith('sha256:'),
            'Official Vita3K download lacks a verifiable checksum.')
    size = valid_size(item.get('size'))
    require(0 < size <= 150 * 1024**2, 'Unexpected Vita3K download size.')
    return Asset('windows-latest.zip', URL, size, valid_hash(digest[7:]))


def extract_runtime(archive, root, cancel=None):
    with zipfile.ZipFile(archive) as z:
        entries = z.infolist()
        require(len(entries) <= 5000 and sum(i.file_size for i in entries) <= 500 * 1024**2,
                'Unexpected Vita3K archive size.')
        seen = set()
        for i in entries:
            parts = i.filename.rstrip('/').split('/')
            require(1 <= len(parts) <= 12, 'Invalid Vita3K archive path.')
            for part in parts:
                output_name(part)
            name = '/'.join(parts).casefold()
            require(name not in seen and not stat.S_ISLNK(i.external_attr >> 16) and
                    'portable' not in [p.casefold() for p in parts], 'Unsafe Vita3K archive entry.')
            seen.add(name)
        for i in entries:
            check_cancel(cancel)
            target = root.joinpath(*i.filename.rstrip('/').split('/'))
            if i.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(i) as src, target.open('xb') as dst:
                    while True:
                        check_cancel(cancel)
                        chunk = src.read(256 * 1024)
                        if not chunk:
                            break
                        dst.write(chunk)
    executables = list(root.rglob('Vita3K.exe'))
    require(len(executables) == 1, 'Official archive does not contain one Vita3K executable.')
    return executables[0]


def run_installer(exe, pkg, secret, fs, cancel=None, progress=None):
    portable = exe.parent/'portable'
    portable.mkdir()
    fs.mkdir(parents=True)
    (portable/'config.yml').write_text('pref-path: ' + json.dumps(str(fs)) +
        '\ncheck-for-updates: false\ncheck-for-updates-mode: 0\nlog-level: 6\n', encoding='utf-8')
    # Redirect fallbacks as well as the documented portable paths. No firmware,
    # emulator account, real configuration, installed game or save is touched.
    env = os.environ.copy()
    for key in ('APPDATA', 'LOCALAPPDATA', 'TEMP', 'TMP'):
        folder = portable/key.lower()
        folder.mkdir()
        env[key] = str(folder)
    env.pop('QT_PLUGIN_PATH', None)
    env.pop('QT_QPA_PLATFORM_PLUGIN_PATH', None)
    args = [str(exe), '--pkg', str(pkg), '--zrif', secret]
    process = subprocess.Popen(args, cwd=exe.parent, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    # Upstream CLI accepts zRIF only via argv. It is transiently visible to
    # same-user/system process inspection, never sent to GitHub or persisted.
    del args, secret
    start = time.monotonic()
    try:
        while process.poll() is None:
            check_cancel(cancel)
            require(time.monotonic() - start < 3600, 'PKG conversion timed out. No overlay was created.')
            report(progress, 'Extracting and decrypting your PKG locally…', None)
            time.sleep(0.2)
        require(process.returncode == 0, 'PKG conversion failed. Check your matching work.bin and retry.')
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
    # The official CLI can return zero on an installer error. The caller must
    # verify actual source files against the patch manifest before any output.


@contextmanager
def decrypted_source(pkg, license_path, output, client=None, cache=None, cancel=None, progress=None):
    require(os.name == 'nt' and platform.machine().lower() in ('amd64', 'x86_64'),
            'Direct PKG conversion currently requires 64-bit Windows on an x64 PC.')
    pkg, license_path, output = no_links(pkg).resolve(), no_links(license_path).resolve(), no_links(output)
    require(pkg.is_file() and license_path.is_file(), 'Choose the original PKG and matching work.bin.')
    require(not os.path.lexists(output) and output.parent.is_dir() and
            independent(pkg, output.resolve()) and independent(license_path, output.resolve()),
            'Choose a new output folder that does not contain either input.')
    client = client or GitHubClient()
    cache = Path(cache) if cache else cache_directory()
    # Exact package allowlist is also an extraction safety boundary: upstream
    # PKG paths are not independently sanitized. Never pass arbitrary packages.
    with ExitStack() as locks:
        locks.enter_context(read_lock(pkg))
        locks.enter_context(read_lock(license_path))
        data = license_bytes(pkg, license_path)
        verify(pkg, PKG, cancel, progress)
        require(shutil.disk_usage(output.parent).free >= 6 * 1024**3,
                'At least 6 GB of free temporary space is required on the output drive.')
        asset = runtime_asset(client, cancel)
        archive = client.download(asset, cache, cancel, progress)
        verify(archive, dict(bytes=asset.size, sha256=asset.sha256), cancel)
        with tempfile.TemporaryDirectory(prefix='.retro-pkg-', dir=str(output.parent)) as folder:
            root = Path(folder)
            exe = extract_runtime(archive, root/'engine', cancel)
            fs = exe.parent/'portable/fs'
            run_installer(exe, pkg, encoded_license(data), fs, cancel, progress)
            del data
            source = fs/'ux0/app/PCSG00264'
            require((source/'eboot.bin').is_file(),
                    'PKG decryption did not finish. Verify your work.bin; no overlay was created.')
            check_cancel(cancel)
            yield source
