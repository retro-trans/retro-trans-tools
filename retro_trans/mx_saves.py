"""Read-only SRW MX inspection and confirmed PS2 integrity primitives.

Experimental cross-platform writing lives in mx_converter; this module remains
a read-only inspector. Metadata inspection is not PSP authentication, and a PS2
additive checksum does not identify a game build.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

from .core import check_cancel
from .ps2_memcard import Card, require
from .z3_saves import sfo_fields, sfo_text

SIZES = {'scenario': 0xD400, 'system': 0x21C00}
CHECKSUM_BASE = 0x78945612
BALANCE_MAGIC = 0x4442584D
PS2_DIRECTORY = re.compile(r'BISLPS-25345(?:S[0-9]{2})?\Z')
PSP_DIRECTORY = re.compile(r'ULJS00041[0-9]{4}\Z')


def identity(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def checksum_words(payload):
    require(len(payload) in SIZES.values(), 'Unsupported MX PS2 payload length')
    words = struct.unpack('<{}I'.format(len(payload) // 4), payload)
    return ((CHECKSUM_BASE + sum(words[-256:-2])) & 0xFFFFFFFF,
            (CHECKSUM_BASE + sum(words[:-256])) & 0xFFFFFFFF)


def validate_ps2(payload):
    expected = checksum_words(payload)
    actual = struct.unpack_from('<2I', payload, len(payload) - 8)
    require(actual == expected, 'MX PS2 save checksum mismatch')
    return expected


def inspect_balance(payload):
    validate_ps2(payload)
    marker = struct.unpack_from('<3I', payload, len(payload) - 32)
    if marker == (0, 0, 0):
        return {'status': 'absent', 'mode': 'original'}
    if marker[:2] == (BALANCE_MAGIC, 1) and marker[2] in (0, 1):
        return {'status': 'valid', 'mode': ('original', 'psp')[marker[2]]}
    return {'status': 'unsupported', 'mode': None, 'raw_words': list(marker)}


def with_balance(payload, mode):
    """Edit only a known extension on an already identified PS2-port payload.

    This byte primitive neither migrates campaigns nor proves build compatibility.
    The caller must establish the destination profile before using its result.
    """
    require(mode in ('original', 'psp'), 'Unknown game balance')
    require(inspect_balance(payload)['status'] != 'unsupported',
            'Unknown MX balance extension; refusing to overwrite it')
    output = bytearray(payload)
    struct.pack_into('<3I', output, len(output) - 32, BALANCE_MAGIC, 1, int(mode == 'psp'))
    struct.pack_into('<2I', output, len(output) - 8, *checksum_words(output))
    validate_ps2(output)
    return bytes(output)


def inspect_scenario(payload):
    """Measured fields in decoded scenario data; does not authenticate it.

    Native serializers: PS2 0x30d880/0x335650; PSP 0x180b50/0x573e8.
    Campaign words are intentionally unnamed until route semantics are verified.
    """
    require(len(payload) == SIZES['scenario'], 'Expected an MX scenario payload')
    units, pilots = struct.unpack_from('<2I', payload)
    require(units <= 128 and pilots <= 256, 'Invalid MX party counts')
    return {
        'unit_count': units, 'pilot_count': pilots,
        'unit_ids': [struct.unpack_from('<H', payload, 0x1400 + i * 0x40)[0]
                     for i in range(units)],
        'pilot_ids': [struct.unpack_from('<H', payload, 0x3400 + i * 0x60)[0]
                      for i in range(pilots)],
        'funds': struct.unpack_from('<I', payload, 0xC818)[0],
        'completed_maps': struct.unpack_from('<I', payload, 0xC810)[0],
        'turns': struct.unpack_from('<I', payload, 0xC814)[0],
        'favorite_series_bits': struct.unpack_from('<I', payload, 0xC808)[0],
        'campaign_words': list(struct.unpack_from('<5I', payload, 0xBF90)),
        'campaign_flags_sha256': hashlib.sha256(payload[0xBC00:0xBF90]).hexdigest(),
        'location_history_sha256': hashlib.sha256(payload[0xBFA4:0xC0A4]).hexdigest(),
    }


def _read_stable(path, limit, cancel=None):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'Missing or linked input file: ' + str(path))

    def read():
        parts, size = [], 0
        with path.open('rb') as stream:
            while True:
                check_cancel(cancel)
                chunk = stream.read(min(1024 * 1024, limit + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                require(size <= limit, 'Input exceeds supported size: ' + path.name)
                parts.append(chunk)
        return b''.join(parts)

    data = read()
    require(read() == data, 'Save changed while reading; close the emulator and retry')
    return data


def inspect_ps2_save(name, payload):
    require(PS2_DIRECTORY.fullmatch(name), 'Not an MX PS2 save directory')
    kind = 'system' if name == 'BISLPS-25345' else 'scenario'
    require(len(payload) == SIZES[kind], 'MX PS2 directory and payload size disagree')
    validate_ps2(payload)
    result = dict(directory=name, platform='ps2', kind=kind, **identity(payload))
    result.update(checksums_valid=True, balance=inspect_balance(payload),
                  game_build='unverified', conversion_supported=False)
    if kind == 'scenario':
        result['scenario'] = inspect_scenario(payload)
    return result


def inspect_ps2(path, cancel=None):
    path = Path(path)
    if path.is_file():
        snapshot = _read_stable(path, 128 * 1024 * 1024, cancel)
        card = Card(snapshot)
        saves = []
        for directory in card.directory(card.root):
            check_cancel(cancel)
            if directory.is_directory and PS2_DIRECTORY.fullmatch(directory.name):
                files = card.files(directory)
                require(directory.name in files, 'MX PS2 save payload is missing')
                saves.append(inspect_ps2_save(directory.name, files[directory.name]))
        require(saves, 'No MX saves found in this memory card')
        return {'container': 'ps2-card', 'source': identity(snapshot),
                'ecc_checked': False, 'saves': saves}
    require(path.is_dir() and not path.is_symlink(), 'Choose an extracted PS2 save folder or .ps2 card')
    folders = [path] if PS2_DIRECTORY.fullmatch(path.name) else sorted(
        p for p in path.iterdir() if PS2_DIRECTORY.fullmatch(p.name))
    require(folders, 'No extracted MX PS2 saves found')
    saves = []
    for folder in folders:
        require(folder.is_dir() and not folder.is_symlink(), 'Invalid extracted PS2 save directory')
        payload = _read_stable(folder / folder.name, SIZES['system'], cancel)
        saves.append(inspect_ps2_save(folder.name, payload))
    return {'container': 'extracted-ps2', 'saves': saves}


def inspect_psp_save(name, payload, metadata):
    require(PSP_DIRECTORY.fullmatch(name), 'Not an MX PSP save directory')
    fields, text = sfo_fields(metadata), sfo_text(metadata)
    require(text.get('SAVEDATA_DIRECTORY') == name, 'PSP metadata belongs to another save directory')
    require('SAVEDATA_PARAMS' in fields and 'SAVEDATA_FILE_LIST' in fields,
            'PSP integrity metadata is missing')
    _, typ, start, length, _ = fields['SAVEDATA_PARAMS']
    require(typ == 4 and length == 128, 'Unexpected PSP integrity metadata layout')
    params = metadata[start:start + length]
    require(params[0] in (0, 1, 0x21, 0x41), 'Unsupported PSP encryption mode')
    mode = {0: 0, 1: 1, 0x21: 3, 0x41: 5}[params[0]]
    require(mode != 0 or not any(params), 'Ambiguous PSP plaintext metadata')
    kind = 'system' if name.endswith('9999') else 'scenario'
    require(len(payload) == SIZES[kind] + (16 if mode else 0),
            'MX PSP directory, encryption mode and payload size disagree')
    _, typ, start, length, _ = fields['SAVEDATA_FILE_LIST']
    require(typ == 4 and length > 0 and length % 32 == 0, 'Invalid PSP file-list layout')
    entries = [metadata[i:i + 32] for i in range(start, start + length, 32)]
    matching = [entry for entry in entries if entry[:13].split(b'\0', 1)[0] == b'DATA.BIN']
    require(len(matching) == 1, 'PSP file list must reference DATA.BIN exactly once')
    result = dict(directory=name, platform='psp', kind=kind, **identity(payload))
    result.update(metadata=identity(metadata), display_text=text, encryption_mode=mode,
                  integrity='not-verified', game_build='unverified', conversion_supported=False)
    # No encrypted payload parsing without authenticated decryption. A readable
    # PARAM.SFO, matching sizes or nonzero MAC are not integrity verification.
    if mode == 0:
        require(not any(matching[0][13:29]), 'Plaintext PSP metadata contains a stale file MAC')
        if kind == 'scenario':
            result['scenario'] = inspect_scenario(payload)
    return result


def inspect_psp(path, cancel=None):
    path = Path(path)
    require(path.is_dir() and not path.is_symlink(), 'Choose the PPSSPP SAVEDATA folder or an MX slot')
    folders = [path] if PSP_DIRECTORY.fullmatch(path.name) else sorted(
        p for p in path.iterdir() if PSP_DIRECTORY.fullmatch(p.name))
    require(folders, 'No MX PSP saves found')
    saves = []
    for folder in folders:
        require(folder.is_dir() and not folder.is_symlink(), 'Invalid PSP save directory')
        metadata = _read_stable(folder / 'PARAM.SFO', 64 * 1024, cancel)
        payload = _read_stable(folder / 'DATA.BIN', SIZES['system'] + 16, cancel)
        require(_read_stable(folder / 'PARAM.SFO', 64 * 1024, cancel) == metadata,
                'PSP metadata changed while reading; close the emulator and retry')
        saves.append(inspect_psp_save(folder.name, payload, metadata))
    return {'container': 'psp-savedata', 'saves': saves}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Inspect MX saves without modifying them. For experimental writing use retro_trans.mx_converter.')
    parser.add_argument('--ps2', type=Path, help='PS2 memory card or extracted MX saves')
    parser.add_argument('--psp', type=Path, help='PPSSPP SAVEDATA folder or MX slot')
    args = parser.parse_args(argv)
    if not args.ps2 and not args.psp:
        parser.error('Select --ps2 and/or --psp')
    try:
        result = {'conversion_supported': False, 'read_only': True}
        if args.ps2:
            result['ps2'] = inspect_ps2(args.ps2)
        if args.psp:
            result['psp'] = inspect_psp(args.psp)
    except (OSError, ValueError) as error:
        parser.exit(1, 'MX inspection failed: {}\n'.format(error))
    print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == '__main__':
    main()
