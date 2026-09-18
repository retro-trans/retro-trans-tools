"""Versioned manifests, binary identities, deterministic routes and catalog I/O."""

from dataclasses import dataclass, field
import hashlib
import heapq
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import urllib.parse

from .core import (Asset, GitHubClient, PatchError, Cancelled, CHUNK, check_cancel,
    report, safe_name, valid_hash, valid_size, validate_repo, cache_directory,
    engine_context, decode, output_path, publish_output)

APP_REPO = "retro-trans/retro-trans-tools"
CATALOG_URL = "https://raw.githubusercontent.com/retro-trans/retro-trans-tools/main/retro_trans/resources/catalog.json"
RESOURCE_DIR = Path(__file__).parent / "resources"


def version_key(value):
    if value == "original":
        return (-1,)
    if not isinstance(value, str) or not re.fullmatch(r"v?\d+(?:\.\d+){1,3}", value):
        raise PatchError("Stable versions must be numeric, for example 1.2.3.")
    parts = tuple(int(p) for p in value.lstrip("v").split("."))
    return parts + (0,) * (4 - len(parts))


def clean_version(value):
    version_key(value)
    return value.lstrip("v")


def text_field(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 200 or any(ord(c) < 32 for c in value):
        raise PatchError("Invalid manifest field: " + name)
    return value


def validate_manifest(data, legacy=False):
    if not isinstance(data, dict):
        raise PatchError("Manifest must be a JSON object.")
    required = ("game_id", "game_name", "platform", "version", "patches")
    if any(k not in data for k in required):
        raise PatchError("Missing required release fields.")
    if not legacy and (type(data.get("schema_version")) is not int or data["schema_version"] != 1):
        raise PatchError("Unsupported manifest schema version.")
    for name in ("game_id", "game_name", "platform"):
        text_field(data[name], name)
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", data["game_id"]):
        raise PatchError("game_id must be a stable lowercase slug.")
    clean_version(data["version"])
    if data["version"] == "original":
        raise PatchError("A release must have a numeric target version.")
    if not legacy and not re.fullmatch(r"[a-fA-F0-9]{40}", str(data.get("source_commit", ""))):
        raise PatchError("source_commit must be the full 40-character Git commit.")
    patches = data["patches"]
    if not isinstance(patches, list) or not patches:
        raise PatchError("Manifest has no patches.")
    names = set()
    for p in patches:
        if not isinstance(p, dict):
            raise PatchError("Invalid patch record.")
        try:
            name = safe_name(p["patch"])
            if not name.lower().endswith((".xdelta", ".vcdiff")) or name.casefold() in names:
                raise PatchError("Patch asset names must be unique xdelta filenames.")
            names.add(name.casefold())
            for key in ("edition", "language", "source_format", "target_format"):
                text_field(p[key], key)
            for key in ("source_format", "target_format"):
                if not re.fullmatch(r"[a-z0-9]{1,12}", p[key]):
                    raise PatchError("Binary formats must be simple file extensions.")
            clean_version(p["source_version"])
            valid_hash(p["patch_sha256"])
            valid_size(p["patch_bytes"])
            for side in ("source", "target"):
                if p.get(side + "_bytes") is not None:
                    valid_size(p[side + "_bytes"])
                elif not legacy:
                    raise PatchError("Missing binary size: " + side)
                sha256, sha1 = p.get(side + "_sha256"), p.get(side + "_sha1")
                if sha256:
                    valid_hash(sha256)
                if sha1 and not re.fullmatch(r"[a-fA-F0-9]{40}", str(sha1)):
                    raise PatchError("Invalid legacy SHA-1.")
                if not sha256 and not (legacy and sha1):
                    raise PatchError("Missing binary SHA-256: " + side)
        except (KeyError, TypeError) as exc:
            raise PatchError("Incomplete patch metadata.") from exc
    return data


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".json.part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as out:
            json.dump(data, out, indent=2, ensure_ascii=False)
            out.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@dataclass
class Binary:
    id: tuple
    game_name: str
    platform: str
    version: str
    edition: str
    language: str
    format: str
    size: object
    hashes: dict = field(default_factory=dict)

    @property
    def label(self):
        return "{} / {} / {} / {}".format(self.game_name, self.edition, self.language, self.version)


@dataclass(frozen=True)
class Edge:
    source: tuple
    target: tuple
    asset: Asset
    release_url: str


@dataclass(frozen=True)
class Plan:
    source: Binary
    target: Binary
    edges: tuple
    latest: Binary
    latest_reachable: bool = True

    @property
    def summary(self):
        versions = [self.source.version] + [e.target[-1] for e in self.edges]
        text = " → ".join(versions)
        if self.target.version != self.latest.version:
            text += "  (latest published: {})".format(self.latest.version)
            if not self.latest_reachable:
                text += " — no compatible route to that version from this file."
        return text


class Catalog:
    def __init__(self, data):
        if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1 or not isinstance(data.get("releases"), list):
            raise PatchError("Unsupported catalog format.")
        self.data, self.nodes, self.edges = data, {}, []
        identities = {}
        seen_releases = set()
        for release in data["releases"]:
            try:
                repo = validate_repo(release["repo"])
                tag = text_field(release["tag"], "tag")
                key = (repo, tag)
                if key in seen_releases:
                    raise PatchError("Duplicate catalog release.")
                seen_releases.add(key)
                m = validate_manifest(release["manifest"], legacy=release.get("legacy") is True)
                if clean_version(tag) != clean_version(m["version"]):
                    raise PatchError("Release tag and manifest version disagree.")
                for p in m["patches"]:
                    source = self.add_binary(m, p, "source", clean_version(p["source_version"]))
                    target = self.add_binary(m, p, "target", clean_version(m["version"]))
                    url = release["assets"][p["patch"]]
                    expected = "https://github.com/{}/releases/download/{}/".format(repo, urllib.parse.quote(tag, safe=""))
                    if not isinstance(url, str) or not url.startswith(expected) or url[len(expected):] != urllib.parse.quote(p["patch"]):
                        raise PatchError("Patch URL does not match its release asset.")
                    asset = Asset(p["patch"], url, p["patch_bytes"], p["patch_sha256"].lower())
                    identity = (asset.size, asset.sha256)
                    if url in identities and identities[url] != identity:
                        raise PatchError("A published patch identity has changed.")
                    identities[url] = identity
                    self.edges.append(Edge(source.id, target.id, asset, "https://github.com/{}/releases/tag/{}".format(repo, tag)))
            except (KeyError, TypeError, AttributeError) as exc:
                raise PatchError("Incomplete catalog release.") from exc

    def add_binary(self, manifest, patch, side, version):
        key = (manifest["game_id"], patch["edition"], patch["language"], version)
        hashes = {algorithm: patch[side + "_" + algorithm].lower() for algorithm in ("sha256", "sha1") if patch.get(side + "_" + algorithm)}
        size = patch.get(side + "_bytes")
        if key in self.nodes:
            node = self.nodes[key]
            if node.platform != manifest["platform"] or node.format != patch[side + "_format"]:
                raise PatchError("Conflicting platform or format for binary " + node.label)
            if node.size is not None and size is not None and node.size != size:
                raise PatchError("Conflicting sizes for binary " + node.label)
            shared = node.hashes.keys() & hashes.keys()
            if not shared or any(node.hashes[a] != hashes[a] for a in shared):
                raise PatchError("Conflicting or unlinked hashes for binary " + node.label)
            node.hashes.update(hashes)
            if node.size is None:
                node.size = size
            return node
        node = Binary(key, manifest["game_name"], manifest["platform"], version,
            patch["edition"], patch["language"], patch[side + "_format"], size, hashes)
        self.nodes[key] = node
        return node

    def versions(self, source):
        published = {e.target for e in self.edges}
        return sorted((n for n in self.nodes.values() if n.id in published and n.id[:3] == source.id[:3] and n.version != "original"),
                      key=lambda n: version_key(n.version), reverse=True)

    def plan(self, source, target="Latest"):
        # Dijkstra with a lexicographic (operations, download bytes) cost.
        best = {source.id: (0, 0)}
        paths = {source.id: ()}
        todo = [(0, 0, source.id)]
        while todo:
            steps, total, node = heapq.heappop(todo)
            if best[node] != (steps, total):
                continue
            for edge in sorted(self.edges, key=lambda e: e.asset.url):
                if edge.source != node or edge.target[:3] != source.id[:3]:
                    continue
                cost = (steps + 1, total + edge.asset.size)
                if edge.target not in best or cost < best[edge.target]:
                    best[edge.target], paths[edge.target] = cost, paths[node] + (edge,)
                    heapq.heappush(todo, (*cost, edge.target))
        versions = self.versions(source)
        if not versions:
            raise PatchError("No published targets are available.")
        latest = versions[0]
        if target == "Latest":
            candidates = [n for n in versions if n.id in best and version_key(n.version) >= version_key(source.version)]
            if not candidates:
                raise PatchError("No upgrade path is available for this binary.")
            destination = candidates[0]
        elif target == "Next version only":
            candidates = [n for n in reversed(versions) if best.get(n.id, (0,))[0] == 1 and version_key(n.version) > version_key(source.version)]
            if not candidates:
                raise PatchError("No next-version patch is available.")
            destination = candidates[0]
        else:
            candidates = [n for n in versions if n.version == clean_version(target)]
            if not candidates or candidates[0].id not in best:
                raise PatchError("No compatible path to this version. Select its required source or the original binary.")
            destination = candidates[0]
        return Plan(source, destination, paths[destination.id], latest, latest.id in best)


def file_hashes(path, algorithms=("sha256",), cancel=None, progress=None):
    size = Path(path).stat().st_size
    digests = {a: hashlib.new(a) for a in algorithms}
    done = 0
    with open(path, "rb") as stream:
        while True:
            check_cancel(cancel)
            data = stream.read(CHUNK)
            if not data:
                break
            for digest in digests.values():
                digest.update(data)
            done += len(data)
            report(progress, "Identifying " + Path(path).name, done / max(size, 1))
    return {a: d.hexdigest() for a, d in digests.items()}


def matches(node, hashes, size):
    algorithm = "sha256" if "sha256" in node.hashes else "sha1"
    return (node.size is None or node.size == size) and hashes.get(algorithm) == node.hashes[algorithm]


def recognize(path, catalog, cancel=None, progress=None):
    path = Path(path)
    if not path.is_file():
        raise PatchError("Select an existing binary.")
    size = path.stat().st_size
    candidates = [n for n in catalog.nodes.values() if n.size is None or n.size == size]
    if not candidates:
        return []
    algorithms = set(a for n in candidates for a in n.hashes)
    hashes = file_hashes(path, algorithms, cancel, progress)
    return sorted([n for n in candidates if matches(n, hashes, size)], key=lambda n: version_key(n.version), reverse=True)


def scan_root(root, catalog, cancel=None, progress=None):
    result = []
    for path in sorted(Path(root).iterdir()):
        check_cancel(cancel)
        if not path.is_file() or path.is_symlink() or path.resolve() == Path(sys.executable).resolve():
            continue
        try:
            for node in recognize(path, catalog, cancel, progress):
                result.append((path, node))
        except (PermissionError, FileNotFoundError, OSError):
            continue
    return result


def application_root():
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]


def assert_immutable(previous, current):
    old = {e.asset.url: e for e in previous.edges}
    new = {e.asset.url: e for e in current.edges}
    for url, edge in old.items():
        if url not in new or new[url] != edge:
            raise PatchError("Catalog removed or changed an existing patch: " + edge.asset.name)
    for key, node in previous.nodes.items():
        updated = current.nodes.get(key)
        if updated is None or any(updated.hashes.get(a) != v for a, v in node.hashes.items()) or (node.size is not None and updated.size != node.size):
            raise PatchError("Catalog changed a known binary identity.")


def load_catalog(cache=None):
    cached = (Path(cache) if cache else cache_directory()) / "catalog.json"
    for path in (cached, RESOURCE_DIR / "catalog.json"):
        try:
            return Catalog(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, PatchError):
            continue
    return Catalog({"schema_version": 1, "releases": []})


def refresh_catalog(client=None, cache=None, cancel=None):
    client = client or GitHubClient()
    current = Catalog(client.json(CATALOG_URL, cancel))
    assert_immutable(load_catalog(cache), current)
    check_cancel(cancel)
    atomic_json((Path(cache) if cache else cache_directory()) / "catalog.json", current.data)
    return current


def apply_plan(source, output, plan, catalog, client=None, cache=None, cancel=None, progress=None):
    source = Path(source).resolve()
    output = output_path(output, (source,))
    if not plan.edges:
        raise PatchError("This binary is already at the selected version.")
    hashes = file_hashes(source, plan.source.hashes, cancel, progress)
    if not matches(plan.source, hashes, source.stat().st_size):
        raise PatchError("The selected source changed or no longer matches its detected version.")
    # For legacy records without published sizes, VCDIFF header sizes are filled
    # during catalog import. Reject missing bounds before writing a chain.
    sizes = [catalog.nodes[e.target].size for e in plan.edges]
    if any(s is None for s in sizes):
        raise PatchError("This legacy patch is missing its output size. Use manual Apply xdelta or update the catalog.")
    peak = max(size + (sizes[i - 1] if i else 0) for i, size in enumerate(sizes))
    if shutil.disk_usage(output.parent).free < peak + 64 * 1024 * 1024:
        raise PatchError("Not enough free space for the patch sequence and intermediate files.")
    client, cache = client or GitHubClient(), Path(cache) if cache else cache_directory()
    downloads = [client.download(e.asset, cache, cancel, progress) for e in plan.edges]
    with engine_context(client, cache, cancel, progress) as engine:
        with tempfile.TemporaryDirectory(prefix=".retro-trans-", dir=str(output.parent)) as stage:
            previous = source
            for index, (edge, delta) in enumerate(zip(plan.edges, downloads)):
                check_cancel(cancel)
                target = catalog.nodes[edge.target]
                temporary = Path(stage) / ("step-{}.part".format(index))
                def step_progress(message, fraction):
                    report(progress, "Step {}/{}: {}".format(index + 1, len(plan.edges), message), fraction)
                decode(engine, previous, delta, temporary, target.size, cancel, step_progress)
                hashes = file_hashes(temporary, target.hashes, cancel, step_progress)
                if not matches(target, hashes, temporary.stat().st_size):
                    raise PatchError("Intermediate output failed verification at version " + target.version)
                if previous != source:
                    previous.unlink()
                previous = temporary
            check_cancel(cancel)
            publish_output(previous, output)
    report(progress, "Saved and verified " + plan.target.version, 1)
    return output
