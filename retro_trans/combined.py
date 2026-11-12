"""Explicit, ordered multi-file sources for ordinary xdelta upgrade routes."""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import shutil
import tempfile

from .core import CHUNK, PatchError, check_cancel, report, valid_hash, valid_size, output_path
from .solutions import output_name

MIN_APP_VERSION = '0.5.23'


def components(record):
    if not isinstance(record, dict) or set(record) != {'method', 'files'} or record['method'] != 'concat':
        raise PatchError('Combined sources require an explicit concat method and file list.')
    files = record['files']
    if not isinstance(files, list) or not 2 <= len(files) <= 16:
        raise PatchError('A combined source requires between two and sixteen files.')
    result, names = [], set()
    for item in files:
        if not isinstance(item, dict) or set(item) != {'name', 'bytes', 'sha256'}:
            raise PatchError('Combined-source files need only name, bytes and SHA-256.')
        name = output_name(item['name'])
        if name.casefold() in names:
            raise PatchError('Combined-source filenames must be unique.')
        names.add(name.casefold())
        valid_size(item['bytes']); valid_hash(item['sha256'])
        result.append((name, item['bytes'], item['sha256'].lower()))
    return tuple(result)


def validate(manifest):
    from .catalog import version_key
    from . import __version__
    combined = [p for p in manifest['patches'] if 'combined_source' in p]
    if manifest.get('schema_version') != 3:
        if combined:
            raise PatchError('Combined sources require manifest schema_version 3.')
        return
    if not combined:
        raise PatchError('Manifest v3 requires at least one combined-source patch.')
    if 'solutions' in manifest:
        raise PatchError('Combined-source v3 releases cannot also declare multi-file output solutions.')
    if version_key(manifest.get('min_app_version')) < version_key(MIN_APP_VERSION):
        raise PatchError('Combined sources require Retro Trans 0.5.23 or later.')
    if version_key(manifest['min_app_version']) > version_key(__version__):
        raise PatchError('Update Retro Trans to read this combined-source release.')
    for patch in combined:
        parts = components(patch['combined_source'])
        if sum(size for _, size, _ in parts) != patch['source_bytes']:
            raise PatchError('Combined-source component sizes do not match the source size.')


@dataclass(frozen=True)
class CombinedSource:
    binary: object
    root: Path
    problems: tuple = ()

    def __getattr__(self, name):
        return getattr(self.binary, name)

    @property
    def label(self):
        return self.binary.label + (' (incomplete source)' if self.problems else ' (combined source)')

    @property
    def details(self):
        return 'Required source files, in order:\n' + '\n'.join(
            '  ' + name for name, _, _ in self.binary.source_parts)


def resolve_parts(root, parts):
    """No recursive search, symlink following, or guessed concatenation order."""
    root = Path(root).resolve()
    entries = {}
    for path in root.iterdir():
        entries.setdefault(path.name.casefold(), []).append(path)
    paths, problems = [], []
    for name, size, digest in parts:
        matches = entries.get(name.casefold(), [])
        if len(matches) != 1:
            problems.append(('Missing' if not matches else 'Ambiguous') + ' source file: ' + name)
            continue
        path = matches[0]
        if path.is_symlink() or not path.is_file() or path.resolve().parent != root:
            problems.append('Source must be a regular file in the selected folder: ' + name)
            continue
        if path.stat().st_size != size:
            problems.append('Unsupported source file: ' + name)
            continue
        paths.append(path)
    return paths, problems


def recognize(path, catalog, cancel=None, progress=None):
    from .core import sha256_file
    selected = Path(path).resolve()
    root = selected if selected.is_dir() else selected.parent
    found = []
    for node in catalog.nodes.values():
        if not node.source_parts or node.id not in catalog.available_ids:
            continue
        if selected.is_file() and selected.name.casefold() not in {n.casefold() for n, _, _ in node.source_parts}:
            continue
        paths, problems = resolve_parts(root, node.source_parts)
        if not paths:
            continue
        by_name = {p.name.casefold(): p for p in paths}
        matched = False
        for name, _, digest in node.source_parts:
            check_cancel(cancel)
            actual = by_name.get(name.casefold())
            if actual is not None:
                if sha256_file(actual, cancel, progress) != digest:
                    problems.append('Unsupported source file: ' + name)
                else:
                    matched = True
        if matched:
            found.append(CombinedSource(node, root, tuple(problems)))
    return found


def concatenate(paths, parts, output, cancel=None, progress=None):
    """Verify each component while streaming, including its exact byte count."""
    if len(paths) != len(parts):
        raise PatchError('Missing combined-source component.')
    combined = hashlib.sha256()
    total = sum(size for _, size, _ in parts)
    done = 0
    with Path(output).open('xb') as destination:
        for path, (name, size, expected) in zip(paths, parts):
            check_cancel(cancel)
            if path.is_symlink() or not path.is_file():
                raise PatchError('Invalid source component: ' + name)
            digest, count = hashlib.sha256(), 0
            with path.open('rb') as stream:
                while True:
                    check_cancel(cancel)
                    block = stream.read(min(CHUNK, size - count + 1))
                    if not block:
                        break
                    count += len(block)
                    if count > size:
                        raise PatchError('Source component changed: ' + name)
                    destination.write(block); digest.update(block); combined.update(block)
                    done += len(block)
                    report(progress, 'Checking source component: ' + name, done / max(total, 1))
            if count != size or digest.hexdigest() != expected:
                raise PatchError('Source component changed or failed verification: ' + name)
    return combined.hexdigest()


def apply(source, output, plan, catalog, client=None, cache=None, cancel=None, progress=None):
    from .catalog import _apply_plan_binary
    selected = Path(source).resolve()
    root = selected if selected.is_dir() else selected.parent
    if root != plan.source.root:
        raise PatchError('Combined-source folder changed since selection.')
    parts = plan.source.binary.source_parts
    paths, problems = resolve_parts(root, parts)
    if plan.source.problems or problems:
        raise PatchError('\n'.join(plan.source.problems or problems))
    output = output_path(output, paths)
    # Reserve enough for the combined input and the ordinary route's peak pair.
    sizes = [catalog.nodes[e.target].size for e in plan.edges]
    peak = max((size + (sizes[i - 1] if i else 0) for i, size in enumerate(sizes)), default=0)
    if shutil.disk_usage(output.parent).free < plan.source.size + peak + 64 * 1024**2:
        raise PatchError('Not enough space for the combined source and verified output.')
    with tempfile.TemporaryDirectory(prefix='.retro-trans-source-', dir=str(output.parent)) as stage:
        binary = Path(stage) / 'combined.bin'
        if concatenate(paths, parts, binary, cancel, progress) != plan.source.hashes['sha256']:
            raise PatchError('Combined source failed verification.')
        return _apply_plan_binary(binary, output, plan, catalog, client, cache, cancel, progress, False, None)
