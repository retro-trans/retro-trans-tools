"""Bounded EMS/PSU packaging, based on Ross Ridge's public-domain mymc format.

Directory entries are 512 bytes; each file's data is padded to 1024 bytes.
This writes an import container, never a memory card or ECC pages.
"""
from datetime import datetime
import struct

from .ps2_memcard import require

ENTRY = struct.Struct('<HHI8sII8sI28x448s')


def _name(name):
    require(isinstance(name, str) and 0 < len(name) < 32 and name not in ('.', '..')
            and all(c.isascii() and (c.isalnum() or c in '._-') for c in name), 'Unsafe PSU name')
    return name.encode('ascii')


def pack(folder, files):
    _name(folder)
    require(0 < len(files) <= 16, 'Invalid PSU file count')
    now = datetime.now()
    stamp = struct.pack('<xBBBBBH', now.second, now.minute, now.hour, now.day, now.month, now.year)

    def entry(name, length, directory):
        return ENTRY.pack(0x8427 if directory else 0x8497, 0, length, stamp, 0, 0, stamp, 0, name.encode('ascii'))
    parts = [entry(folder, len(files) + 2, True), entry('.', 0, True), entry('..', 0, True)]
    for name, data in sorted(files.items()):
        _name(name)
        require(0 < len(data) <= 4 * 1024 * 1024, 'Invalid PSU file size')
        parts.extend((entry(name, len(data), False), data, bytes((-len(data)) % 1024)))
    result = b''.join(parts)
    require(unpack(result) == (folder, files), 'PSU read-back verification failed')
    return result


def unpack(data):
    require(1536 <= len(data) <= 16 * 1024 * 1024, 'Unsupported PSU size')
    pos = 0

    def entry(directory):
        nonlocal pos
        require(pos + 512 <= len(data), 'Truncated PSU directory entry')
        values = ENTRY.unpack_from(data, pos)
        pos += 512
        require(values[0] & 0x8030 == (0x8020 if directory else 0x8010), 'Invalid PSU entry type')
        name = values[-1].split(b'\0', 1)[0].decode('ascii')
        return name, values[2]
    folder, count = entry(True)
    _name(folder)
    require(2 < count <= 18, 'Invalid PSU entry count')
    require(entry(True) == ('.', 0) and entry(True) == ('..', 0), 'Invalid PSU special entries')
    files = {}
    for _ in range(count - 2):
        name, length = entry(False)
        _name(name)
        padded = (length + 1023) // 1024 * 1024
        require(name not in files and 0 < length <= 4 * 1024 * 1024 and pos + padded <= len(data),
                'Invalid or truncated PSU file')
        files[name] = data[pos:pos + length]
        require(not any(data[pos + length:pos + padded]), 'Invalid PSU padding')
        pos += padded
    require(pos == len(data), 'Trailing PSU data')
    return folder, files
