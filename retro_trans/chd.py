"""Offline CHD disc preparation. Catalog identities always refer to disc bytes.

The v5 header/metadata layout follows MAME src/lib/util/chd.h (mame0289).
DVD header hashes are recognition hints only; patching verifies extracted bytes.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import time
import zipfile

from .core import PatchError, cache_directory, check_cancel, report, sha256_file, output_path, publish_output

RESOURCE = Path(__file__).with_name('resources') / 'chdman-windows.zip'
ENGINE_SHA256 = '39c4cc4f8dc4da8422c378886458745fba1304ebe7bc8f69ebbd30baa97fdfeb'
RESERVE = 64 * 1024 * 1024
CD_MODES = {'MODE1': (2048, 'MODE1/2048'), 'MODE1_RAW': (2352, 'MODE1/2352'),
            'MODE2_RAW': (2352, 'MODE2/2352')}


class ChdError(PatchError):
    pass


@dataclass(frozen=True)
class Disc:
    kind: str
    size: int
    sector_size: int = 2048
    cue_mode: str = ''
    sha1_hint: str = ''


def is_chd(path):
    path = Path(path)
    if path.suffix.lower() == '.chd':
        return True
    with path.open('rb') as stream:
        return stream.read(8) == b'MComprHD'


def inspect_chd(path):
    """Read bounded metadata without decompressing a potentially large image."""
    def require(ok, message):
        if not ok:
            raise ChdError(message)
    with Path(path).open('rb') as stream:
        length = os.fstat(stream.fileno()).st_size
        header = stream.read(124)
        require(len(header) == 124 and header[:8] == b'MComprHD', 'Invalid or truncated CHD header.')
        require(struct.unpack_from('>II', header, 8) == (124, 5),
                'This CHD version is unsupported. Convert it to CHD v5 with chdman first.')
        require(not any(header[104:124]), 'Parent-dependent CHDs are unsupported. Use a standalone CHD.')
        logical, map_offset, offset = struct.unpack_from('>QQQ', header, 32)
        hunk, unit = struct.unpack_from('>II', header, 56)
        require(logical > 0 and 0 < hunk <= 1024 * 1024 and 0 < unit <= hunk
                and hunk % unit == 0 and 124 <= map_offset < length, 'Invalid CHD geometry or data map.')
        entries, visited = [], set()
        while offset:
            require(offset not in visited and len(visited) < 128 and 124 <= offset <= length - 16,
                    'Invalid CHD metadata chain.')
            visited.add(offset)
            stream.seek(offset)
            tag, size, following = struct.unpack('>4sIQ', stream.read(16))
            size &= 0xffffff
            require(size <= 65536 and offset + 16 + size <= length, 'Invalid CHD metadata size.')
            entries.append((tag, stream.read(size)))
            offset = following
        tags = [tag for tag, data in entries]
        if tags == [b'DVD ']:
            require(unit == 2048 and logical % 2048 == 0, 'Invalid DVD CHD sector size.')
            return Disc('dvd', logical, sha1_hint=header[64:84].hex())
        require(tags in ([b'CHT2'], [b'CHTR']),
                'CHD support covers DVDs and single data-track CDs. Multi-track, audio, GD-ROM, '
                'hard-disk and other CHDs need a track-aware workflow.')
        try:
            fields = dict(part.split(':', 1) for part in entries[0][1].rstrip(b'\0').decode('ascii').split())
            mode, frames = fields['TYPE'], int(fields['FRAMES'])
            require(fields['TRACK'] == '1' and fields['SUBTYPE'] == 'NONE' and mode in CD_MODES
                    and int(fields.get('PREGAP', '0')) == 0 and int(fields.get('POSTGAP', '0')) == 0,
                    'This CD layout is unsupported. Use a single data track without gaps or subchannels.')
            sector, cue_mode = CD_MODES[mode]
            require(unit == 2448 and frames > 0 and logical == ((frames + 3) // 4) * 4 * 2448,
                    'Invalid CD CHD track length.')
            return Disc('cd', frames * sector, sector, cue_mode)
        except (KeyError, ValueError, UnicodeError) as exc:
            raise ChdError('Invalid CD CHD track metadata.') from exc


def require_space(folder, size):
    if shutil.disk_usage(folder).free < size + RESERVE:
        raise ChdError('Not enough free space to prepare or compress the CHD. '
                       'Choose a drive with space for the extracted disc and verified output.')


@contextmanager
def engine_context(cancel=None):
    if os.name != 'nt':
        raise ChdError('The bundled CHD engine requires 64-bit Windows.')
    if sha256_file(RESOURCE, cancel) != ENGINE_SHA256:
        raise ChdError('The bundled CHD engine failed verification. Reinstall the app.')
    with tempfile.TemporaryDirectory(prefix='retro-chd-engine-') as folder:
        path = Path(folder) / 'chdman.exe'
        with zipfile.ZipFile(RESOURCE) as archive:
            path.write_bytes(archive.read('chdman.exe'))
        check_cancel(cancel)
        yield path


def run(engine, args, message, cancel=None, progress=None, bounded_output=None, max_bytes=None):
    check_cancel(cancel)
    report(progress, message, None)
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen([str(engine)] + [str(a) for a in args], stdin=subprocess.DEVNULL,
            stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            while process.poll() is None:
                check_cancel(cancel)
                if bounded_output and bounded_output.exists() and bounded_output.stat().st_size > max_bytes:
                    raise ChdError('CHD extraction exceeded its declared disc size.')
                if bounded_output and bounded_output.exists():
                    report(progress, message, min(bounded_output.stat().st_size / max(max_bytes, 1), .99))
                time.sleep(.1)
            check_cancel(cancel)
            if process.returncode:
                log.seek(0, 2)
                end = log.tell()
                log.seek(max(0, end - 4096))
                detail = log.read().decode('utf-8', errors='replace').strip()
                raise ChdError(message + ' failed. ' + detail)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()


def extract(source, stage, disc, cancel=None, progress=None):
    require_space(stage, disc.size)
    output = Path(stage) / ('disc.iso' if disc.kind == 'dvd' else 'disc.bin')
    with engine_context(cancel) as engine:
        if disc.kind == 'dvd':
            args = ['extractdvd', '-i', source, '-o', output]
        else:
            # CD metadata and padded sector storage are part of the CHD identity.
            run(engine, ['verify', '-i', source], 'Verifying CD CHD', cancel, progress)
            args = ['extractcd', '-i', source, '-o', Path(stage) / 'disc.cue', '-ob', output]
        run(engine, args, 'Extracting ' + Path(source).name, cancel, progress, output, disc.size)
    if not output.is_file() or output.stat().st_size != disc.size:
        raise ChdError('The extracted disc size does not match the CHD metadata.')
    return output


@contextmanager
def prepared_source(source, folder=None, cancel=None, progress=None):
    source = Path(source)
    if not is_chd(source):
        yield source, None
        return
    disc = inspect_chd(source)
    folder = Path(folder) if folder else cache_directory() / 'chd'
    folder.mkdir(parents=True, exist_ok=True)
    require_space(folder, disc.size)
    with tempfile.TemporaryDirectory(prefix='.retro-chd-', dir=str(folder)) as temporary:
        yield extract(source, Path(temporary), disc, cancel, progress), disc


def output_disc(source, size, disc=None, binary_format=None):
    if binary_format and binary_format.lower() not in ('iso', 'bin'):
        raise ChdError('CHD output is supported for disc images, not ' + binary_format.upper() + ' files.')
    if disc is None:
        if (binary_format or Path(source).suffix.lstrip('.')).lower() != 'iso':
            raise ChdError('CHD output needs an ISO or a supported CHD input with known disc layout. '
                           'Save this binary in its original format instead.')
        disc = Disc('dvd', size)
    if size <= 0 or size % disc.sector_size:
        raise ChdError('The patched image size is not a whole number of disc sectors.')
    return Disc(disc.kind, size, disc.sector_size, disc.cue_mode)


def copy_notices(directory):
    """Copy the pinned engine's notices into the portable ZIP's licenses folder."""
    if sha256_file(RESOURCE) != ENGINE_SHA256:
        raise ChdError('The bundled CHD engine failed verification.')
    with zipfile.ZipFile(RESOURCE) as archive:
        for name in archive.namelist():
            if name in ('COPYING', 'NOTICE.txt') or name.startswith('docs/legal/'):
                parts = name.split('/')
                if any(part in ('', '.', '..') or ':' in part or '\\' in part for part in parts):
                    raise ChdError('Invalid bundled notice path.')
                target = Path(directory).joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(name))


def cue_bytes(binary_name, disc):
    if any(c in binary_name for c in ('"', '\n', '\r')):
        raise ChdError('Unsupported disc filename for a CUE sheet.')
    return ('FILE "' + binary_name + '" BINARY\n  TRACK 01 ' + disc.cue_mode +
            '\n    INDEX 01 00:00:00\n').encode('utf-8')


def companion_cue(output, disc):
    if disc and disc.kind == 'cd' and (disc.sector_size != 2048 or Path(output).suffix.lower() != '.iso'):
        return output_path(Path(output).with_suffix('.cue'), (output,))
    return None


def publish_disc(temporary, output, disc=None):
    cue = companion_cue(output, disc)
    if cue:
        staged = Path(temporary).parent / 'output.cue'
        staged.write_bytes(cue_bytes(Path(output).name, disc))
        publish_output(staged, cue)
        try:
            publish_output(temporary, output)
        except BaseException:
            cue.unlink()  # Only the new companion created by this operation.
            raise
    else:
        publish_output(temporary, output)


def compress_verified(source, output, disc, cancel=None, progress=None):
    """Compress and round-trip the exact patched bytes before publication."""
    source, output = Path(source), Path(output)
    require_space(output.parent, disc.size * 2)
    expected = sha256_file(source, cancel, progress, 'Checking disc before CHD compression')
    with engine_context(cancel) as engine:
        if disc.kind == 'dvd':
            args = ['createdvd', '-i', source, '-o', output]
        else:
            cue = output.parent / 'patched.cue'
            # Callers provide a private stage with simple generated basenames.
            cue.write_bytes(cue_bytes(source.name, disc))
            args = ['createcd', '-i', cue, '-o', output]
        run(engine, args + ['-np', str(max(1, min(4, (os.cpu_count() or 2) - 1)))],
            'Compressing patched CHD', cancel, progress)
    actual = inspect_chd(output)
    if (actual.kind, actual.size, actual.sector_size, actual.cue_mode) != (
            disc.kind, disc.size, disc.sector_size, disc.cue_mode):
        raise ChdError('Compressed CHD disc layout verification failed.')
    with tempfile.TemporaryDirectory(prefix='verify-', dir=str(output.parent)) as temporary:
        restored = extract(output, Path(temporary), actual, cancel, progress)
        if sha256_file(restored, cancel, progress, 'Verifying compressed CHD round trip') != expected:
            raise ChdError('Compressed CHD does not reproduce the verified patched image.')
    check_cancel(cancel)
