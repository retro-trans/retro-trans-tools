"""DCP packages through the pinned Universal Dreamcast Patcher process engine.

No game files are uploaded. Rebuilt discs have their own layout; they are not
claimed to match raw-track xdelta output. Optional ZIP-comment metadata verifies
the complete game-file tree without adding a manifest to the game's filesystem.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

from .core import PatchError, check_cancel, report, sha256_file, safe_name, valid_hash

UPSTREAM = '8b352f959bcc56ab39174c9e311b7ab7f0d522a2'
SPACE = 12 * 1024 ** 3


def inspect_patch(path):
    """Bound and validate every archive path before the external engine runs."""
    try:
        with zipfile.ZipFile(path) as z:
            rows = z.infolist()
            if not rows or len(rows) > 50000:
                raise PatchError('DCP has an empty or oversized file list.')
            total, names = 0, set()
            for row in rows:
                name = row.filename.replace('\\', '/')
                parts = name.rstrip('/').split('/')
                if not parts or name.startswith('/') or any(p in ('.', '..') for p in parts):
                    raise PatchError('DCP contains an unsafe archive path.')
                for part in parts:
                    safe_name(part)
                    if part.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *('COM'+str(i) for i in range(1,10)), *('LPT'+str(i) for i in range(1,10))}:
                        raise PatchError('DCP contains a reserved filename.')
                if stat.S_ISLNK(row.external_attr >> 16) or row.flag_bits & 1:
                    raise PatchError('DCP links and encrypted members are unsupported.')
                folded = name.rstrip('/').casefold()
                if folded in names:
                    raise PatchError('DCP contains duplicate archive paths.')
                names.add(folded)
                total += row.file_size
                if total > 4 * 1024 ** 3:
                    raise PatchError('DCP expands beyond the supported Dreamcast patch size.')
            metadata = {}
            if z.comment.startswith(b'{'):
                candidate = json.loads(z.comment.decode('utf-8'))
                if isinstance(candidate, dict) and candidate.get('retro_trans_dcp') == 1:
                    for key in ('source_tree_sha256', 'target_tree_sha256'):
                        valid_hash(candidate[key])
                    metadata = candidate
            return {'members': len(rows), 'expanded_bytes': total, 'metadata': metadata}
    except (OSError, zipfile.BadZipFile, KeyError, ValueError, UnicodeError) as exc:
        raise PatchError('The DCP archive or its verification metadata is invalid.') from exc


def engine():
    system = {'win32': 'win', 'darwin': 'osx', 'linux': 'linux'}.get(sys.platform)
    arch = 'arm64' if platform.machine().lower() in ('arm64', 'aarch64') else 'x64'
    directory = Path(__file__).with_name('resources') / 'native/dcp' / (str(system) + '-' + arch)
    try:
        manifest = json.loads((directory / 'engine.json').read_text(encoding='utf-8'))
        if manifest['upstream_commit'] != UPSTREAM:
            raise PatchError('The bundled DCP engine version is unexpected.')
        for name, identity in manifest['files'].items():
            safe_name(name)
            p = directory / name
            if p.is_symlink() or p.stat().st_size != identity['bytes'] or sha256_file(p) != identity['sha256']:
                raise PatchError('The bundled DCP engine failed verification. Reinstall this build.')
        return directory / ('RetroTrans.Dcp.exe' if sys.platform == 'win32' else 'RetroTrans.Dcp')
    except (OSError, ValueError, KeyError) as exc:
        raise PatchError('This build has no DCP engine for your platform. Use a DCP-enabled build or Universal Dreamcast Patcher.') from exc


def run(command, request, workspace, cancel=None, progress=None):
    executable = engine()
    workspace = Path(workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    control = workspace / ('control-' + command + '-' + str(time.time_ns()) + '.json')
    cancel_file = control.with_suffix('.cancel')
    request = dict(request, cancel_file=str(cancel_file))
    control.write_text(json.dumps(request), encoding='utf-8')
    env = os.environ.copy()
    temporary = workspace / 'engine-temp'
    temporary.mkdir(exist_ok=True)
    env.update(TEMP=str(temporary), TMP=str(temporary), TMPDIR=str(temporary), DOTNET_EnableDiagnostics='0')
    check_cancel(cancel)
    process = subprocess.Popen([str(executable), command, str(control)], stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', env=env,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    events = queue.Queue()
    def reader():
        try:
            for line in process.stdout:
                events.put(line)
        finally:
            events.put(None)
    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    result, errors, cancelling = None, [], None
    try:
        while True:
            if cancel is not None and cancel.is_set():
                if cancelling is None:
                    cancel_file.touch(); cancelling = time.monotonic()
                elif time.monotonic() - cancelling > 10 and process.poll() is None:
                    process.kill()
            try:
                line = events.get(timeout=0.1)
            except queue.Empty:
                continue
            if line is None:
                break
            try:
                message = json.loads(line)
            except ValueError:
                errors.append(line.strip()); errors = errors[-8:]; continue
            if 'progress' in message:
                report(progress, message['progress'])
            if 'success' in message:
                result = message
        code = process.wait()
        check_cancel(cancel)
        if code != 0 or not result or not result.get('success'):
            raise PatchError((result or {}).get('error') or 'DCP engine failed: ' + ' '.join(errors))
        return result
    finally:
        if process.poll() is None:
            cancel_file.touch()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
        thread.join(timeout=3)
        process.stdout.close()


def tree_hash(files):
    """Disc filesystem identity; IP.BIN is handled separately by the rebuilder."""
    rows = {n: v for n, v in files.items() if not n.lower().startswith('bootsector/')}
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def audio_identity(path, cancel=None):
    """Hash CDDA content separately from DAT-reconstructed silent padding.

    Redump/TOSEC conversion moves drive-offset/pregap silence. Require identical
    non-silent bytes, their sample alignment, and retain full hashes for audit.
    Streaming keeps long audio tracks from consuming their size in RAM.
    """
    first, last, position = None, 0, 0
    with Path(path).open('rb') as source:
        while chunk := source.read(4 * 1024 * 1024):
            check_cancel(cancel)
            body = chunk.strip(b'\0')
            if body:
                if first is None: first = position + len(chunk) - len(chunk.lstrip(b'\0'))
                last = position + len(chunk.rstrip(b'\0'))
            position += len(chunk)
        digest = hashlib.sha256()
        remaining = last - (first or 0)
        source.seek(first or 0)
        while remaining:
            check_cancel(cancel)
            chunk = source.read(min(remaining, 4 * 1024 * 1024))
            if not chunk: raise PatchError('Truncated CD audio track.')
            digest.update(chunk); remaining -= len(chunk)
    return {'content_bytes': last - (first or 0), 'content_sha256': digest.hexdigest(),
            'sample_alignment': (first or 0) % 4}


def prepare_gdi(source, workspace, cancel=None, progress=None):
    """UDP 2.1.8 ignores the sixth GDI field. Normalize offsets, read-only."""
    source = Path(source).resolve()
    if source.suffix.lower() != '.gdi':
        return source
    try:
        lines = source.read_text(encoding='utf-8-sig').splitlines()
        count = int(lines[0]); tracks = [shlex.split(line) for line in lines[1:] if line.strip()]
        if not 3 <= count <= 99 or len(tracks) != count:
            raise ValueError('Invalid track count')
        for row in tracks:
            if len(row) != 6 or int(row[3]) not in (2048, 2352) or int(row[5]) < 0 or int(row[5]) % int(row[3]):
                raise ValueError('Invalid track geometry')
            safe_name(row[4])
            if not (source.parent / row[4]).is_file():
                raise ValueError('Missing companion track: ' + row[4])
        if not any(int(row[5]) for row in tracks):
            return source
        directory = Path(workspace) / 'offset-normalized'
        directory.mkdir(parents=True)
        normalized = [str(count)]
        for row in tracks:
            track, lba, kind, size, name, offset = row
            destination = directory / ('track' + str(int(track)).zfill(2) + '.bin')
            report(progress, 'Preparing GDI track ' + track + ' offsets')
            with (source.parent / name).open('rb') as src, destination.open('xb') as dst:
                src.seek(int(offset))
                while True:
                    check_cancel(cancel)
                    chunk = src.read(4 * 1024 * 1024)
                    if not chunk: break
                    dst.write(chunk)
            if destination.stat().st_size == 0 or destination.stat().st_size % int(size):
                raise ValueError('Truncated track')
            normalized.append(' '.join((track, lba, kind, size, destination.name, '0')))
        gdi = directory / 'disc.gdi'
        gdi.write_text('\n'.join(normalized) + '\n', encoding='utf-8')
        return gdi
    except (OSError, ValueError, IndexError) as exc:
        raise PatchError('Invalid GDI descriptor: ' + str(exc)) from exc


def inspect_disc(source, workspace, cancel=None, progress=None):
    workspace = Path(workspace).resolve()
    source = prepare_gdi(source, workspace, cancel, progress)
    result = run('inspect', {'source': str(source), 'workspace': str(workspace),
                           'extracted': str(workspace / 'files')}, workspace, cancel, progress)
    ip = bytearray((workspace / 'files/bootsector/IP.BIN').read_bytes())
    # Rebuilding may update only TOC1 entries for the source's HD tracks.
    tracks = int(Path(result['gdi']).read_text(encoding='utf-8-sig').splitlines()[0]) - 2
    if len(ip) != 32768 or ip[0x100:0x104] != b'TOC1' or not 1 <= tracks <= 97:
        raise PatchError('The disc has an unsupported boot-sector track table.')
    ip[0x104:0x104 + tracks * 4] = bytes(tracks * 4)
    result['bootsector_invariant_sha256'] = hashlib.sha256(ip).hexdigest()
    result['audio_tracks'] = {}
    result['audio_content'] = {}
    for line in Path(result['gdi']).read_text(encoding='utf-8-sig').splitlines()[1:]:
        row = shlex.split(line)
        if len(row) == 6 and row[2] == '0':
            audio = Path(result['gdi']).parent / row[4]
            result['audio_tracks'][row[0]] = {'bytes': audio.stat().st_size, 'sha256': sha256_file(audio, cancel)}
            result['audio_content'][row[0]] = audio_identity(audio, cancel)
    return result


def unpack_chd(source, cancel=None, progress=None):
    source = Path(source).resolve()
    if source.suffix.lower() != '.chd' or not source.is_file():
        raise PatchError('Choose a Dreamcast CHD.')
    if shutil.disk_usage(source.parent).free < SPACE:
        raise PatchError('CHD preparation requires 12 GB free beside the source.')
    destination = source.with_name(source.stem + '-unpacked')
    index = 2
    while destination.exists():
        destination = source.with_name(source.stem + '-unpacked-' + str(index)); index += 1
    with tempfile.TemporaryDirectory(prefix='.retro-trans-dcp-unpack-', dir=source.parent) as name:
        inspection = inspect_disc(source, name, cancel, progress)
        gdi = Path(inspection['gdi'])
        check_cancel(cancel)
        destination.mkdir()
        try:
            for p in gdi.parent.iterdir():
                check_cancel(cancel)
                if p.is_file(): shutil.copy2(p, destination / p.name)
        except BaseException:
            shutil.rmtree(destination); raise
    return destination / gdi.name


def apply(source, patch, output, *, format='GDI', allow_chd=False, cancel=None, progress=None):
    source, patch, output = Path(source).resolve(), Path(patch).resolve(), Path(output).absolute()
    if source.suffix.lower() not in ('.gdi', '.cue', '.chd') or not source.is_file():
        raise PatchError('Choose a Dreamcast GDI, CUE or CHD with all its companion tracks.')
    if source.suffix.lower() == '.chd' and not allow_chd:
        raise PatchError('CHD extraction needs permission. Confirm it in the DCP tab first.')
    if format not in ('GDI', 'CUE/BIN', 'CHD'):
        raise PatchError('Choose GDI, CUE/BIN or CHD output.')
    if output.exists() or not output.parent.is_dir():
        raise PatchError('Choose a new output folder in an existing parent. Existing folders are never overwritten.')
    archive = inspect_patch(patch)
    metadata = archive['metadata']
    if shutil.disk_usage(output.parent).free < SPACE:
        raise PatchError('DCP rebuilding requires at least 12 GB of free temporary/output space.')
    # Keep all upstream temporary files in an owned workspace beside the output.
    with tempfile.TemporaryDirectory(prefix='.retro-trans-dcp-', dir=output.parent) as name:
        stage = Path(name)
        prepared_source = prepare_gdi(source, stage / 'input', cancel, progress)
        if source.suffix.lower() == '.chd':
            prepared_source = unpack_chd(source, cancel, progress)
        before = inspect_disc(prepared_source, stage / 'source-check', cancel, progress)
        if metadata:
            if tree_hash(before['files']) != metadata['source_tree_sha256']:
                raise PatchError('This DCP requires ' + str(metadata.get('source_version', 'a different source version')) + '. Select the matching original or previous release.')
        produced_parent = stage / 'output'
        produced_parent.mkdir()
        result = run('apply', {'source': str(prepared_source), 'patch': str(patch), 'output': str(produced_parent),
                               'format': format}, stage / 'apply', cancel, progress)
        produced = Path(result['output']).resolve()
        if produced.parent != produced_parent.resolve() or not produced.is_dir():
            raise PatchError('DCP engine returned an unexpected output folder.')
        descriptors = list(produced.glob({'GDI': '*.gdi', 'CUE/BIN': '*.cue', 'CHD': '*.chd'}[format]))
        if len(descriptors) != 1:
            raise PatchError('Rebuilt output is missing its unique disc descriptor.')
        after = inspect_disc(descriptors[0], stage / 'output-check', cancel, progress)
        actual = tree_hash(after['files'])
        if metadata and actual != metadata['target_tree_sha256']:
            raise PatchError('Rebuilt game files do not match this DCP release. Output was not saved.')
        if metadata.get('bootsector_invariant_sha256') and after.get('bootsector_invariant_sha256') != metadata['bootsector_invariant_sha256']:
            raise PatchError('Rebuilt boot code does not match this DCP release. Output was not saved.')
        if before.get('audio_content', before.get('audio_tracks', {})) != after.get('audio_content', after.get('audio_tracks', {})):
            raise PatchError('Rebuilt CD audio tracks do not match the source. Output was not saved.')
        hashes = {p.name: {'bytes': p.stat().st_size, 'sha256': sha256_file(p, cancel)} for p in produced.iterdir() if p.is_file()}
        proof = dict(result, output=str(output), format=format, verified_game_tree_sha256=actual,
                     bootsector_invariant_sha256=after.get('bootsector_invariant_sha256'),
                     audio_tracks_preserved=True, audio_tracks=after.get('audio_tracks', {}),
                     audio_verification='Identical CDDA content and sample alignment; format-specific silent padding may differ',
                     audio_content=after.get('audio_content', {}),
                     release_metadata_verified=bool(metadata), metadata=metadata, output_files=hashes)
        (produced / 'DCP-VALIDATION.json').write_text(json.dumps(proof, indent=2) + '\n', encoding='utf-8')
        check_cancel(cancel)
        output.mkdir()  # Exclusive reservation; only this job's directory may be cleaned.
        try:
            for p in produced.iterdir(): os.rename(p, output / p.name)
        except BaseException:
            shutil.rmtree(output); raise
        proof['output'] = str(output)
        if prepared_source != source: proof['extracted_source'] = str(prepared_source)
        return proof


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source'); ap.add_argument('patch'); ap.add_argument('output')
    ap.add_argument('--format', choices=('GDI', 'CUE/BIN', 'CHD'), default='GDI')
    ap.add_argument('--allow-chd', action='store_true', help='Permit extraction of the selected CHD.')
    a = ap.parse_args()
    try:
        value = apply(a.source, a.patch, a.output, format=a.format, allow_chd=a.allow_chd,
                      progress=lambda m, f=None: print(m, flush=True))
        print(json.dumps(value, indent=2))
    except (PatchError, OSError) as exc:
        ap.exit(1, str(exc) + '\n')


if __name__ == '__main__': main()
