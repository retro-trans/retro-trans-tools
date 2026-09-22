import dataclasses
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from retro_trans.core import (Asset, Cancelled, GitHubClient, Patch, PatchError,
    Release, decode, ensure_engine, identify_source, parse_manifest, patch_binary,
    safe_name, sha256_file, validate_repo)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fixture(source=b"original game", target=b"translated game", delta=b"delta"):
    asset = Asset("translation.xdelta", "https://github.com/retro-trans/test/releases/download/v1/translation.xdelta", len(delta), sha(delta))
    p = Patch(asset, "original", "", sha(source), len(source), sha(target), len(target))
    return Release("retro-trans/test", "v1", "https://github.com/retro-trans/test/releases/tag/v1", (p,))


class MemoryClient(GitHubClient):
    def __init__(self, content):
        self.content = content
        self.calls = 0

    def open(self, url):
        self.calls += 1
        return io.BytesIO(self.content)


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "original.bin"
        self.source.write_bytes(b"original game")
        self.release = fixture()

    def tearDown(self):
        self.temp.cleanup()

    def test_source_matches_by_hash_not_filename(self):
        self.assertEqual(identify_source(self.source, self.release), self.release.patches[0])

    def test_wrong_source_same_size_rejected(self):
        self.source.write_bytes(b"different rom")
        with self.assertRaisesRegex(PatchError, "does not match"):
            identify_source(self.source, self.release)

    def test_wrong_size_rejected_before_hash(self):
        self.source.write_bytes(b"x")
        with patch("retro_trans.core.sha256_file") as digest:
            with self.assertRaisesRegex(PatchError, "size"):
                identify_source(self.source, self.release)
            digest.assert_not_called()

    def test_already_patched_identified(self):
        self.source.write_bytes(b"translated game")
        with self.assertRaisesRegex(PatchError, "already patched"):
            identify_source(self.source, self.release)

    def test_upgrade_selected_from_multiple_editions(self):
        upgrade = dataclasses.replace(self.release.patches[0], source_version="0.9.79")
        other = dataclasses.replace(upgrade, source_sha256="0" * 64, edition="best")
        release = dataclasses.replace(self.release, patches=(other, upgrade))
        self.assertEqual(identify_source(self.source, release), upgrade)

    def test_invalid_chd_is_rejected(self):
        source = self.root / "game.chd"
        source.write_bytes(b"original game")
        with self.assertRaisesRegex(PatchError, "CHD header"):
            identify_source(source, self.release)

    def test_cancel_hash(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            sha256_file(self.source, cancel)

    def test_download_hash_and_cache_revalidation(self):
        client = MemoryClient(b"delta")
        asset = self.release.patches[0].asset
        cached = client.download(asset, self.root / "cache")
        self.assertEqual(cached.read_bytes(), b"delta")
        client.download(asset, cached.parent)
        self.assertEqual(client.calls, 1)
        cached.write_bytes(b"wrong")
        client.download(asset, cached.parent)
        self.assertEqual(client.calls, 2)
        self.assertEqual(cached.read_bytes(), b"delta")

    def test_corrupt_and_truncated_downloads_removed(self):
        for data in (b"wrong", b"delt", b"deltaextra"):
            with self.subTest(data=data):
                with self.assertRaises(PatchError):
                    MemoryClient(data).download(self.release.patches[0].asset, self.root / "cache")
                self.assertEqual(list((self.root / "cache").iterdir()), [])

    def test_cancel_download_removes_partial(self):
        cancel = threading.Event()
        with self.assertRaises(Cancelled):
            MemoryClient(b"delta").download(self.release.patches[0].asset, self.root / "cache",
                cancel, lambda *args: cancel.set())
        self.assertEqual(list((self.root / "cache").iterdir()), [])

    def test_source_cannot_be_output(self):
        with self.assertRaisesRegex(PatchError, "different output"):
            patch_binary(self.source, self.source, self.release)
        self.assertEqual(self.source.read_bytes(), b"original game")

    def test_existing_output_never_overwritten(self):
        output = self.root / "result.bin"
        output.write_bytes(b"keep me")
        with self.assertRaisesRegex(PatchError, "already exists"):
            patch_binary(self.source, output, self.release)
        self.assertEqual(output.read_bytes(), b"keep me")

    def fake_engine(self, *args):
        directory = self.root / "engine"
        directory.mkdir()
        engine = directory / "xdelta3.exe"
        engine.write_bytes(b"test placeholder")
        return engine

    def apply_fake(self, target=b"translated game", progress=None):
        def fake_decode(engine, source, delta, temporary, *args):
            temporary.write_bytes(target)
        with patch("retro_trans.core.ensure_engine", self.fake_engine), patch("retro_trans.core.decode", fake_decode):
            return patch_binary(self.source, self.root / "result.bin", self.release,
                MemoryClient(b"delta"), self.root / "cache", progress=progress)

    def test_verified_output_saved_original_unchanged(self):
        self.apply_fake()
        self.assertEqual((self.root / "result.bin").read_bytes(), b"translated game")
        self.assertEqual(self.source.read_bytes(), b"original game")
        self.assertEqual(list(self.root.glob(".retro-trans-*")), [])
        self.assertFalse((self.root / "engine").exists())

    def test_bad_output_removed(self):
        for data in (b"wrong", b"not-translated!"):
            with self.subTest(data=data):
                with self.assertRaisesRegex(PatchError, "verification failed"):
                    self.apply_fake(data)
                self.assertFalse((self.root / "result.bin").exists())
                self.assertEqual(list(self.root.glob(".retro-trans-*")), [])
                self.assertFalse((self.root / "engine").exists())

    def test_destination_created_during_patch_is_preserved(self):
        def progress(message, fraction):
            if message == "Verifying patched copy":
                (self.root / "result.bin").write_bytes(b"created by someone else")
        with self.assertRaisesRegex(PatchError, "now exists"):
            self.apply_fake(progress=progress)
        self.assertEqual((self.root / "result.bin").read_bytes(), b"created by someone else")

    def test_invalid_repositories_and_asset_names(self):
        for name in ("../evil", "C:\\evil", "good/bad.xdelta", "bad:stream", "..", "file."):
            with self.assertRaises(PatchError):
                safe_name(name)
        for repo in ("elsewhere/repo", "retro-trans/repo/../../evil", "retro-trans/repo?query"):
            with self.assertRaises(PatchError):
                validate_repo(repo)

    def manifest(self):
        p = self.release.patches[0]
        return {"patches": [{"patch": p.asset.name, "edition": "original",
            "source_sha256": p.source_sha256, "source_bytes": p.source_bytes,
            "target_sha256": p.target_sha256, "target_bytes": p.target_bytes,
            "patch_sha256": p.asset.sha256, "patch_bytes": p.asset.size}]}

    def test_manifest_parses_actual_release_schema(self):
        asset = self.release.patches[0].asset
        self.assertEqual(parse_manifest(self.manifest(), {asset.name: asset}), list(self.release.patches))

    def test_manifest_mismatch_and_missing_fields_rejected(self):
        asset = self.release.patches[0].asset
        for field, value in (("patch_sha256", "0" * 64), ("patch_bytes", 100), ("target_bytes", -1), ("source_sha256", "bad")):
            manifest = self.manifest()
            manifest["patches"][0][field] = value
            with self.subTest(field=field), self.assertRaises(PatchError):
                parse_manifest(manifest, {asset.name: asset})
        manifest = self.manifest()
        del manifest["patches"][0]["source_sha256"]
        with self.assertRaises(PatchError):
            parse_manifest(manifest, {asset.name: asset})

    def test_release_fetch_verifies_manifest_digest(self):
        payload = json.dumps(self.manifest()).encode()
        asset = self.release.patches[0].asset
        metadata = {"tag_name": "v1", "assets": [
            {"name": asset.name, "size": asset.size, "digest": "sha256:" + asset.sha256, "browser_download_url": asset.url},
            {"name": "BUILD-MANIFEST-v1.json", "size": len(payload), "digest": "sha256:" + sha(payload),
             "browser_download_url": "https://github.com/retro-trans/test/releases/download/v1/BUILD-MANIFEST-v1.json"}]}
        client = MemoryClient(payload)
        with patch.object(client, "json", return_value=metadata):
            self.assertEqual(client.latest("retro-trans/test").patches, self.release.patches)
            client.content = payload.replace(b"original", b"modified")
            with self.assertRaisesRegex(PatchError, "manifest failed"):
                client.latest("retro-trans/test")


@unittest.skipUnless(os.environ.get("RETRO_TRANS_ONLINE_TEST") == "1", "Set RETRO_TRANS_ONLINE_TEST=1 for live GitHub + xdelta tests")
class OnlineTests(unittest.TestCase):
    def test_live_manifest_patch_downloads_and_real_roundtrip(self):
        client = GitHubClient()
        cache = Path(__file__).resolve().parents[1] / ".test-cache"
        release = client.latest("retro-trans/SRW-Z")
        self.assertGreaterEqual(len(release.patches), 1)
        for p in release.patches:
            downloaded = client.download(p.asset, cache)
            self.assertEqual(sha256_file(downloaded), p.asset.sha256)
        engine = ensure_engine(client, cache)
        try:
            with tempfile.TemporaryDirectory(prefix="retro-trans-test-") as root:
                root = Path(root)
                # Unicode/spaces and a nontrivial source exercise real process paths
                # and source-copy instructions, not just an all-literal patch.
                source = root / "original 日本語 game.bin"
                target = root / "translated game.bin"
                output = root / "verified copy.bin"
                delta = root / "sample.xdelta"
                data = b"".join(hashlib.sha256(str(i).encode()).digest() for i in range(32768))
                translated = data[:10000] + b"English translation!" * 100 + data[12000:]
                source.write_bytes(data)
                target.write_bytes(translated)
                subprocess.run([str(engine), "-e", "-s", str(source), str(target), str(delta)], check=True, capture_output=True)
                test_release = fixture(data, translated, delta.read_bytes())
                with patch("retro_trans.core.ensure_engine", return_value=engine):
                    patch_binary(source, output, test_release, MemoryClient(delta.read_bytes()), cache)
                self.assertEqual(output.read_bytes(), translated)
                self.assertEqual(source.read_bytes(), data)
        finally:
            engine.unlink(missing_ok=True)
            if engine.parent.exists():
                engine.parent.rmdir()


if __name__ == "__main__":
    unittest.main()
