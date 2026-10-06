"""Synthetic fixtures independently emitted by both games' native serializers.

No user save bytes are included. These verify record packing, not game support.
"""
import unittest

from retro_trans import mx_records as records


UNIT = bytes.fromhex(
    '710000000000889baec1d4e7e2000000a9cbfd105597aa2a5503000000000000'
    '0000000000000000000000000000000000000000000000000000000000000000')
PILOT = bytes.fromhex(
    '7100e2003502a6021703000053f98803c401db044c05bd052e069f0610078107'
    'f205182b3e516376899cafc20000000000000000000000000000000000000000'
    '0000000000000000000000000000000000000000000000000000000000000000')
UNIT_VALUES = {
    1: 113, 2: 226, 3: 1, 4: 0, 5: 1, 6: (0, 1, 0, 1, 0, 1),
    7: (1, 0, 1, 0, 1, 0, 1, 0, 1), 8: (136, 155, 174, 193, 212, 231),
    9: 9, 10: 10, 11: 11, 12: 12, 13: 13, 14: 14, 15: 15, 16: 0, 17: 1,
    18: 2, 19: (1, 0) * 8,
}
PILOT_VALUES = {
    1: 113, 2: 226, 3: 83, 4: 452, 5: 565, 6: 678, 7: 791, 8: 904,
    9: 249, 10: 0, 11: 1243, 12: 1356, 13: 1469, 14: 1582, 15: 1695,
    16: 1808, 17: 1921, 18: (242, 5, 24, 43, 62, 81),
    19: (99, 118, 137, 156, 175, 194),
}


class RecordTests(unittest.TestCase):
    def test_independent_native_fixtures(self):
        for kind, blob, values in (('unit', UNIT, UNIT_VALUES), ('pilot', PILOT, PILOT_VALUES)):
            with self.subTest(kind=kind):
                self.assertEqual(records.decode(blob, kind), values)
                self.assertEqual(records.encode(values, kind), blob)

    def test_padding_is_not_silently_rewritten(self):
        for kind, size in (('unit', 0x40), ('pilot', 0x60)):
            original = bytes((i * 71 + 17) % 256 for i in range(size))
            values = records.decode(original, kind)
            self.assertEqual(records.encode(values, kind, original=original), original)
            canonical = records.encode(values, kind)
            self.assertEqual(records.decode(canonical, kind), values)
            self.assertNotEqual(canonical, original)

    def test_adjacent_packed_flags_preserved(self):
        values = dict(UNIT_VALUES)
        values[5] = 0
        result = records.encode(values, 'unit', original=UNIT)
        self.assertEqual(bytes(a ^ b for a, b in zip(result, UNIT)),
                         bytes(25) + b'\x02' + bytes(38))
        values = dict(PILOT_VALUES)
        values[10] = 1
        result = records.encode(values, 'pilot', original=PILOT)
        self.assertEqual(bytes(a ^ b for a, b in zip(result, PILOT)),
                         bytes(44) + b'\x01' + bytes(51))

    def test_refuse_overflow_and_incomplete_properties(self):
        for kind, original in (('unit', UNIT_VALUES), ('pilot', PILOT_VALUES)):
            for value in (-1, 65536, True, '1'):
                values = dict(original)
                values[1] = value
                with self.subTest(kind=kind, value=value), self.assertRaises(ValueError):
                    records.encode(values, kind)
            for action in ('missing', 'extra', 'short-array'):
                values = dict(original)
                if action == 'missing':
                    del values[1]
                elif action == 'extra':
                    values[20] = 1
                else:
                    values[19] = ()
                with self.assertRaises(ValueError):
                    records.encode(values, kind)

    def test_wrong_lengths_and_kind(self):
        for kind, blob in (('unit', UNIT), ('pilot', PILOT)):
            for bad in (b'', blob[:-1], blob + b'\0'):
                with self.assertRaises(ValueError):
                    records.decode(bad, kind)
            with self.assertRaises(ValueError):
                records.encode(records.decode(blob, kind), kind, original=b'')
        with self.assertRaises(ValueError):
            records.decode(UNIT, 'system')

    def test_signed_native_field_preserves_wire_bits(self):
        values = dict(PILOT_VALUES)
        values[17] = 0xFFFF  # Both native loaders interpret these bits as -1.
        output = records.encode(values, 'pilot')
        self.assertEqual(output[0x1E:0x20], b'\xff\xff')
        self.assertEqual(records.decode(output, 'pilot')[17], 0xFFFF)


if __name__ == '__main__':
    unittest.main()
