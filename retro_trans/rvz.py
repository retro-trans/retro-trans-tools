"""Lossless GameCube/Wii RVZ conversion; identities always describe ISO bytes."""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zipfile

from .core import PatchError, check_cancel, report, sha256_file, output_path

RESOURCE = Path(__file__).with_name('resources')/'dolphin-tool-windows.zip'
ENGINE_SHA256 = '9c75363877cc6202685d497c781c924661168b8f51fb2f641b8f5c901f76a08d'
RESERVE = 64*1024**2
MAX_ISO = 10*1024**3
MAGIC = b'RVZ\x01'

class RvzError(PatchError):
    pass

@dataclass(frozen=True)
class RvzSource:
    label: str = 'RVZ — unpack to identify'

@dataclass(frozen=True)
class Disc:
    size: int

def supported():
    return os.name == 'nt' or sys.platform == 'linux'

def is_rvz(path):
    path = Path(path)
    if path.suffix.lower() == '.rvz':
        return True
    with path.open('rb') as stream:
        return stream.read(4) == MAGIC

def inspect_rvz(path):
    """Validate bounded RVZ v1 metadata, without decompressing or trusting it as identity."""
    def require(value, message):
        if not value:
            raise RvzError(message)
    with Path(path).open('rb') as stream:
        length = os.fstat(stream.fileno()).st_size
        h = stream.read(0x48)
        require(len(h) == 0x48 and h[:4] == MAGIC, 'Invalid or truncated RVZ header.')
        version, compatible, header_size = struct.unpack_from('>III', h, 4)
        require(0x30000 <= version and compatible <= 0x1000000 and 0x90 <= header_size <= 4096,
                'Unsupported RVZ header version.')
        require(hashlib.sha1(h[:0x34]).digest() == h[0x34:0x48], 'RVZ header checksum failed.')
        size, stored = struct.unpack_from('>QQ', h, 0x24)
        require(0 < size <= MAX_ISO and size % 4 == 0 and stored == length and length >= 0x48+header_size,
                'Invalid RVZ disc or container size.')
        h2 = stream.read(header_size)
        require(hashlib.sha1(h2).digest() == h[0x10:0x24], 'RVZ disc-header checksum failed.')
        kind, compression, level, chunk = struct.unpack_from('>IIiI', h2)
        require(kind in (1, 2) and compression in (0, 1, 2, 3, 4, 5) and
                32768 <= chunk <= 32*1024**2 and chunk & (chunk-1) == 0,
                'Unsupported RVZ disc layout or compression settings.')
        return Disc(size)

def is_game_disc(path):
    with Path(path).open('rb') as stream:
        h = stream.read(0x20)
    return len(h) == 0x20 and (h[0x18:0x1c] == bytes.fromhex('5d1c9ea3') or
                              h[0x1c:0x20] == bytes.fromhex('c2339f3d'))

def require_space(folder, size):
    if shutil.disk_usage(folder).free < size+RESERVE:
        raise RvzError('Not enough free space for the extracted ISO and verified RVZ output.')

@contextmanager
def engine_context(cancel=None):
    if sys.platform == 'linux':
        from .linux import native_tool
        check_cancel(cancel)
        yield native_tool('dolphin-tool')
        return
    if not supported():
        raise RvzError('RVZ conversion in this build requires 64-bit Windows.')
    if not RESOURCE.is_file() or sha256_file(RESOURCE, cancel) != ENGINE_SHA256:
        raise RvzError('The bundled RVZ conversion tool is missing or damaged. Reinstall the app.')
    with tempfile.TemporaryDirectory(prefix='retro-rvz-tool-') as folder:
        root = Path(folder)
        with zipfile.ZipFile(RESOURCE) as z:
            (root/'DolphinTool.exe').write_bytes(z.read('DolphinTool.exe'))
        check_cancel(cancel)
        yield root/'DolphinTool.exe'

def run(engine, args, user, message, cancel=None, progress=None, bounded_output=None, max_bytes=None):
    check_cancel(cancel)
    report(progress, message, None)
    # This is a converter, never Dolphin.exe. An isolated, muted profile also
    # prevents touching a user's Dolphin settings or temporary processing data.
    user = Path(user)
    (user/'Config').mkdir(parents=True, exist_ok=True)
    (user/'Config/Dolphin.ini').write_text('[DSP]\nBackend = Null\nVolume = 0\n', encoding='utf-8')
    with tempfile.TemporaryFile() as log:
        try:
            process = subprocess.Popen([str(engine), 'convert', '-u', str(user)]+[str(x) for x in args],
                stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except OSError as exc:
            if sys.platform == 'linux':
                raise RvzError('Could not start the bundled RVZ converter. Extract a fresh Linux package.') from exc
            raise RvzError('Could not start the RVZ converter. On Windows, install the current '
                           'Microsoft Visual C++ v14 x64 runtime and retry.') from exc
        try:
            while process.poll() is None:
                check_cancel(cancel)
                if bounded_output and bounded_output.exists():
                    size = bounded_output.stat().st_size
                    if max_bytes is not None and size > max_bytes:
                        raise RvzError('RVZ conversion exceeded the declared output size.')
                    report(progress, message, min(size/max(max_bytes or 1, 1), .99))
                time.sleep(.1)
            check_cancel(cancel)
            if process.returncode:
                if sys.platform == 'linux':
                    raise RvzError(message+' failed. The disc may be damaged or unsupported.')
                raise RvzError(message+' failed. The disc may be damaged or unsupported. '
                               'Check that the Microsoft Visual C++ v14 x64 runtime is installed.')
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()

def extract(source, stage, disc=None, cancel=None, progress=None):
    source, stage = Path(source), Path(stage)
    disc = disc or inspect_rvz(source)
    require_space(stage, disc.size)
    output = stage/'disc.iso'
    output_path(output, (source,))
    with engine_context(cancel) as engine:
        run(engine, ['-i', source, '-o', output, '-f', 'iso'], stage/'user',
            'Extracting RVZ to ISO', cancel, progress, output, disc.size)
    if not output.is_file() or output.stat().st_size != disc.size or not is_game_disc(output):
        raise RvzError('The RVZ did not produce a complete GameCube or Wii ISO.')
    return output

def unpack_to_folder(source, destination, cancel=None, progress=None):
    from .solutions import publish_directory
    source, destination = Path(source).resolve(), Path(destination).absolute()
    if destination.parent.resolve() != source.parent or os.path.lexists(destination):
        raise RvzError('Choose a new child folder beside the RVZ. Existing folders are never replaced.')
    before = source.stat()
    disc = inspect_rvz(source)
    require_space(source.parent, disc.size)
    with tempfile.TemporaryDirectory(prefix='.retro-rvz-', dir=str(source.parent)) as folder:
        stage = Path(folder)
        complete = stage/'complete'; complete.mkdir()
        # User processing data stays in the private stage, outside the retained folder.
        binary = extract(source, stage, disc, cancel, progress)
        name = source.stem+'.iso'
        binary.rename(complete/name)
        after = source.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise RvzError('The RVZ changed during extraction. Select it again.')
        check_cancel(cancel)
        publish_directory(complete, destination)
    return destination/name

def compress_verified(source, output, cancel=None, progress=None):
    source, output = Path(source), Path(output)
    output_path(output, (source,))
    if not is_game_disc(source):
        raise RvzError('RVZ output requires a GameCube or Wii ISO. Choose the original output format for this file.')
    size = source.stat().st_size
    if not 0 < size <= MAX_ISO:
        raise RvzError('Unsupported GameCube/Wii disc size.')
    # Conservatively allow a second ISO plus an incompressible RVZ and overhead.
    require_space(output.parent, size*2+16*1024**2)
    expected = sha256_file(source, cancel, progress, 'Checking ISO before RVZ compression')
    with tempfile.TemporaryDirectory(prefix='.retro-rvz-verify-', dir=str(output.parent)) as folder:
        stage = Path(folder)
        with engine_context(cancel) as engine:
            run(engine, ['-i', source, '-o', output, '-f', 'rvz', '-b', '131072', '-c', 'zstd', '-l', '5'],
                stage/'user', 'Compressing patched RVZ', cancel, progress, output, size+16*1024**2)
        disc = inspect_rvz(output)
        if disc.size != size:
            raise RvzError('The compressed RVZ declares a different ISO size.')
        restored = extract(output, stage, disc, cancel, progress)
        if sha256_file(restored, cancel, progress, 'Verifying RVZ round trip') != expected:
            raise RvzError('The RVZ does not reproduce the verified patched ISO.')
    check_cancel(cancel)

def copy_notices(directory):
    if sha256_file(RESOURCE) != ENGINE_SHA256:
        raise RvzError('The bundled RVZ converter failed verification.')
    with zipfile.ZipFile(RESOURCE) as z:
        for name in z.namelist():
            if name in ('COPYING', 'NOTICE.txt') or name.startswith('Licenses/'):
                parts = name.split('/')
                if any(p in ('', '.', '..') or ':' in p or '\\' in p for p in parts):
                    raise RvzError('Invalid RVZ notice path.')
                target = Path(directory).joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(name))
