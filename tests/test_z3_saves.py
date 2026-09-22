"""Synthetic fixtures only: endian conversion, metadata, isolation, ZIPs."""
from pathlib import Path
import struct
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from retro_trans import z3_saves as c
from retro_trans.core import Cancelled


def binary(kind, platform):
    size, used, offsets, start = c.FORMATS[kind]
    b = bytearray(size)
    struct.pack_into('<H', b, 2, 101)
    struct.pack_into('>I' if platform == 'ps3' else '<I', b, 4, used)
    struct.pack_into('<' + 'I' * len(offsets), b, 8, *offsets)
    b[0x50:0x56] = b'SUMMAR'
    b[start + 32:start + 36] = b'BODY'
    struct.pack_into('<H', b, 0, c.checksum(b, start, size - start))
    struct.pack_into('<H', b, 0x40, c.checksum(b, 0x44, 0x3FC))
    return bytes(b)


def sfo(folder, kind):
    text = {'TITLE': '第３次スーパーロボット大戦Ｚ　時獄篇', 'SUB_TITLE': 'test slot',
            'DETAIL': 'synthetic source description', 'SAVEDATA_DIRECTORY': folder,
            'SAVEDATA_LIST_PARAM': 'SYSTEM' if kind == 'SYSTEM.BIN' else 'STAGE'}
    fields = [('ACCOUNT_ID', 4, b'A' * 16, 16)]
    fields += [(k, 0x204, v.encode() + b'\0', 512) for k, v in text.items()]
    keys, values, records = bytearray(), bytearray(), bytearray()
    for key, typ, data, cap in fields:
        records.extend(struct.pack('<HHIII', len(keys), typ, len(data), cap, len(values)))
        keys.extend(key.encode() + b'\0')
        values.extend(data.ljust(cap, b'\0'))
    keyoff = 20 + len(records)
    valueoff = keyoff + len(keys)
    return struct.pack('<4s4I', b'\0PSF', 0x101, keyoff, valueoff, len(fields)) + records + keys + values


def inputs(root):
    ps3, vita = root / 'ps3', root / c.VITA_ID
    for slot in (0, 1, 4):
        kind = 'SYSTEM.BIN' if slot == 0 else 'STAGE.BIN'
        folder = c.PS3_ID + ('-SYS' if slot == 0 else '-STG-%03d' % (slot - 1))
        c.put_files(ps3, {folder + '/' + kind: binary(kind, 'ps3'),
                         folder + '/PARAM.SFO': sfo(folder, kind),
                         folder + '/ICON0.PNG': b'fixture-icon', folder + '/PIC1.PNG': b'fixture-picture'})
    for slot in (0, 1):
        kind = 'SYSTEM.BIN' if slot == 0 else 'STAGE.BIN'
        folder = c.VITA_ID + ('-SYS' if slot == 0 else '-STG-%03d' % slot)
        text = c.sfo_text(sfo(folder, kind))
        meta = c.make_slot(bytes(0x34C), text, kind, 1788518217)
        c.put_files(vita, {folder + '/' + kind: binary(kind, 'vita'), 'SlotParam_%d.bin' % slot: meta})
    return ps3, vita


class SaveConversionTests(unittest.TestCase):
    def test_exact_round_trip_both_kinds_and_directions(self):
        for kind in c.FORMATS:
            for platform, target in (('ps3', 'vita'), ('vita', 'ps3')):
                with self.subTest(kind=kind, platform=platform):
                    b = binary(kind, platform)
                    out = c.convert(b, kind, platform, target)
                    self.assertEqual(out[:4], b[:4])
                    self.assertEqual(out[8:], b[8:])
                    self.assertEqual(c.convert(out, kind, target, platform), b)

    def test_bad_checksums_layout_version_size_and_platform_rejected(self):
        original = binary('STAGE.BIN', 'ps3')
        for offset in (0, 2, 4, 8, 32, 0x40, 0x50, 0x460):
            b = bytearray(original)
            b[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                c.convert(b, 'STAGE.BIN', 'ps3', 'vita')
        for bad in (original[:-1], original + b'\0'):
            with self.assertRaises(ValueError):
                c.inspect(bad, 'STAGE.BIN', 'ps3')
        with self.assertRaises(ValueError):
            c.inspect(original, 'STAGE.BIN', 'vita')

    def test_checksum_matches_native_excluded_final_word(self):
        data = struct.pack('<4H', 0xFFFF, 2, 3, 0x9999)
        self.assertEqual(c.checksum(data, 0, 8), 4)
        self.assertEqual(c.checksum(data, 0, 2), 0)

    def test_sfo_preserves_unrelated_account_and_directory_fields(self):
        original = sfo('NPJB00520-STG-000', 'STAGE.BIN')
        changed = c.update_sfo(original, {'DETAIL': 'Vita progress → PS3'})
        self.assertEqual(c.sfo_text(changed)['DETAIL'], 'Vita progress → PS3')
        entry = c.sfo_fields(original)['ACCOUNT_ID']
        start, capacity = entry[2], entry[4]
        self.assertEqual(original[start:start + capacity], changed[start:start + capacity])
        self.assertEqual(c.sfo_text(original)['SAVEDATA_DIRECTORY'], c.sfo_text(changed)['SAVEDATA_DIRECTORY'])
        with self.assertRaises(ValueError):
            c.update_sfo(original, {'DETAIL': 'X' * 600})
        with self.assertRaises(ValueError):
            c.sfo_fields(original[:-400])

    def test_slot_utf8_fields_and_overflow(self):
        text = {'TITLE': '時獄篇', 'SUB_TITLE': '第４話', 'DETAIL': '変換テスト'}
        meta = c.make_slot(bytes(0x34C), text, 'STAGE.BIN', 1788518217)
        self.assertEqual(c.slot_text(meta), text)
        self.assertIn(b'icon_stg.png', meta)
        with self.assertRaises(ValueError):
            c.make_slot(meta, dict(text, TITLE='x' * 64), 'STAGE.BIN', 1788518217)
        with self.assertRaises(ValueError):
            c.slot_text(meta[:-1])

    def test_slot_mapping_system_and_manual(self):
        with tempfile.TemporaryDirectory() as folder:
            ps3, vita = inputs(Path(folder))
            outputs, mapping = c.packages(c.load_ps3(ps3), c.load_vita(vita))
            self.assertIn('PCSG00264/PCSG00264-STG-004/STAGE.BIN', outputs['rpcs3-to-vita3k'])
            self.assertIn('PCSG00264/SlotParam_4.bin', outputs['rpcs3-to-vita3k'])
            self.assertIn('savedata/NPJB00520-STG-000/STAGE.BIN', outputs['vita3k-to-rpcs3'])
            self.assertEqual(len(mapping), 5)
            self.assertTrue(all(m['round_trip_exact'] for m in mapping))

    def test_missing_slot_and_unknown_files_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            ps3, vita = inputs(Path(folder))
            c.put_files(vita, {'unknown.txt': b'unknown'})
            with self.assertRaises(ValueError):
                c.load_vita(vita)
            c.put_files(ps3 / 'NPJB00520-STG-000', {'PARAM.PFD': b'physical-container'})
            with self.assertRaises(ValueError):
                c.load_ps3(ps3)

    def test_build_backups_zip_readback_and_no_live_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ps3, vita = inputs(root)
            before = c.source_blobs(c.load_ps3(ps3), c.load_vita(vita))
            output = root / 'work' / 'converted'
            report = c.build(ps3, vita, output, write=False)
            self.assertFalse(output.exists())
            report = c.build(ps3, vita, output, write=True, expected_sources=report['source_files'])
            with self.assertRaises(ValueError):
                c.build(ps3, vita, output, write=True)
            self.assertEqual(c.source_blobs(c.load_ps3(ps3), c.load_vita(vita)), before)
            for name, data in before.items():
                self.assertEqual((output / 'original-backups' / name).read_bytes(), data)
            for package in report['packages'].values():
                with zipfile.ZipFile(str(output / package['name'])) as archive:
                    for name, expected in package['files'].items():
                        self.assertEqual(c.row(archive.read(name)), expected)

    def test_output_write_refuses_overwrite_and_path_traversal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            c.put_files(root, {'safe.bin': b'original'})
            with self.assertRaises(FileExistsError):
                c.put_files(root, {'safe.bin': b'changed'})
            for name in ('../escape', '/absolute', 'C:/escape', 'a\\b'):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    c.put_files(root, {name: b'bad'})
            self.assertEqual((root / 'safe.bin').read_bytes(), b'original')

    def test_single_direction_and_unrelated_games_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ps3, vita = inputs(root)
            c.put_files(ps3, {'OTHER-GAME/save.bin': b'unrelated'})
            for direction in c.DIRECTIONS:
                output = root / direction
                report = c.build(ps3, vita, output, write=True, direction=direction)
                self.assertEqual(set(report['packages']), {direction})
                self.assertEqual({m['direction'] for m in report['mappings']}, {direction})
                self.assertFalse((output / next(d for d in c.DIRECTIONS if d != direction)).exists())
                self.assertTrue((output / 'original-backups').is_dir())
            self.assertEqual((ps3 / 'OTHER-GAME/save.bin').read_bytes(), b'unrelated')
            with self.assertRaisesRegex(ValueError, 'direction'):
                c.build(ps3, vita, root / 'bad', direction='unknown')

    def test_existing_and_live_output_paths_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ps3, vita = inputs(root)
            original = c.source_blobs(c.load_ps3(ps3), c.load_vita(vita))
            for output in (ps3, vita, ps3 / 'converted', vita / 'converted', root):
                with self.subTest(output=output), self.assertRaises(ValueError):
                    c.build(ps3, vita, output, write=True)
            self.assertEqual(c.source_blobs(c.load_ps3(ps3), c.load_vita(vita)), original)

    def test_changed_sources_require_new_check(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ps3, vita = inputs(root)
            output = root / 'new'
            checked = c.build(ps3, vita, output)
            # A valid metadata change must invalidate a previously checked profile.
            (ps3 / 'NPJB00520-SYS/ICON0.PNG').write_bytes(b'new icon')
            with self.assertRaisesRegex(ValueError, 'changed since checking'):
                c.build(ps3, vita, output, write=True, expected_sources=checked['source_files'])
            self.assertFalse(output.exists())

    def test_source_changes_during_write_rejected_and_cleaned(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ps3, vita = inputs(root)
            def progress(message, fraction):
                if fraction == .85:
                    (ps3 / 'NPJB00520-SYS/ICON0.PNG').write_bytes(b'changed by emulator')
            with self.assertRaisesRegex(ValueError, 'changed during conversion'):
                c.build(ps3, vita, root / 'new', write=True, progress=progress)
            self.assertFalse((root / 'new').exists())
            self.assertEqual(list(root.glob('.z3-conversion-*')), [])

    def test_cancellation_during_each_phase_cleans_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ps3, vita = inputs(root)
            before = c.source_blobs(c.load_ps3(ps3), c.load_vita(vita))
            for phase in ('Reading', 'Checking', 'Backing', 'Writing', 'Verifying'):
                cancel = threading.Event()
                def progress(message, fraction):
                    if message.startswith(phase):
                        cancel.set()
                with self.subTest(phase=phase), self.assertRaises(Cancelled):
                    c.build(ps3, vita, root / 'new', write=True, cancel=cancel, progress=progress)
                self.assertFalse((root / 'new').exists())
                self.assertEqual(list(root.glob('.z3-conversion-*')), [])
            self.assertEqual(c.source_blobs(c.load_ps3(ps3), c.load_vita(vita)), before)

    def test_disk_space_write_failure_and_collision_preserve_existing_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ps3, vita = inputs(root)
            output = root / 'new'
            with patch.object(c.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)):
                with self.assertRaisesRegex(ValueError, 'disk space'):
                    c.build(ps3, vita, output, write=True)
            with patch.object(c, 'make_zip', side_effect=OSError('disk failure')):
                with self.assertRaisesRegex(OSError, 'disk failure'):
                    c.build(ps3, vita, output, write=True)
            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob('.z3-conversion-*')), [])
            def collision(message, fraction):
                if fraction == .85:
                    output.mkdir()
                    (output / 'keep.txt').write_bytes(b'existing output')
            with self.assertRaises(FileExistsError):
                c.build(ps3, vita, output, write=True, progress=collision)
            self.assertEqual((output / 'keep.txt').read_bytes(), b'existing output')
            self.assertEqual(list(root.glob('.z3-conversion-*')), [])


if __name__ == '__main__':
    unittest.main()
