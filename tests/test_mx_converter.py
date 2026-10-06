import hashlib
import os
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

from retro_trans import mx_converter as converter, mx_crypto as crypto, mx_saves as mx, ps2_psu
from retro_trans.core import Cancelled
from test_mx_saves import sfo


def payload(ps2=True):
    """Synthetic campaign with measured checkpoint coordinates, no real save bytes."""
    result = bytearray(0xD400)
    units, pilots = sorted(converter.UNIT_IDS), sorted(converter.PILOT_IDS)
    if ps2:
        pilots.append(170)  # The reviewed PS2 profile can include a duplicate.
    struct.pack_into('<2I', result, 0, len(units), len(pilots))
    struct.pack_into('<I', result, 8, (1 << len(units)) - 1)
    struct.pack_into('<I', result, 0x18, (1 << len(pilots)) - 1)
    for i, unit in enumerate(units):
        struct.pack_into('<H', result, 0x1400 + 64 * i, unit)
    for i, pilot in enumerate(pilots):
        struct.pack_into('<H', result, 0x3400 + 96 * i, pilot)
        struct.pack_into('<I', result, 0x3408 + 96 * i, 1234 + i)
    result[0xB804:0xB80A] = b'Hugo\0\0'
    struct.pack_into('<5I', result, 0xBF90, 3, 0, 1, 0, 0)
    result[0xBFA7] = 1
    struct.pack_into('<2I', result, 0xC800, 1, 0)
    struct.pack_into('<I', result, 0xC808, 1 << 21 if ps2 else (1 << 5 | 1 << 7 | 1 << 8))
    struct.pack_into('<3I', result, 0xC810, 2, 9, 31600 if ps2 else 8200)
    # Exercise arrays and native record bits without copying any game data.
    result[0xC823] = 9
    result[0xD015] = 7
    if ps2:
        struct.pack_into('<3I', result, 0xD3E0, mx.BALANCE_MAGIC, 1, 0)
        struct.pack_into('<2I', result, len(result) - 8, *mx.checksum_words(result))
    return bytes(result)


def inputs(root):
    ps2, psp = root / 'BISLPS-25345S01', root / 'ULJS000410000'
    ps2.mkdir()
    psp.mkdir()
    (ps2 / ps2.name).write_bytes(payload())
    (ps2 / 'icon.sys').write_bytes(b'PS2D' + bytes(960))
    (ps2 / 'mx1.ico').write_bytes(b'synthetic icon')
    (psp / 'DATA.BIN').write_bytes(payload(False))
    (psp / 'PARAM.SFO').write_bytes(sfo(psp.name, 0))
    (psp / 'ICON0.PNG').write_bytes(b'synthetic icon')
    return ps2, psp


class ConversionTests(unittest.TestCase):
    def test_actual_two_direction_transformation_and_balance(self):
        with patch.object(crypto, 'music_defaults', return_value=b'\x03' * 157):
            portable, details = converter.convert_payload(payload(), 'psp', b'owned-game')
        self.assertEqual(mx.inspect_scenario(portable)['funds'], 31600)
        self.assertEqual(portable[0xC0A4:0xC141], b'\x03' * 157)
        self.assertEqual(portable[0xD3E0:], bytes(32))
        self.assertEqual(details['destination']['pilot_count'], 14)
        self.assertEqual(portable[0xC823], 9)
        self.assertEqual(portable[0xD015], 7)
        for balance, expected in [('keep', 'psp'), ('psp', 'psp'), ('original', 'original')]:
            result, info = converter.convert_payload(payload(False), 'ps2', None, balance=balance)
            mx.validate_ps2(result)
            self.assertEqual(mx.inspect_balance(result)['mode'], expected)
            self.assertEqual(mx.inspect_scenario(result)['funds'], 8200)
            self.assertEqual(info['retained_favorites'], [5, 7, 8])
            self.assertEqual(struct.unpack_from('<I', result, 0xC808)[0], 0x1A0)
            self.assertEqual(result[0xC0A4:0xC141], bytes(157))
            self.assertEqual(result[0x3408:0x340C], struct.pack('<I', 1234))

    def test_reject_unreviewed_checkpoints_party_and_favorite(self):
        for offset, value in [(0xBF9C, 1), (0xBC00, 1), (0xBFA7, 2), (0x1400, 1), (0x28, 1), (0xC800, 0), (0xC804, 1)]:
            changed = bytearray(payload(False))
            changed[offset] = value
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                converter.convert_payload(changed, 'ps2', None)
        for mask in (0, 1 << 22, 1 << 31, (1 << 7) | (1 << 24)):
            changed = bytearray(payload(False))
            struct.pack_into('<I', changed, 0xC808, mask)
            with self.subTest(mask=mask), self.assertRaisesRegex(ValueError, 'Unknown favorite-series'):
                converter.convert_payload(changed, 'ps2', None)

    def test_difficulty_detection_in_both_directions(self):
        for mode in ('original', 'psp'):
            ps2 = mx.with_balance(payload(), mode)
            with patch.object(crypto, 'music_defaults', return_value=bytes(157)):
                portable, report = converter.convert_payload(ps2, 'psp', b'owned-game')
            self.assertEqual(report['source_balance'], mode)
            self.assertEqual(report['destination_balance'], 'psp')
            self.assertEqual(report['difficulty_changed'], mode == 'original')
            self.assertEqual(mx.inspect_scenario(portable)['funds'], 31600)
            restored, report = converter.convert_payload(payload(False), 'ps2', None, balance=mode)
            self.assertEqual(report['source_balance'], 'psp')
            self.assertEqual(report['destination_balance'], mode)
            self.assertEqual(report['difficulty_changed'], mode == 'original')
            self.assertEqual(mx.inspect_balance(restored)['mode'], mode)
            self.assertEqual(mx.inspect_scenario(restored)['funds'], 8200)

    def test_all_favorites_survive_both_directions_including_legacy_and_inherited_masks(self):
        for mask in (1 << 21, 0x1A0, 0x1A0 | (1 << 21), (1 << 22) - 1):
            source = bytearray(payload(False))
            struct.pack_into('<I', source, 0xC808, mask)
            ps2, first = converter.convert_payload(source, 'ps2', None)
            with patch.object(crypto, 'music_defaults', return_value=bytes(157)):
                psp, second = converter.convert_payload(ps2, 'psp', b'owned-game')
            for converted in (ps2, psp):
                self.assertEqual(struct.unpack_from('<I', converted, 0xC808)[0], mask)
                self.assertEqual(mx.inspect_scenario(converted)['funds'], 8200)
            self.assertEqual(first['source_favorites'], first['retained_favorites'])
            self.assertEqual(first['retained_favorites'], second['retained_favorites'])
            self.assertEqual(first['favorite_policy'], 'preserve-all-mapped-bits')

    def test_psu_layout_roundtrip_and_corruption(self):
        files = {'data.bin': b'x' * 1025, 'icon.sys': b'y' * 964}
        package = ps2_psu.pack('TEST-SAVE', files)
        self.assertEqual(struct.unpack_from('<I', package, 4)[0], 4)
        self.assertEqual(package[64:73], b'TEST-SAVE')
        self.assertEqual(package[1536 + 64:1536 + 72], b'data.bin')
        self.assertEqual(package[2048:3073], b'x' * 1025)
        self.assertEqual(ps2_psu.unpack(package), ('TEST-SAVE', files))
        for corrupt in (package[:-1], package + b'x', b'\0' * 2048):
            with self.assertRaises(ValueError):
                ps2_psu.unpack(corrupt)
        with self.assertRaises(ValueError):
            ps2_psu.pack('TEST', {'../bad': b'x'})

    def test_offline_build_backups_no_overwrite_source_changes_and_psu_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ps2, psp = inputs(root)
            output = root / 'result'
            options = dict(direction='psp-to-ps2', experimental=True)
            checked = converter.build(ps2, psp, output, **options)
            self.assertFalse(output.exists())
            built = converter.build(ps2, psp, output, write=True, expected_sources=checked['source_files'], **options)
            self.assertFalse(built['runtime_tested'])
            self.assertEqual((ps2 / ps2.name).read_bytes(), payload())
            self.assertEqual((psp / 'DATA.BIN').read_bytes(), payload(False))
            name, files = ps2_psu.unpack((output / 'psp-to-ps2' / (ps2.name + '.psu')).read_bytes())
            self.assertEqual(name, ps2.name)
            self.assertEqual(mx.inspect_scenario(files[name])['funds'], 8200)
            self.assertEqual(mx.inspect_scenario(files[name])['favorite_series_bits'], 0x1A0)
            self.assertEqual(built['destination_profiles']['ps2'], converter.PS2_PROFILE)
            self.assertTrue((output / 'original-backups/psp/ULJS000410000/DATA.BIN').is_file())
            self.assertTrue((output / 'psp-to-ps2.zip').is_file())
            with self.assertRaisesRegex(ValueError, 'NEW'):
                converter.build(ps2, psp, output, **options)
            (psp / 'ICON0.PNG').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'changed since checking'):
                converter.build(ps2, psp, root / 'changed', expected_sources=checked['source_files'], **options)

    def test_cancellation_disk_full_change_during_stage_and_boundaries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ps2, psp = inputs(root)
            output = root / 'result'
            options = dict(direction='psp-to-ps2', experimental=True, write=True)
            with patch.object(converter.shutil, 'disk_usage') as usage:
                usage.return_value.free = 0
                with self.assertRaisesRegex(ValueError, 'disk space'):
                    converter.build(ps2, psp, output, **options)
            self.assertFalse(output.exists())
            cancel = threading.Event()
            def stop(message, fraction):
                if fraction == .45:
                    cancel.set()
            with self.assertRaises(Cancelled):
                converter.build(ps2, psp, output, cancel=cancel, progress=stop, **options)
            self.assertFalse(output.exists())
            self.assertFalse(list(root.glob('.mx-conversion-*')))
            def change(message, fraction):
                if fraction == .45:
                    (psp / 'ICON0.PNG').write_bytes(b'changed during build')
            with self.assertRaisesRegex(ValueError, 'changed while converting'):
                converter.build(ps2, psp, output, progress=change, **options)
            self.assertFalse(output.exists())
            with self.assertRaisesRegex(ValueError, 'inside a source'):
                converter.build(ps2, psp, psp / 'result', **options)
            with self.assertRaisesRegex(ValueError, 'experimental'):
                converter.build(ps2, psp, output)

    def test_plaintext_psp_output_metadata_and_progression_not_from_template(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ps2, psp = inputs(root)
            with patch.object(crypto, 'read_boot', return_value=b'owned-game'), \
                    patch.object(crypto, 'music_defaults', return_value=bytes(157)):
                converter.build(ps2, psp, root / 'result', experimental=True, boot_path='owned.iso', write=True)
            slot = root / 'result/ps2-to-psp' / psp.name
            data, metadata = (slot / 'DATA.BIN').read_bytes(), (slot / 'PARAM.SFO').read_bytes()
            info = mx.inspect_psp_save(psp.name, data, metadata)
            self.assertEqual(info['encryption_mode'], 0)
            self.assertEqual(info['scenario']['funds'], 31600)
            self.assertEqual(info['scenario']['pilot_count'], 14)
            self.assertEqual(len(data), 0xD400)


@unittest.skipUnless(os.name == 'nt', 'Windows CNG cryptography')
class CryptoTests(unittest.TestCase):
    def test_nist_aes_cbc_and_cmac_vectors(self):
        # NIST SP 800-38A F.2.1 and SP 800-38B examples / RFC 4493.
        key = bytes.fromhex('2b7e151628aed2a6abf7158809cf4f3c')
        block = bytes.fromhex('6bc1bee22e409f96e93d7e117393172a')
        with crypto.AES(key) as cipher:
            encoded = cipher.crypt(block, iv=bytes(range(16)))
            self.assertEqual(encoded.hex(), '7649abac8119b246cee98e9b12e9197d')
            self.assertEqual(cipher.crypt(encoded, True, bytes(range(16))), block)
        self.assertEqual(crypto.cmac(key, b'').hex(), 'bb1d6929e95937287fa37d129b756746')
        self.assertEqual(crypto.cmac(key, block).hex(), '070a16b46b4d4144f79bdd9dd04a287c')
        forty = bytes.fromhex('6bc1bee22e409f96e93d7e117393172aae2d8a571e03ac9c9eb76fac45af8e5130c81c46a35ce411')
        self.assertEqual(crypto.cmac(key, forty).hex(), 'dfa66747de9ae63030ca32611497c827')

    def test_authenticated_mode3_and_corrupt_data_or_metadata(self):
        keys = object.__new__(crypto.Keys)
        keys.game = bytes(range(16))
        keys.seeds = {i: bytes([i]) * 16 for i in (3, 12, 14, 87)}  # synthetic keys, not game material
        header = b'example-header!!'
        base = crypto.xor(crypto.aes(keys.seeds[14], crypto.xor(crypto.xor(header, keys.game), crypto.X4), True), crypto.X3)
        counters = b''.join(base[:12] + struct.pack('<I', i) for i in range(1, 0xD400 // 16 + 1))
        encrypted = header + crypto.xor(payload(False), crypto.aes(keys.seeds[87], counters, True))
        metadata = bytearray(sfo())
        fields = crypto.sfo_fields(metadata)
        record = fields['SAVEDATA_FILE_LIST'][2]
        file_mac = crypto.aes(keys.seeds[12], crypto.xor(crypto.xor(crypto.cmac(keys.seeds[12], encrypted), crypto.MAC_MASK), keys.game))
        metadata[record + 13:record + 29] = file_mac
        params = fields['SAVEDATA_PARAMS'][2]
        def padded():
            return bytes(metadata).ljust((len(metadata) + 15) // 16 * 16, b'\0')
        metadata[params + 0x70:params + 0x80] = crypto.xor(crypto.cmac(keys.seeds[12], padded()), crypto.MAC_MASK)
        metadata[params + 0x10:params + 0x20] = crypto.cmac(keys.seeds[3], padded())
        self.assertEqual(keys.decode('ULJS000410000', encrypted, metadata)[0], payload(False))
        with self.assertRaisesRegex(ValueError, 'authentication failed'):
            keys.decode('ULJS000410000', encrypted[:-1] + bytes([encrypted[-1] ^ 1]), metadata)
        metadata[-2] ^= 1
        with self.assertRaisesRegex(ValueError, 'metadata final hash'):
            keys.decode('ULJS000410000', encrypted, metadata)


if __name__ == '__main__':
    unittest.main()
