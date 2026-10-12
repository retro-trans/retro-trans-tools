"""Bounded local diagnostics. Never serialize arbitrary messages or input data.

Records use an allowlisted schema, not raw exceptions, progress strings, URLs,
paths, subprocess arguments, environment variables, or traceback source/locals.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import platform
import re
import sys
import threading
import time
import traceback
import uuid

from . import __version__

MAX_BYTES = 512 * 1024
KEEP_SESSIONS = 5
_lock = threading.RLock()
_local = threading.local()
_logger = None
_path = None
_runtime = {}

# No caller can accidentally add a password/path/message to an event.
SCHEMAS = {
    'session_start': {'version': 'version', 'system': 'word', 'os_version': 'version',
                      'architecture': 'word', 'python': 'version', 'frozen': 'bool'},
    'session_end': {},
    'operation_start': {'kind': 'word'},
    'operation_end': {'kind': 'word', 'outcome': 'word', 'elapsed_ms': 'int'},
    'phase': {'stage': 'word'},
    'exception': {'category': 'word', 'types': 'words', 'frames': 'frames',
                  'errno': 'int', 'http_status': 'int', 'ssl_verify_code': 'int'},
    'network_open': {'host': 'host', 'endpoint': 'word'},
    'network_ok': {'host': 'host', 'http_status': 'int'},
    'download': {'state': 'word', 'bytes': 'int', 'sha256': 'hash'},
    'vita_input': {'mode': 'word', 'pkg': 'bool'},
    'vita_profile': {'mode': 'word', 'files': 'int'},
    'vita_zip': {'state': 'word', 'files': 'int'},
    'file_check': {'role': 'word', 'patch': 'patch', 'result': 'word',
                   'expected_bytes': 'int', 'actual_bytes': 'int',
                   'expected_sha256': 'hash', 'actual_sha256': 'hash'},
    'installer': {'state': 'word', 'exit_code': 'int'},
    'vita_file_access': {'state': 'word', 'errno': 'int'},
    'vita_workspace': {'state': 'word', 'errno': 'int'},
}


def _safe(value, kind):
    if kind == 'bool':
        return value if type(value) is bool else None
    if kind == 'int':
        return value if type(value) is int and -2**63 <= value < 2**63 else None
    if kind == 'words':
        return [v for v in (_safe(v, 'word') for v in value[:8]) if v] if isinstance(value, list) else None
    if kind == 'frames':
        return [v for v in value[:20] if isinstance(v, str) and re.fullmatch(
            r'(?:[A-Za-z_][A-Za-z_0-9]*\.py):[0-9]+:[A-Za-z_][A-Za-z_0-9]*', v)] if isinstance(value, list) else None
    if not isinstance(value, str):
        return None
    patterns = {'word': r'[A-Za-z_][A-Za-z_0-9.-]{0,79}',
                'version': r'[0-9][A-Za-z_0-9.+-]{0,49}',
                'hash': r'[0-9a-f]{64}',
                'patch': r'VITA-PCSG00264-test[0-9]+-[0-9]+\.xdelta'}
    if kind == 'host':
        return value if value in ('api.github.com', 'github.com', 'raw.githubusercontent.com') else None
    return value if re.fullmatch(patterns[kind], value) else None


class _QuietHandler(RotatingFileHandler):
    def _open(self):
        fd = os.open(self.baseFilename, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        return os.fdopen(fd, 'a', encoding='utf-8')

    def handleError(self, record):
        # Logging failure must not stop a patch or echo sensitive data to stderr.
        pass


def start_session(directory=None):
    global _logger, _path, _runtime
    with _lock:
        if _logger is not None:
            return _path
        try:
            if directory is None:
                from .core import cache_directory
                directory = cache_directory().parent/'logs'
            directory = Path(directory)
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            name = 'retro-trans-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
            path = directory/(name + '-' + uuid.uuid4().hex + '.log')
            # Only prune this feature's own generated session filenames.
            old = sorted((p for p in directory.glob('retro-trans-*.log')
                          if re.fullmatch(r'retro-trans-\d{8}T\d{6}-[0-9a-f]{32}\.log', p.name)
                          and not p.is_symlink()), key=lambda p: p.stat().st_mtime, reverse=True)
            for p in old[KEEP_SESSIONS-1:]:
                for candidate in (p, Path(str(p)+'.1')):
                    try:
                        candidate.unlink(missing_ok=True)
                    except OSError:
                        pass
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
            handler = _QuietHandler(path, maxBytes=MAX_BYTES, backupCount=1, encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(message)s'))
            logger = logging.Logger('retro_trans.local', logging.INFO)
            logger.addHandler(handler)
            logger.propagate = False
            _logger, _path = logger, path
            values = dict(version=__version__, system=platform.system(),
                          os_version=platform.mac_ver()[0] if sys.platform == 'darwin' else platform.release(),
                          architecture=platform.machine(), python=platform.python_version(),
                          frozen=bool(getattr(sys, 'frozen', False)))
            _runtime = {k: _safe(v, SCHEMAS['session_start'][k]) for k, v in values.items()}
            _runtime = {k: v for k, v in _runtime.items() if v is not None}
            event('session_start')
            return path
        except (OSError, ValueError):
            return None


def event(name, **fields):
    try:
        with _lock:
            if _logger is None or name not in SCHEMAS:
                return
            row = {'time_utc': datetime.now(timezone.utc).isoformat(timespec='milliseconds'), 'event': name}
            # Keep build/system identity even if rotation removed the session header.
            row.update(_runtime)
            operation_id = getattr(_local, 'operation_id', None)
            if operation_id:
                row['operation'] = operation_id
            for key, kind in SCHEMAS[name].items():
                if key in fields:
                    value = _safe(fields[key], kind)
                    if value is not None:
                        row[key] = value
            _logger.info(json.dumps(row, ensure_ascii=True))
    except Exception:
        pass


def exception(exc):
    try:
        _exception(exc)
    except Exception:
        pass


def _exception(exc):
    # Traverse cause chains, but never format the exception value (which may
    # contain zRIF, subprocess argv, a URL token, paths, keys or save data).
    types, frames, seen, codes = [], [], set(), {}
    current = exc
    while current is not None and id(current) not in seen and len(seen) < 8:
        seen.add(id(current))
        types.append(type(current).__name__)
        for frame in traceback.extract_tb(current.__traceback__):
            if 'retro_trans' in Path(frame.filename).parts or Path(frame.filename).name == 'launch.py':
                frames.append(f'{Path(frame.filename).name}:{frame.lineno}:{frame.name}')
        for attr, key in (('errno', 'errno'), ('code', 'http_status'), ('verify_code', 'ssl_verify_code')):
            value = getattr(current, attr, None)
            if type(value) is int:
                codes[key] = value
        reason = getattr(current, 'reason', None)
        current = current.__cause__ or (reason if isinstance(reason, BaseException) else None) or current.__context__
    # Classify only fixed known prefixes; never store the text itself.
    message = str(exc) if type(exc).__name__ in ('PatchError', 'Cancelled') else ''
    category = 'validation' if type(exc).__name__ == 'PatchError' else 'unexpected'
    for prefix, label in [('File mismatch:', 'file_mismatch'), ('Could not reach GitHub', 'network'),
                          ('Could not verify GitHub', 'certificate'), ('Cancelled', 'cancelled'),
                          ('Download verification failed', 'download_verification'),
                          ('Not enough', 'disk_space'), ('PKG conversion', 'pkg_conversion')]:
        if message.startswith(prefix):
            category = label
            break
    event('exception', category=category, types=types, frames=frames[-20:], **codes)


@contextmanager
def operation(kind):
    previous = getattr(_local, 'operation_id', None)
    _local.operation_id = uuid.uuid4().hex[:12]
    _local.phase = None
    start = time.monotonic()
    outcome = 'success'
    event('operation_start', kind=kind)
    try:
        yield
    except BaseException as exc:
        outcome = 'cancelled' if type(exc).__name__ == 'Cancelled' else 'error'
        exception(exc)
        raise
    finally:
        event('operation_end', kind=kind, outcome=outcome, elapsed_ms=int((time.monotonic()-start)*1000))
        _local.operation_id = previous
        _local.phase = None


def progress(message):
    # Record phase transitions, not per-chunk updates or user-supplied filenames.
    stage = 'working'
    for prefix, label in [('Verifying ', 'verifying'), ('Checking ', 'checking'),
                          ('Downloading ', 'downloading'), ('Using verified download', 'cached_download'),
                          ('Extracting and decrypting', 'pkg_conversion'), ('Vita file ', 'vita_patching'),
                          ('Scanning', 'scanning'), ('Applying', 'patching'), ('Compressing', 'compressing')]:
        if message.startswith(prefix):
            stage = label
            break
    if getattr(_local, 'phase', None) != stage:
        event('phase', stage=stage)
        _local.phase = stage


def close_session():
    global _logger, _path
    with _lock:
        event('session_end')
        if _logger:
            for handler in _logger.handlers:
                try:
                    handler.close()
                except OSError:
                    pass
        _logger, _path = None, None
