import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from retro_trans.catalog import (Catalog, assert_immutable, recognize, scan_root,
    validate_manifest, refresh_catalog, load_catalog, apply_plan, file_hashes)
from retro_trans.core import PatchError, Cancelled


DATA = {"original": b"original file", "1.1": b"version 1.1", "1.2": b"version 1.2", "1.3": b"version 1.3"}


def record(source="original", target="1.1", edition="original", size=5, legacy=False):
    name = "{}-{}-{}.xdelta".format(edition, source, target)
    p = {"patch": name, "edition": edition, "language": "en", "source_version": source,
         "source_format": "vpk", "target_format": "vpk", "patch_sha256": hashlib.sha256(b"delta").hexdigest(), "patch_bytes": size}
    for side, v in (("source", source), ("target", target)):
        p[side + "_bytes"] = len(DATA[v])
        algorithm = "sha1" if legacy else "sha256"
        p[side + "_" + algorithm] = hashlib.new(algorithm, DATA[v]).hexdigest()
    m = {"schema_version": 1, "game_id": "test", "game_name": "Test Game", "platform": "Test", "version": target,
         "source_commit": "a" * 40, "patches": [p]}
    return {"repo": "retro-trans/test", "tag": "v" + target, "legacy": legacy, "manifest": m,
            "assets": {name: "https://github.com/retro-trans/test/releases/download/v{}/{}".format(target, name)}}


def catalog(*records):
    # Merge alternate routes included in the same release.
    merged = {}
    for item in copy.deepcopy(records):
        key = item["tag"]
        if key in merged:
            merged[key]["manifest"]["patches"].extend(item["manifest"]["patches"])
            merged[key]["assets"].update(item["assets"])
        else:
            merged[key] = item
    return Catalog({"schema_version": 1, "releases": list(merged.values())})


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "renamed 日本語.vpk"
        self.path.write_bytes(DATA["original"])
        self.cat = catalog(record(), record("1.1", "1.2"), record("1.2", "1.3"))
        self.original = recognize(self.path, self.cat)[0]

    def tearDown(self):
        self.temp.cleanup()

    def test_recognition_and_chain_modes(self):
        self.assertEqual(self.original.version, "original")
        self.assertEqual(len(self.cat.plan(self.original).edges), 3)
        self.assertEqual(self.cat.plan(self.original, "Next version only").target.version, "1.1")
        self.assertEqual(len(self.cat.plan(self.original, "1.2").edges), 2)
        self.path.write_bytes(DATA["1.3"])
        current = recognize(self.path, self.cat)[0]
        self.assertEqual(self.cat.plan(current).edges, ())
        with self.assertRaises(PatchError):
            self.cat.plan(current, "1.1")

    def test_direct_route_beats_smaller_chain(self):
        cat = catalog(record(), record("1.1", "1.2"), record("1.2", "1.3"), record("original", "1.3", size=999))
        self.assertEqual(len(cat.plan(cat.nodes[self.original.id]).edges), 1)

    def test_unreachable_latest_is_reported(self):
        cat = catalog(record(), record("1.2", "1.3"))
        plan = cat.plan(cat.nodes[self.original.id])
        self.assertEqual(plan.target.version, "1.1")
        self.assertEqual(plan.latest.version, "1.3")
        self.assertIn("latest published: 1.3", plan.summary)

    def test_edition_separation(self):
        cat = catalog(record(), record("1.1", "1.2", edition="best"))
        self.assertEqual(cat.plan(cat.nodes[self.original.id]).target.version, "1.1")

    def test_scan_zero_one_many_and_no_subfolders(self):
        nested = self.root / "subfolder"
        nested.mkdir()
        (nested / "extra.iso").write_bytes(DATA["1.1"])
        self.assertEqual(len(scan_root(self.root, self.cat)), 1)
        (self.root / "second.bin").write_bytes(DATA["1.2"])
        self.assertEqual(len(scan_root(self.root, self.cat)), 2)
        self.path.write_bytes(b"unknown")
        (self.root / "second.bin").unlink()
        self.assertEqual(scan_root(self.root, self.cat), [])

    def test_cancelled_scan(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            scan_root(self.root, self.cat, cancel)

    def test_legacy_identity_and_strong_hash_precedence(self):
        legacy = record(legacy=True)
        cat = catalog(legacy)
        self.assertEqual(recognize(self.path, cat)[0].version, "original")
        legacy["manifest"]["patches"][0]["source_sha256"] = "0" * 64
        self.assertEqual(recognize(self.path, catalog(legacy)), [])

    def test_only_required_hashes_are_computed_in_one_pass(self):
        strong = record()
        strong["manifest"]["patches"][0]["source_sha1"] = hashlib.sha1(DATA["original"]).hexdigest()
        with patch("retro_trans.catalog.file_hashes", wraps=file_hashes) as hash_file:
            self.assertEqual(recognize(self.path, catalog(strong))[0].version, "original")
            self.assertEqual(hash_file.call_count, 1)
            self.assertEqual(hash_file.call_args.args[1], {"sha256"})
        mixed = catalog(record(edition="legacy-edition", legacy=True), strong)
        with patch("retro_trans.catalog.file_hashes", wraps=file_hashes) as hash_file:
            self.assertEqual(len(recognize(self.path, mixed)), 2)
            self.assertEqual(hash_file.call_count, 1)
            self.assertEqual(hash_file.call_args.args[1], {"sha256", "sha1"})

    def test_manifest_rejections(self):
        m = record()["manifest"]
        for field in ("source_commit", "game_id", "version"):
            bad = copy.deepcopy(m)
            bad[field] = "invalid?"
            with self.subTest(field=field), self.assertRaises(PatchError):
                validate_manifest(bad)
        for field in ("source_sha256", "target_sha256", "patch_sha256", "source_bytes"):
            bad = copy.deepcopy(m)
            del bad["patches"][0][field]
            with self.subTest(field=field), self.assertRaises(PatchError):
                validate_manifest(bad)

    def test_conflicting_and_changed_identities_rejected(self):
        newer = record("1.1", "1.2")
        newer["manifest"]["patches"][0]["source_sha256"] = "0" * 64
        with self.assertRaises(PatchError):
            catalog(record(), newer)
        changed = copy.deepcopy(self.cat.data)
        changed["releases"][0]["manifest"]["patches"][0]["patch_sha256"] = "0" * 64
        with self.assertRaises(PatchError):
            assert_immutable(self.cat, Catalog(changed))

    def test_invalid_remote_catalog_retains_cached_copy(self):
        (self.root / "catalog.json").write_text(json.dumps(self.cat.data), encoding="utf-8")
        class Client:
            def json(self, *args):
                return {"schema_version": 999, "releases": []}
        with self.assertRaises(PatchError):
            refresh_catalog(Client(), self.root)
        self.assertEqual(len(load_catalog(self.root).edges), 3)

    def test_withdrawal_preserves_identity_but_removes_routes_and_recognition(self):
        old = catalog(record(edition="withdrawn"), record(edition="kept"))
        data = copy.deepcopy(old.data)
        release = data["releases"][0]
        withdrawn = copy.deepcopy(release)
        withdrawn["reason"] = "Maintainer discontinued this edition."
        for item, edition in ((release, "kept"), (withdrawn, "withdrawn")):
            item["manifest"]["patches"] = [p for p in item["manifest"]["patches"] if p["edition"] == edition]
            item["assets"] = {p["patch"]: item["assets"][p["patch"]] for p in item["manifest"]["patches"]}
        data["withdrawn_releases"] = [withdrawn]
        current = Catalog(data)
        assert_immutable(old, current)
        self.assertEqual([n.edition for n in recognize(self.path, current)], ["kept"])
        self.assertEqual(len(current.edges), 1)
        self.assertEqual(len(current.withdrawn_edges), 1)
        self.assertEqual(len(current.nodes), len(old.nodes))
        self.assertEqual(current.plan(recognize(self.path, current)[0]).target.edition, "kept")
        with self.assertRaises(PatchError):
            assert_immutable(current, old)  # Reactivation is not allowed.
        broken = copy.deepcopy(data)
        broken["withdrawn_releases"][0]["manifest"]["patches"][0]["patch_sha256"] = "0" * 64
        with self.assertRaises(PatchError):
            assert_immutable(old, Catalog(broken))
        del broken["withdrawn_releases"]
        with self.assertRaises(PatchError):
            assert_immutable(old, Catalog(broken))

    def test_withdrawal_requires_reason_and_cannot_duplicate_active_asset(self):
        data = copy.deepcopy(self.cat.data)
        withdrawn = copy.deepcopy(data["releases"][0])
        data["withdrawn_releases"] = [withdrawn]
        with self.assertRaises(PatchError):
            Catalog(data)
        withdrawn["reason"] = "Withdrawn by maintainer."
        with self.assertRaises(PatchError):
            Catalog(data)

    def test_source_changed_and_low_disk_fail_before_download(self):
        plan = self.cat.plan(self.original)
        self.path.write_bytes(b"differentfile")
        with self.assertRaises(PatchError):
            apply_plan(self.path, self.root / "out.bin", plan, self.cat)
        self.path.write_bytes(DATA["original"])
        with patch("retro_trans.catalog.shutil.disk_usage") as disk:
            disk.return_value.free = 0
            with self.assertRaisesRegex(PatchError, "free space"):
                apply_plan(self.path, self.root / "out.bin", plan, self.cat)


if __name__ == "__main__":
    unittest.main()
