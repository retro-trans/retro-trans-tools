"""Native MX scenario record packing, not a cross-platform save converter.

Property numbers match the native getter/setter interfaces. Values here are
unsigned wire bits (both native loaders sign-extend pilot property 17).
Unproven field meanings are deliberately not given gameplay names. IDs, references, campaign
compatibility, containers and destination acceptance are separate concerns.
"""

# (first bit, width, count). A count above one represents an array.
UNIT_FIELDS = {
    1: (0, 16, 1), 2: (0x0C * 8, 8, 1),
    3: (0x14 * 8, 1, 1), 4: (0x14 * 8 + 31, 1, 1),
    5: (0x18 * 8 + 9, 1, 1), 6: (0x14 * 8 + 1, 1, 6),
    7: (0x18 * 8, 1, 9), 8: (6 * 8, 8, 6),
    9: (0x10 * 8, 4, 1), 10: (0x10 * 8 + 4, 4, 1),
    11: (0x10 * 8 + 8, 4, 1), 12: (0x10 * 8 + 12, 4, 1),
    13: (0x10 * 8 + 16, 4, 1), 14: (0x14 * 8 + 7, 4, 1),
    15: (0x10 * 8 + 20, 4, 1), 16: (0x10 * 8 + 24, 4, 1),
    17: (0x10 * 8 + 28, 4, 1), 18: (0x14 * 8 + 11, 4, 1),
    19: (0x14 * 8 + 15, 1, 16),
}
PILOT_FIELDS = {
    1: (0, 16, 1), 2: (2 * 8, 16, 1), 3: (0x0C * 8, 8, 1),
    4: (0x10 * 8, 16, 1), 5: (4 * 8, 16, 1), 6: (6 * 8, 16, 1),
    7: (8 * 8, 32, 1), 8: (0x0E * 8, 16, 1), 9: (0x0D * 8, 8, 1),
    10: (0x2C * 8, 1, 1), 11: (0x12 * 8, 16, 1),
    12: (0x14 * 8, 16, 1), 13: (0x16 * 8, 16, 1),
    14: (0x18 * 8, 16, 1), 15: (0x1A * 8, 16, 1),
    16: (0x1C * 8, 16, 1), 17: (0x1E * 8, 16, 1),
    18: (0x20 * 8, 8, 6), 19: (0x26 * 8, 8, 6),
}


def layout(kind):
    if kind == 'unit':
        return UNIT_FIELDS, 0x40
    if kind == 'pilot':
        return PILOT_FIELDS, 0x60
    raise ValueError('Unknown MX record kind')


def decode(data, kind):
    fields, size = layout(kind)
    if len(data) != size:
        raise ValueError('Unexpected MX record length')
    packed, result = int.from_bytes(data, 'little'), {}
    for prop, (offset, width, count) in fields.items():
        values = tuple((packed >> (offset + i * width)) & ((1 << width) - 1)
                       for i in range(count))
        result[prop] = values[0] if count == 1 else values
    return result


def encode(properties, kind, *, original=None):
    """Pack all known properties; optionally preserve the same record's padding.

    `original` must be that record's own bytes, never a destination game's party
    template. No unspecified property is silently supplied from a template.
    """
    fields, size = layout(kind)
    if set(properties) != set(fields):
        raise ValueError('Missing or unknown MX record properties')
    if original is not None and len(original) != size:
        raise ValueError('Unexpected original MX record length')
    packed = int.from_bytes(original, 'little') if original is not None else 0
    for prop, (offset, width, count) in fields.items():
        values = (properties[prop],) if count == 1 else properties[prop]
        if not isinstance(values, (tuple, list)) or len(values) != count:
            raise ValueError('Incorrect MX property array length')
        for index, value in enumerate(values):
            if type(value) is not int or not 0 <= value < (1 << width):
                raise ValueError('MX property value exceeds its field width')
            position = offset + index * width
            packed = (packed & ~(((1 << width) - 1) << position)) | (value << position)
    return packed.to_bytes(size, 'little')
