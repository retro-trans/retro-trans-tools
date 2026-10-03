"""Explicit multi-file patch solutions; all outputs are published as one folder."""

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

from .core import (CHUNK, GitHubClient, PatchError, cache_directory, check_cancel,
                   decode, engine_context, output_path, publish_output, report,
                   safe_name, valid_hash, valid_size)


def output_name(value):
    value = safe_name(value)
    if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", value.split('.')[0]):
        raise PatchError("A solution contains a reserved Windows filename.")
    return value


def validate_solutions(manifest, legacy=False):
    from .catalog import text_field
    schema = manifest.get('schema_version', 1)
    if schema != 2:
        if 'solutions' in manifest:
            raise PatchError("Multi-file solutions require manifest schema_version 2.")
        return
    if legacy:
        raise PatchError("Multi-file solutions require complete SHA-256 metadata.")
    solutions = manifest.get('solutions')
    if not isinstance(solutions, list) or not solutions:
        raise PatchError("Manifest v2 requires explicit patch solutions.")
    ids = set()
    for solution in solutions:
        try:
            if not isinstance(solution, dict):
                raise PatchError("Invalid patch solution.")
            identity = solution['id']
            if not isinstance(identity, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,99}', identity):
                raise PatchError("Solution IDs must be stable lowercase slugs.")
            for key in ('name', 'edition', 'language'):
                text_field(solution[key], key)
            key = (identity, solution['language'])
            if key in ids:
                raise PatchError("Duplicate patch solution.")
            ids.add(key)
            files = solution['files']
            if not isinstance(files, list) or len(files) < 2:
                raise PatchError("A multi-file solution needs at least two components.")
            names, editions = set(), set()
            for component in files:
                name = output_name(component['output_name'])
                edition = text_field(component['edition'], 'component edition')
                if name.casefold() in names or edition in editions:
                    raise PatchError("Solution filenames and component editions must be unique.")
                names.add(name.casefold())
                editions.add(edition)
                patches = [p for p in manifest['patches'] if p['edition'] == edition and
                           p['language'] == solution['language']]
                if not patches:
                    raise PatchError("Solution references a missing component: " + edition)
                identities = {(p['target_sha256'].lower(), p['target_bytes'], p['target_format']) for p in patches}
                if len(identities) != 1:
                    raise PatchError("Solution component has conflicting target identities.")
            copies = solution.get('copy_files', [])
            if not isinstance(copies, list):
                raise PatchError("Invalid unchanged-file list.")
            for item in copies:
                name = output_name(item['name'])
                if name.casefold() in names:
                    raise PatchError("Solution output filenames must be unique.")
                names.add(name.casefold())
                valid_hash(item['sha256'])
                valid_size(item['bytes'])
                if 'source' in item:
                    raise PatchError("Private file paths must not appear in a published solution.")
        except (KeyError, TypeError) as exc:
            raise PatchError("Incomplete patch solution metadata.") from exc


@dataclass(frozen=True)
class Component:
    name: str
    target: tuple


@dataclass(frozen=True)
class CopyFile:
    name: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Solution:
    id: tuple
    game_name: str
    name: str
    edition: str
    language: str
    version: str
    files: tuple
    copy_files: tuple
    format: str = 'folder'


@dataclass
class SolutionSource:
    family: tuple
    definition: Solution
    root: Path
    # Component edition -> (exact local path, recognized Binary).
    found: dict
    problems: tuple = ()

    @property
    def version(self):
        versions = {node.version for _, node in self.found.values()}
        return next(iter(versions)) if len(versions) == 1 else 'mixed versions'

    @property
    def label(self):
        return '{} / {} / {} / {} ({} files{})'.format(
            self.definition.game_name, self.definition.edition, self.definition.language,
            self.version, len(self.definition.files), ', incomplete' if self.problems else '')


@dataclass(frozen=True)
class SolutionPlan:
    source: SolutionSource
    target: Solution
    # (output filename, source path, ordinary binary Plan)
    parts: tuple
    latest: Solution
    latest_reachable: bool

    @property
    def edges(self):
        return tuple(edge for _, _, plan in self.parts for edge in plan.edges)

    @property
    def summary(self):
        text = '{} → {} • {} files, {} xdelta operations'.format(
            self.source.version, self.target.version, len(self.parts), len(self.edges))
        if self.target.version != self.latest.version:
            text += ' (latest published: {})'.format(self.latest.version)
            if not self.latest_reachable:
                text += ' — no complete compatible route to that version.'
        return text

    @property
    def details(self):
        rows = [self.target.name, self.summary, '']
        for name, path, plan in self.parts:
            rows.extend([name + ': ' + plan.summary, '  Source: ' + path.name])
            rows.extend('  ' + edge.asset.name for edge in plan.edges)
            if not plan.edges:
                rows.append('  Already at target; verified copy.')
        if self.target.copy_files:
            rows += ['', '{} unchanged files copied and verified:'.format(len(self.target.copy_files))]
            rows.extend('  ' + item.name for item in self.target.copy_files)
        return '\n'.join(rows)


def load_solutions(catalog):
    from .catalog import clean_version
    catalog.solutions, catalog.active_solutions, catalog.grouped_families = {}, set(), set()
    active_targets = {edge.target for edge in catalog.edges}
    for retired, releases in ((False, catalog.data['releases']), (True, catalog.data.get('withdrawn_releases', []))):
        for release in releases:
            manifest = release['manifest']
            for row in manifest.get('solutions', []):
                version = clean_version(manifest['version'])
                key = (manifest['game_id'], row['id'], row['language'], version)
                files = tuple(Component(c['output_name'], (manifest['game_id'], c['edition'], row['language'], version))
                              for c in row['files'])
                copies = tuple(CopyFile(c['name'], c['bytes'], c['sha256'].lower()) for c in row.get('copy_files', []))
                solution = Solution(key, manifest['game_name'], row['name'], row['edition'], row['language'], version, files, copies)
                if key in catalog.solutions and catalog.solutions[key] != solution:
                    raise PatchError("Conflicting published patch solutions.")
                catalog.solutions[key] = solution
                catalog.grouped_families.update(c.target[:3] for c in files)
                if not retired and all(c.target in active_targets for c in files):
                    catalog.active_solutions.add(key)
    # Component identities are stable across releases, just like single binaries.
    families = {}
    for solution in catalog.solutions.values():
        signature = frozenset(c.target[:3] for c in solution.files)
        previous = families.setdefault(solution.id[:3], signature)
        if previous != signature:
            raise PatchError("A solution changed its required components. Use a new solution ID.")


def solution_versions(catalog, source):
    from .catalog import version_key
    return sorted((s for s in catalog.solutions.values() if s.id in catalog.active_solutions and
                   s.id[:3] == source.family), key=lambda s: version_key(s.version), reverse=True)


def scan_folder(root, catalog, cancel=None, progress=None, selected=None, known=None):
    from .catalog import _recognize_binary, version_key
    from .chd import ChdError, is_chd
    root = Path(root).resolve()
    if not root.is_dir():
        raise PatchError("Choose a folder containing the original files.")
    matches, singles = {}, []
    for path in sorted(root.iterdir()):
        check_cancel(cancel)
        if not path.is_file() or path.is_symlink() or path.resolve() == Path(sys.executable).resolve():
            continue
        try:
            nodes = known[path] if known is not None and path in known else _recognize_binary(path, catalog, cancel, progress)
            compressed = bool(nodes) and is_chd(path)
            for node in nodes:
                if node.id[:3] in catalog.grouped_families:
                    if not compressed:  # A group is an explicit set of raw files.
                        matches.setdefault(node.id[:3], []).append((path, node))
                else:
                    singles.append((path, node))
        except OSError:
            continue
        except ChdError as exc:
            report(progress, 'Skipped ' + path.name + ': ' + str(exc), None)
    groups, seen = [], set()
    for solution in sorted(catalog.solutions.values(), key=lambda s: version_key(s.version), reverse=True):
        family = solution.id[:3]
        if solution.id not in catalog.active_solutions or family in seen:
            continue
        seen.add(family)
        if not any(matches.get(c.target[:3]) for c in solution.files):
            continue
        if selected and not any(p == selected for c in solution.files for p, _ in matches.get(c.target[:3], [])):
            continue
        found, problems = {}, []
        for component in solution.files:
            candidates = matches.get(component.target[:3], [])
            # Equal bytes can be valid under several published version labels.
            by_path = {}
            for path, node in sorted(candidates, key=lambda item: version_key(item[1].version)):
                by_path[path] = node
            if len(by_path) == 1:
                found[component.target[1]] = next(iter(by_path.items()))
            else:
                problems.append(('Missing or unrecognized: ' if not by_path else 'Multiple matching files for: ') + component.name)
        groups.append((root, SolutionSource(family, solution, root, found, tuple(problems))))
    return groups + [(p, n) for p, n in singles if selected is None or p == selected]


def recognize_selection(path, catalog, cancel=None, progress=None):
    from .catalog import _recognize_binary
    path = Path(path).resolve()
    if path.is_dir():
        # File results need their own paths; folder selection is for groups only.
        return [n for _, n in scan_folder(path, catalog, cancel, progress) if isinstance(n, SolutionSource)]
    nodes = _recognize_binary(path, catalog, cancel, progress)
    if any(n.id[:3] in catalog.grouped_families for n in nodes):
        return [n for _, n in scan_folder(path.parent, catalog, cancel, progress, path, {path: nodes})]
    if path.suffix.lower() in ('.cue', '.gdi') and not nodes:
        if not catalog.active_solutions:
            raise PatchError('The current catalog has no complete disc patches. Click Refresh catalog, then select the CUE/GDI again.')
        groups = [n for _, n in scan_folder(path.parent, catalog, cancel, progress) if isinstance(n, SolutionSource)]
        if not groups:
            raise PatchError('No supported disc set was found beside this CUE/GDI. Keep the descriptor and its tracks in the same folder, and refresh the catalog.')
        return groups
    return [n for n in nodes if n.id[:3] not in catalog.grouped_families]


def plan_solution(catalog, source, target='Latest'):
    from .catalog import Plan, clean_version, version_key
    if source.problems:
        raise PatchError('The patch solution is incomplete. ' + '; '.join(source.problems))
    versions = solution_versions(catalog, source)
    if not versions:
        raise PatchError('No published patch solutions are available.')
    reachable = {}
    for solution in versions:
        parts = []
        for component in solution.files:
            path, node = source.found[component.target[1]]
            try:
                destination = catalog.nodes[component.target]
                if node.size == destination.size and node.hashes.get('sha256') == destination.hashes.get('sha256'):
                    # Unchanged tracks can have several version labels. Identical
                    # bytes need no delta, including when selecting an old set.
                    plan = Plan(node, destination, (), catalog.versions(node)[0])
                else:
                    plan = catalog.plan(node, solution.version)
            except PatchError:
                break
            parts.append((component.name, path, plan))
        else:
            missing = [c.name for c in solution.copy_files if not (source.root / c.name).is_file() or
                       (source.root / c.name).is_symlink() or (source.root / c.name).stat().st_size != c.size]
            if not missing:
                reachable[solution.id] = tuple(parts)
    def no_reverse(parts):
        return all(not p.edges or version_key(p.target.version) >= version_key(p.source.version) for _, _, p in parts)
    if target == 'Latest':
        candidates = [s for s in versions if s.id in reachable and no_reverse(reachable[s.id])]
    elif target == 'Next version only':
        candidates = [s for s in reversed(versions) if s.id in reachable and no_reverse(reachable[s.id]) and
                      any(p.edges for _, _, p in reachable[s.id]) and all(len(p.edges) <= 1 for _, _, p in reachable[s.id])]
    else:
        candidates = [s for s in versions if s.version == clean_version(target) and s.id in reachable]
    if not candidates:
        missing = [c.name for c in versions[0].copy_files if not (source.root / c.name).is_file() or
                   (source.root / c.name).is_symlink() or (source.root / c.name).stat().st_size != c.size]
        reason = (' Missing or changed unchanged files: ' + ', '.join(missing)) if missing else ''
        raise PatchError('No complete compatible route to this version.' + reason)
    destination = candidates[0]
    return SolutionPlan(source, destination, reachable[destination.id], versions[0], versions[0].id in reachable)


def copy_verified(source, output, size, sha256, cancel=None, progress=None):
    digest, done = hashlib.sha256(), 0
    with open(source, 'rb') as reader, open(output, 'xb') as writer:
        while True:
            check_cancel(cancel)
            chunk = reader.read(CHUNK)
            if not chunk:
                break
            done += len(chunk)
            if done > size:
                raise PatchError('Source changed while copying: ' + Path(source).name)
            digest.update(chunk)
            writer.write(chunk)
            report(progress, 'Copying and verifying ' + Path(source).name, done / max(size, 1))
    if done != size or digest.hexdigest() != sha256:
        raise PatchError('File verification failed: ' + Path(source).name)


def publish_directory(stage, output):
    if os.name == 'nt':
        os.rename(stage, output)  # Atomically refuses even an existing empty folder.
        return
    output.mkdir()  # Reserve exclusively on platforms where rename replaces folders.
    try:
        for path in stage.iterdir():
            publish_output(path, output / path.name)
    except BaseException:
        shutil.rmtree(output)
        raise


def apply_solution(source, output, plan, catalog, client=None, cache=None, cancel=None, progress=None):
    from .catalog import file_hashes, matches, required_hashes
    output = output_path(output)
    if not plan.edges:
        raise PatchError('All files are already at the selected version.')
    root = plan.source.root
    selected = Path(source).resolve()
    if selected != root and selected.parent != root:
        raise PatchError('The selected folder changed. Identify the file set again.')
    inputs = [p for _, p, _ in plan.parts] + [root / c.name for c in plan.target.copy_files]
    if len({p.resolve() for p in inputs}) != len(inputs):
        raise PatchError('Each solution component needs a separate source file.')
    for path in inputs:
        if not path.is_file() or path.is_symlink() or path.parent.resolve() != root:
            raise PatchError('A required file is missing or outside the selected folder: ' + path.name)
    sizes = [catalog.nodes[e.target].size for e in plan.edges]
    if any(size is None for size in sizes):
        raise PatchError('A solution patch is missing its output size.')
    final_size = sum(p.target.size for _, _, p in plan.parts) + sum(c.size for c in plan.target.copy_files)
    # Completed files plus two largest intermediates; reserve conservatively.
    peak = final_size + 2 * max(sizes) + 64 * 1024 * 1024
    if shutil.disk_usage(output.parent).free < peak:
        raise PatchError('Not enough free space for the complete patched folder and intermediate files.')
    for _, path, part in plan.parts:
        hashes = file_hashes(path, required_hashes([part.source]), cancel, progress)
        if not matches(part.source, hashes, path.stat().st_size):
            raise PatchError('A selected source changed: ' + path.name)
    client, cache = client or GitHubClient(), Path(cache) if cache else cache_directory()
    with tempfile.TemporaryDirectory(prefix='.retro-trans-solution-', dir=str(output.parent)) as temporary:
        stage = Path(temporary)
        result = stage / 'result'
        result.mkdir()
        # Copy only explicitly declared unchanged files, never unrelated folder contents.
        for item in plan.target.copy_files:
            copy_verified(root / item.name, result / item.name, item.size, item.sha256, cancel, progress)
        downloads = {e.asset.url: client.download(e.asset, cache, cancel, progress) for e in plan.edges}
        with engine_context(client, cache, cancel, progress) as engine:
            step = 0
            for name, path, part in plan.parts:
                previous = path
                for edge in part.edges:
                    check_cancel(cancel)
                    step += 1
                    target = catalog.nodes[edge.target]
                    intermediate = stage / ('step-{}.part'.format(step))
                    def step_progress(message, fraction):
                        report(progress, '{} • Step {}/{}: {}'.format(name, step, len(plan.edges), message), fraction)
                    decode(engine, previous, downloads[edge.asset.url], intermediate, target.size, cancel, step_progress)
                    if not matches(target, file_hashes(intermediate, required_hashes([target]), cancel, step_progress), intermediate.stat().st_size):
                        raise PatchError('Intermediate output failed verification: ' + name + ' / ' + target.version)
                    if previous != path:
                        previous.unlink()
                    previous = intermediate
                if previous == path:
                    copy_verified(path, result / name, part.target.size, part.target.hashes['sha256'], cancel, progress)
                else:
                    os.rename(previous, result / name)
        check_cancel(cancel)
        publish_directory(result, output)
    report(progress, 'Saved and verified complete patch solution ' + plan.target.version, 1)
    return output
