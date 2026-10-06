import contextlib
import hashlib
import io
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

from retro_trans import mx_saves as mx
from retro_trans.core import Cancelled
from retro_trans.ps2_memcard import Card


def ps2_payload(kind='scenario'):
    data = bytearray(mx.SIZES[kind])
    if kind == 'scenario':
        struct.pack_into('<2I', data, 0, 1, 1)
        struct.pack_into('<H', data, 0x1400, 143)
        struct.pack_into('<H', data, 0x3400, 333)
        struct.pack_into('<3I', data, 0xC810, 2, 9, 8200)
    # Fixture checksums computed independently, before using the implementation.
    for start, end, dest in ((0, len(data) - 1024, len(data) - 4),
                             (len(data) - 1024, len(data) - 8, len(data) - 8)):
        total = 0x78945612
        for offset in range(start, end, 4):
            total += int.from_bytes(data[offset:offset + 4], 'little')
        data[dest:dest + 4] = (total & 0xFFFFFFFF).to_bytes(4, 'little')
    return bytes(data)


def sfo(name='ULJS000410000', mode=3):
    params = bytearray(128)
    params[0] = {0: 0, 1: 1, 3: 0x21, 5: 0x41}[mode]
    file_list = b'DATA.BIN\0'.ljust(13, b'\0') + (b'\x55' if mode else b'\0') * 16 + b'\0' * 3
    values = [('SAVEDATA_DIRECTORY', 0x204, name.encode() + b'\0'),
              ('SAVEDATA_PARAMS', 4, bytes(params)),
              ('SAVEDATA_FILE_LIST', 4, file_list),
              ('TITLE', 0x204, b'MX test fixture\0')]
    keys, content, entries = bytearray(), bytearray(), bytearray()
    for key, typ, value in values:
        entries += struct.pack('<HHIII', len(keys), typ, len(value), len(value), len(content))
        keys += key.encode() + b'\0'
        content += value
    key_start = 20 + len(entries)
    return struct.pack('<4s4I', b'\0PSF', 0x101, key_start, key_start + len(keys), len(values)) + entries + keys + content


def card_image(ecc=False):
    data = bytearray(64 * 1024)
    struct.pack_into('<28s12sHHHH6I', data, 0, b'Sony PS2 Memory Card Format ',
                     b'1.2.0.0', 512, 2, 16, 0, 64, 4, 60, 0, 63, 62)
    struct.pack_into('<I', data, 80, 1)  # indirect list points to physical cluster 1
    struct.pack_into('<I', data, 1024, 2)  # indirect cluster points to FAT cluster 2
    for i in range(60):
        struct.pack_into('<I', data, 2048 + i * 4, 0x7FFFFFFF)
    for chain in ([0, 1], [2, 3], list(range(4, 57))):
        for index, current in enumerate(chain):
            value = 0x80000000 | chain[index + 1] if index + 1 < len(chain) else 0xFFFFFFFF
            struct.pack_into('<I', data, 2048 + current * 4, value)

    def entry(offset, name, directory, length, cluster):
        struct.pack_into('<HHI8sII8sI28x448s', data, offset,
                         0x8027 if directory else 0x8017, 0, length,
                         bytes(8), cluster, 0, bytes(8), 0, name.encode())

    entry(4096, '.', True, 3, 0)
    entry(4608, '..', True, 3, 0)
    entry(5120, 'BISLPS-25345S00', True, 3, 2)
    entry(6144, '.', True, 3, 2)
    entry(6656, '..', True, 3, 0)
    entry(7168, 'BISLPS-25345S00', False, mx.SIZES['scenario'], 4)
    data[8192:8192 + mx.SIZES['scenario']] = ps2_payload()
    if ecc:
        return b''.join(data[i:i + 512] + b'\xee' * 16 for i in range(0, len(data), 512))
    return bytes(data)


class IntegrityTests(unittest.TestCase):
    def test_checksum_regions_and_sizes(self):
        for kind in mx.SIZES:
            original = ps2_payload(kind)
            mx.validate_ps2(original)
            for offset in (0, len(original) - 1028, len(original) - 1024,
                           len(original) - 32, len(original) - 12, len(original) - 8,
                           len(original) - 4):
                with self.subTest(kind=kind, offset=offset):
                    broken = bytearray(original)
                    broken[offset] ^= 1
                    with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                        mx.validate_ps2(broken)
            with self.assertRaises(ValueError):
                mx.validate_ps2(original[:-4])

    def test_modes_preserve_every_unrelated_byte(self):
        for kind in mx.SIZES:
            original = ps2_payload(kind)
            self.assertEqual(mx.inspect_balance(original), {'status': 'absent', 'mode': 'original'})
            for mode in ('original', 'psp'):
                result = mx.with_balance(original, mode)
                self.assertEqual(mx.inspect_balance(result), {'status': 'valid', 'mode': mode})
                self.assertEqual(len(result), len(original))
                self.assertEqual(result[:-32], original[:-32])
                self.assertEqual(result[-20:-8], original[-20:-8])
                mx.validate_ps2(result)

    def test_unknown_markers_refused(self):
        for marker in ((mx.BALANCE_MAGIC, 2, 0), (mx.BALANCE_MAGIC, 1, 2), (1, 0, 0)):
            data = bytearray(ps2_payload())
            struct.pack_into('<3I', data, len(data) - 32, *marker)
            struct.pack_into('<2I', data, len(data) - 8, *mx.checksum_words(data))
            self.assertEqual(mx.inspect_balance(data)['status'], 'unsupported')
            with self.assertRaisesRegex(ValueError, 'refusing'):
                mx.with_balance(data, 'original')

    def test_scenario_fields_and_invalid_counts(self):
        result = mx.inspect_scenario(ps2_payload())
        self.assertEqual((result['funds'], result['completed_maps'], result['turns']), (8200, 2, 9))
        self.assertEqual(result['unit_ids'], [143])
        self.assertEqual(result['pilot_ids'], [333])
        for counts in ((129, 0), (0, 257)):
            data = bytearray(ps2_payload())
            struct.pack_into('<2I', data, 0, *counts)
            with self.assertRaises(ValueError):
                mx.inspect_scenario(data)


class CardTests(unittest.TestCase):
    def test_data_and_spare_page_cards(self):
        for ecc in (False, True):
            card = Card(card_image(ecc))
            save = next(d for d in card.directory(card.root) if d.name == 'BISLPS-25345S00')
            self.assertEqual(card.files(save)['BISLPS-25345S00'], ps2_payload())

    def test_invalid_geometry_and_truncation(self):
        for offset, value in ((40, 0), (42, 0), (52, 0), (56, 999)):
            data = bytearray(card_image())
            struct.pack_into('<I', data, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                Card(data)
        for length in (1, 339, 512, len(card_image()) - 1):
            with self.assertRaises(ValueError):
                Card(card_image()[:length])

    def test_bad_chains(self):
        for value in (0x80000000, 0x800000FF, 0x7FFFFFFF):
            data = bytearray(card_image())
            struct.pack_into('<I', data, 2048, value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                Card(data).directory(0)

    def test_bad_directory_entries(self):
        for name in ('../escape', '..\\escape', 'C:escape', '.'):
            data = bytearray(card_image())
            data[5120 + 64:5120 + 512] = name.encode().ljust(448, b'\0')
            with self.subTest(name=name), self.assertRaises(ValueError):
                Card(data).directory(0)
        data = bytearray(card_image())
        struct.pack_into('<I', data, 4100, 999)
        with self.assertRaises(ValueError):
            Card(data).directory(0)

    def test_card_inspection_does_not_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'card.ps2'
            source.write_bytes(card_image(True))
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            result = mx.inspect_ps2(source)
            self.assertFalse(result['ecc_checked'])
            self.assertEqual(len(result['saves']), 1)
            self.assertFalse(result['saves'][0]['conversion_supported'])
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
            self.assertEqual(list(root.iterdir()), [source])


class PspTests(unittest.TestCase):
    def test_metadata_is_not_authentication(self):
        for mode in (1, 3, 5):
            result = mx.inspect_psp_save('ULJS000410000', bytes(0xD410), sfo(mode=mode))
            self.assertEqual(result['encryption_mode'], mode)
            self.assertEqual(result['integrity'], 'not-verified')
            self.assertNotIn('scenario', result)
            self.assertFalse(result['conversion_supported'])

    def test_plaintext(self):
        result = mx.inspect_psp_save('ULJS000410000', ps2_payload(), sfo(mode=0))
        self.assertEqual(result['scenario']['funds'], 8200)
        self.assertEqual(result['integrity'], 'not-verified')

    def test_bad_inputs(self):
        for name, data, meta in (
            ('OTHER00000000', bytes(0xD410), sfo()),
            ('ULJS000410000', bytes(0xD410), sfo('ULJS000419999')),
            ('ULJS000410000', bytes(0xD400), sfo()),
            ('ULJS000419999', bytes(0xD410), sfo('ULJS000419999')),
            ('ULJS000410000', bytes(0xD410), b'invalid'),
        ):
            with self.subTest(name=name, length=len(data)), self.assertRaises(ValueError):
                mx.inspect_psp_save(name, data, meta)

    def test_stale_plaintext_mac_rejected(self):
        metadata = bytearray(sfo())
        _, _, start, length, _ = mx.sfo_fields(metadata)['SAVEDATA_PARAMS']
        metadata[start:start + length] = bytes(length)
        with self.assertRaisesRegex(ValueError, 'stale file MAC'):
            mx.inspect_psp_save('ULJS000410000', ps2_payload(), metadata)

    def test_folder_and_cli_are_read_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            slot = root / 'ULJS000410000'
            slot.mkdir()
            (slot / 'DATA.BIN').write_bytes(bytes(0xD410))
            (slot / 'PARAM.SFO').write_bytes(sfo())
            before = {p.name: p.read_bytes() for p in slot.iterdir()}
            self.assertEqual(mx.inspect_psp(root), mx.inspect_psp(slot))
            with contextlib.redirect_stdout(io.StringIO()) as output:
                mx.main(['--psp', str(root)])
            self.assertIn('"conversion_supported": false', output.getvalue())
            self.assertEqual(before, {p.name: p.read_bytes() for p in slot.iterdir()})

    def test_cancel_and_changed_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            file = Path(temporary) / 'test'
            file.write_bytes(b'first')
            cancel = threading.Event()
            cancel.set()
            with self.assertRaises(Cancelled):
                mx._read_stable(file, 10, cancel)
            with self.assertRaisesRegex(ValueError, 'exceeds'):
                mx._read_stable(file, 4)
            with patch.object(Path, 'open', side_effect=[io.BytesIO(b'first'), io.BytesIO(b'other')]):
                with self.assertRaisesRegex(ValueError, 'changed'):
                    mx._read_stable(file, 10)


if __name__ == '__main__':
    unittest.main()
