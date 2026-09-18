import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from retro_trans.catalog import Catalog, apply_plan, recognize
from retro_trans.core import Cancelled, PatchError, manual_patch
from retro_trans.release import build_release, validate_directory


@unittest.skipUnless(os.name == "nt", "Bundled xdelta engine is Windows x64")
class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.base = bytes(range(256)) * 2048
        (self.root / "original.vpk").write_bytes(self.base)
        (self.root / "1.1.vpk").write_bytes(self.base[:500] + b"English 1.1" + self.base[511:])
        (self.root / "1.2.vpk").write_bytes(self.base[:800] + b"English 1.2" + self.base[811:])

    def tearDown(self):
        self.temp.cleanup()

    def build(self, source, target, edition="original"):
        config = {"game_id": "fixture", "game_name": "Fixture", "platform": "Vita", "version": target,
            "source_commit": "a" * 40, "patches": [{"patch": source + "-to-" + target + ".xdelta",
            "edition": edition, "language": "en", "source_version": source, "source_format": "vpk", "target_format": "vpk",
            "source": source + ".vpk", "target": target + ".vpk"}]}
        config_path = self.root / (target + ".json")
        config_path.write_text(json.dumps(config), encoding="utf-8")
        output = self.root / ("release-" + target)
        manifest = build_release(config_path, output, cache=self.root / "cache")
        record = {"repo": "retro-trans/fixture", "tag": "v" + target, "manifest": manifest,
            "assets": {p["patch"]: "https://github.com/retro-trans/fixture/releases/download/v{}/{}".format(target, p["patch"]) for p in manifest["patches"]}}
        return record, output

    def test_real_release_builder_chain_and_offline_manual_operations(self):
        r1, d1 = self.build("original", "1.1")
        r2, d2 = self.build("1.1", "1.2")
        self.assertEqual(validate_directory(d1), r1["manifest"])
        self.assertEqual({p.suffix for p in d1.iterdir()}, {".json", ".txt", ".xdelta"})
        cat = Catalog({"schema_version": 1, "releases": [r1, r2]})
        source = self.root / "original.vpk"
        original = recognize(source, cat)[0]
        files = {p.name: p for d in (d1, d2) for p in d.glob("*.xdelta")}
        class Local:
            def download(self, asset, *args):
                return files[asset.name]
        output = self.root / "chained.vpk"
        apply_plan(source, output, cat.plan(original), cat, Local(), cache=self.root / "cache")
        self.assertEqual(output.read_bytes(), (self.root / "1.2.vpk").read_bytes())
        self.assertEqual(source.read_bytes(), self.base)
        self.assertEqual(list(self.root.glob(".retro-trans-*")), [])
        delta = self.root / "manual.xdelta"
        with patch("retro_trans.core.GitHubClient.open", side_effect=AssertionError("Network used")):
            manual_patch(source, output, delta, create=True, cache=self.root / "cache")
            manual_patch(source, delta, self.root / "manual.vpk", cache=self.root / "cache")
        self.assertEqual((self.root / "manual.vpk").read_bytes(), output.read_bytes())

    def test_failed_intermediate_output_and_cancel_leave_no_final(self):
        r1, d1 = self.build("original", "1.1")
        r2, d2 = self.build("1.1", "1.2")
        files = {p.name: p for d in (d1, d2) for p in d.glob("*.xdelta")}
        class Local:
            def download(self, asset, *args):
                return files[asset.name]
        broken = copy.deepcopy(r2)
        broken["manifest"]["patches"][0]["target_sha256"] = "0" * 64
        cat = Catalog({"schema_version": 1, "releases": [r1, broken]})
        source = self.root / "original.vpk"
        plan = cat.plan(recognize(source, cat)[0])
        output = self.root / "broken.vpk"
        with self.assertRaisesRegex(PatchError, "Intermediate"):
            apply_plan(source, output, plan, cat, Local(), cache=self.root / "cache")
        self.assertFalse(output.exists())
        self.assertEqual(list(self.root.glob(".retro-trans-*")), [])
        cancel = threading.Event()
        def progress(message, fraction):
            if message.startswith("Step 1/"):
                cancel.set()
        with self.assertRaises(Cancelled):
            apply_plan(source, output, plan, cat, Local(), cache=self.root / "cache", cancel=cancel, progress=progress)
        self.assertFalse(output.exists())
        self.assertEqual(source.read_bytes(), self.base)

    def test_release_corruption_missing_assets_and_existing_directory(self):
        record, directory = self.build("original", "1.1", edition="best")
        with self.assertRaisesRegex(PatchError, "already exists"):
            self.build("original", "1.1")
        delta = directory / record["manifest"]["patches"][0]["patch"]
        data = delta.read_bytes()
        delta.write_bytes(b"corrupt")
        with self.assertRaises(PatchError):
            validate_directory(directory)
        delta.write_bytes(data)
        delta.unlink()
        with self.assertRaises(PatchError):
            validate_directory(directory)

    def test_one_release_multiple_editions_full_and_incremental(self):
        rows = []
        for edition in ("original", "best"):
            for source in ("original", "1.1"):
                rows.append({"patch": edition + "-" + source + ".xdelta", "edition": edition,
                    "language": "en", "source_version": source, "source_format": "bin", "target_format": "bin",
                    "source": source + ".vpk", "target": "1.2.vpk"})
        config = {"game_id": "fixture", "game_name": "Fixture", "platform": "Test", "version": "1.2",
            "source_commit": "a" * 40, "patches": rows}
        path = self.root / "multiple.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        output = self.root / "multiple-release"
        result = build_release(path, output, cache=self.root / "cache")
        self.assertEqual(len(result["patches"]), 4)
        self.assertEqual(validate_directory(output), result)


if __name__ == "__main__":
    unittest.main()
