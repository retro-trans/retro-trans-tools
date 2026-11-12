import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from retro_trans.catalog import Catalog, apply_plan, assert_immutable, recognize, scan_root, validate_manifest
from retro_trans.combined import CombinedSource, concatenate
from retro_trans.core import Cancelled, PatchError, sha256_file
from retro_trans.release import build_release, validate_directory


class CombinedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.game = self.root / 'game'; self.game.mkdir()
        self.a = self.game / 'game.exe'; self.b = self.game / 'game.tpatch'
        self.a.write_bytes(bytes(range(256)) * 1024)
        self.b.write_bytes(b'official update' * 4000)
        (self.game / 'progress.sav').write_bytes(b'user progress')
        self.target = self.root / 'english.exe'
        self.target.write_bytes(self.a.read_bytes() + b'English' + self.b.read_bytes())
        self.ids = [dict(platform='PC', kind='steam-app-id', id='2283710')]
        self.library = dict(schema_version=1, games=[dict(game_id='fixture', name='Fixture',
            repo='retro-trans/fixture', package_ids=self.ids)], vita_releases=[])
        self.config = dict(game_id='fixture', game_name='Fixture', platform='PC', version='0.8.0',
            package_ids=self.ids, source_commit='a' * 40, patches=[dict(patch='full.xdelta',
                edition='Steam', language='en', source_version='original', source_format='bin', target_format='exe',
                source_files=[dict(name='game.exe', source=str(self.a)), dict(name='game.tpatch', source=str(self.b))],
                target=str(self.target))])

    def build(self, config=None, name='release'):
        config = config or self.config
        path = self.root / (name + '.json'); path.write_text(json.dumps(config), encoding='utf-8')
        output = self.root / name
        manifest = build_release(path, output, cache=self.root / 'cache', library=self.library)
        record = dict(repo='retro-trans/fixture', tag='v' + config['version'], manifest=manifest,
            assets={p['patch']: 'https://github.com/retro-trans/fixture/releases/download/v' + config['version'] + '/' + p['patch']
                    for p in manifest['patches']})
        return record, output

    def test_real_full_and_incremental_routes_preserve_every_input(self):
        first, release = self.build()
        self.assertEqual(validate_directory(release), first['manifest'])
        self.assertEqual(first['manifest']['schema_version'], 3)
        self.assertNotIn(str(self.root), (release / 'BUILD-MANIFEST.json').read_text())
        upgrade = copy.deepcopy(self.config)
        upgrade['version'] = '0.8.1'
        next_target = self.root / 'next.exe'; next_target.write_bytes(self.target.read_bytes() + b'correction')
        row = upgrade['patches'][0]
        row.pop('source_files'); row.update(source=str(self.target), target=str(next_target), source_format='exe',
            source_version='0.8.0', patch='upgrade.xdelta')
        second, release2 = self.build(upgrade, 'upgrade-release')
        cat = Catalog(dict(schema_version=1, releases=[first, second]))
        before = {p.name: p.read_bytes() for p in self.game.iterdir()}
        source = recognize(self.a, cat)[0]
        self.assertIsInstance(source, CombinedSource)
        self.assertEqual(len(scan_root(self.game, cat)), 1)
        self.assertIsInstance(recognize(self.b, cat)[0], CombinedSource)
        self.assertIsInstance(recognize(self.game, cat)[0], CombinedSource)
        self.assertEqual(cat.plan(source, 'Next version only').target.version, '0.8.0')
        self.assertEqual(len(cat.plan(source).edges), 2)
        client = Mock()
        client.download.side_effect = lambda asset, *args: (release if asset.name == 'full.xdelta' else release2) / asset.name
        out = self.root / 'latest.exe'
        apply_plan(self.a, out, cat.plan(source), cat, client=client, cache=self.root / 'cache')
        self.assertEqual(out.read_bytes(), next_target.read_bytes())
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.game.iterdir()})
        old_english = recognize(self.target, cat)[0]
        self.assertNotIsInstance(old_english, CombinedSource)
        out2 = self.root / 'updated.exe'
        apply_plan(self.target, out2, cat.plan(old_english), cat, client=client, cache=self.root / 'cache')
        self.assertEqual(out2.read_bytes(), next_target.read_bytes())
        current = recognize(out2, cat)[0]
        self.assertEqual(cat.plan(current).edges, ())
        self.assertFalse(list(self.root.glob('.retro-trans-*')))

    def test_missing_changed_duplicate_and_input_overwrite_are_blocked(self):
        record, _ = self.build()
        cat = Catalog(dict(schema_version=1, releases=[record]))
        source = recognize(self.a, cat)[0]
        plan = cat.plan(source)
        self.b.unlink()
        partial = recognize(self.a, cat)[0]
        with self.assertRaisesRegex(PatchError, 'Missing'):
            cat.plan(partial)
        with self.assertRaises(PatchError):
            apply_plan(self.a, self.root / 'missing.exe', plan, cat)
        self.b.write_bytes(b'official update' * 4000)
        self.b.write_bytes(b'X' + self.b.read_bytes()[1:])
        with self.assertRaisesRegex(PatchError, 'Unsupported'):
            cat.plan(recognize(self.a, cat)[0])
        client = Mock()
        with self.assertRaisesRegex(PatchError, 'verification'):
            apply_plan(self.a, self.root / 'changed.exe', plan, cat, client=client)
        client.download.assert_not_called()
        with self.assertRaises(PatchError):
            apply_plan(self.a, self.a, plan, cat)
        self.assertFalse((self.root / 'changed.exe').exists())
        self.assertFalse(list(self.root.glob('.retro-trans-*')))

    def test_metadata_order_schema_and_identity_are_strict(self):
        record, _ = self.build()
        manifest = record['manifest']
        for field, value in [('schema_version', 1), ('schema_version', 2), ('min_app_version', '0.5.22')]:
            bad = copy.deepcopy(manifest); bad[field] = value
            with self.assertRaises(PatchError): validate_manifest(bad)
        for change in ('duplicate', 'path', 'size', 'method', 'private'):
            bad = copy.deepcopy(manifest); definition = bad['patches'][0]['combined_source']
            if change == 'duplicate': definition['files'][1]['name'] = 'GAME.EXE'
            if change == 'path': definition['files'][0]['name'] = '../game.exe'
            if change == 'size': definition['files'][0]['bytes'] += 1
            if change == 'method': definition['method'] = 'guess'
            if change == 'private': definition['files'][0]['source'] = str(self.a)
            with self.assertRaises(PatchError): validate_manifest(bad)
        cat = Catalog(dict(schema_version=1, releases=[record]))
        altered = copy.deepcopy(record)
        altered['manifest']['patches'][0]['combined_source']['files'].reverse()
        with self.assertRaisesRegex(PatchError, 'identity'):
            assert_immutable(cat, Catalog(dict(schema_version=1, releases=[altered])))
        reversed_cat = Catalog(dict(schema_version=1, releases=[altered]))
        src = recognize(self.a, reversed_cat)[0]
        with self.assertRaisesRegex(PatchError, 'Combined source failed'):
            apply_plan(self.a, self.root / 'wrong-order.exe', reversed_cat.plan(src), reversed_cat)

    def test_cancellation_and_reuse_issued_delta(self):
        first, release = self.build()
        config = copy.deepcopy(self.config)
        config['patches'][0]['patch_source'] = str(release / 'full.xdelta')
        again, imported = self.build(config, 'imported')
        self.assertEqual(sha256_file(release / 'full.xdelta'), sha256_file(imported / 'full.xdelta'))
        cat = Catalog(dict(schema_version=1, releases=[again]))
        source = recognize(self.a, cat)[0]
        cancel = threading.Event(); cancel.set()
        with self.assertRaises(Cancelled):
            apply_plan(self.a, self.root / 'cancelled.exe', cat.plan(source), cat, cancel=cancel)
        self.assertFalse((self.root / 'cancelled.exe').exists())
        self.assertFalse(list(self.root.glob('.retro-trans-*')))
        bad = self.root / 'corrupt.xdelta'; bad.write_bytes(b'broken')
        config['patches'][0]['patch_source'] = str(bad)
        with self.assertRaises(PatchError): self.build(config, 'bad-import')
        self.assertFalse((self.root / 'bad-import').exists())


if __name__ == '__main__':
    unittest.main()
