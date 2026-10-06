"""Experimental, bounded MX manual-save conversion; never installs live saves.

The first profile covers the observed Hugo/Cerberus early intermission only.
Native serializers establish the shared wire layout; in-game continuation is
still an acceptance test, not a promise made by this writer.
"""
import argparse
import json
from pathlib import Path
import shutil
import struct
import tempfile

from .core import check_cancel, report as progress_report
from . import mx_records, mx_saves as mx, mx_crypto, ps2_psu
from .ps2_memcard import Card, require
from .z3_saves import put_files, make_zip, update_sfo, sfo_fields

GUIDE = Path(__file__).parent / 'resources' / 'MX-SAVE-CONVERSION.txt'
PROFILE = 'mx-hugo-early-intermission-experimental-v2'
PS2_PROFILE = 'English PSP-stage port 0.1.18 (user-selected; three-favorite selector)'
DIRECTIONS = ('ps2-to-psp', 'psp-to-ps2')
UNIT_IDS = {79, 80, 82, 85, 86, 87, 89, 90, 143}
PILOT_IDS = {168, 170, 172, 173, 174, 175, 176, 177, 179, 182, 332, 333, 337}
# Reviewed PSP pointer table at VA 0x28a2f0 and PS2's 40-byte title rows
# at VA 0x4771f0 have the same 22 series IDs, in bit-index order.
SERIES = ('Machine Robo: Revenge of Chronos', 'Neon Genesis Evangelion', 'The End of Evangelion',
          'GEAR Fighter Dendoh', 'Martian Successor Nadesico', 'Nadesico: Prince of Darkness',
          'Metal Armor Dragonar', 'Mobile Suit Zeta Gundam', 'Mobile Suit Gundam ZZ', "Char's Counterattack",
          'Mobile Fighter G Gundam', 'Mazinger Z', 'Great Mazinger', 'Getter Robo', 'Getter Robo G',
          'UFO Robo Grendizer', 'Mazinger Movie Series', 'Hades Project Zeorymer', 'Battle Commander Daimos',
          'Brave Raideen', 'RahXephon', 'Banpresto Originals')
FLAGS_HASH = 'd2710a3a6574fc3d509a62191d8933226f0046f7ffcd83fd8de6866684c5f73e'
HISTORY_HASH = '66da6d6a1c123ba365613d4c827dab173d2e609d18e00babcbcfa915439205aa'
WARNINGS = [
    'Experimental: this output still needs game testing. A previous PS2 → PSP candidate was reported working '
    'in PPSSPP; PS2 loading and a full save/reload cycle remain unverified.',
    'Only this early Hugo/Cerberus intermission is accepted. Stock PS2 campaigns and battle saves are unsupported.',
    'Only the selected manual slot is converted. System data, gallery/unlocks and battle suspend are not migrated; '
    'their interaction with converted progression still needs game testing. Use a separate emulator profile/card.',
    'Party order, duplicates, funds and stored progression are preserved without balance scaling. '
    'Option toggles reset to the test-profile defaults; PSP music choices reset to native defaults or are omitted on PS2.',
    'PSP output is plaintext for PPSSPP only. Physical PSP installation is unsupported.',
]


def read_folder(path, required, cancel=None):
    path = Path(path)
    require(path.is_dir() and not path.is_symlink(), 'Choose an extracted manual save folder')
    entries = sorted(path.iterdir())
    require(len(entries) <= 20 and all(p.is_file() and not p.is_symlink() for p in entries),
            'Unexpected contents in the selected save folder')
    files = {p.name: mx._read_stable(p, 4 * 1024 * 1024, cancel) for p in entries}
    require(set(required).issubset(files), 'The selected save is missing required files: ' + ', '.join(required))
    require(sum(map(len, files.values())) <= 16 * 1024 * 1024, 'Save folder exceeds supported size')
    return files


def load_ps2(path, slot=None, cancel=None):
    path = Path(path)
    if path.is_file():
        raw = mx._read_stable(path, 128 * 1024 * 1024, cancel)
        if path.suffix.lower() == '.psu':
            name, files = ps2_psu.unpack(raw)
            require(slot in (None, '', name), 'Selected slot does not match the PSU')
        else:
            card = Card(raw)
            entries = [e for e in card.directory(card.root) if e.is_directory and
                       mx.PS2_DIRECTORY.fullmatch(e.name) and e.name != 'BISLPS-25345']
            if slot:
                entries = [e for e in entries if e.name == slot]
            require(len(entries) == 1, 'Select one PS2 manual slot in MX options. Available: ' +
                    ', '.join(e.name for e in card.directory(card.root) if mx.PS2_DIRECTORY.fullmatch(e.name)))
            name, files = entries[0].name, card.files(entries[0])
        backup = {'ps2/source' + path.suffix.lower(): raw}
    else:
        require(not path.is_symlink(), 'Linked save roots are unsupported')
        if not mx.PS2_DIRECTORY.fullmatch(path.name):
            folders = [p for p in path.iterdir() if p.is_dir() and mx.PS2_DIRECTORY.fullmatch(p.name)
                       and p.name != 'BISLPS-25345' and (not slot or p.name == slot)]
            require(len(folders) == 1, 'Choose one extracted PS2 manual slot or select a slot in MX options')
            path = folders[0]
        require(slot in (None, '', path.name), 'Selected slot does not match the PS2 folder')
        name = path.name
        files = read_folder(path, (name, 'icon.sys', 'mx1.ico'), cancel)
        backup = {'ps2/' + name + '/' + n: b for n, b in files.items()}
    require(mx.PS2_DIRECTORY.fullmatch(name) and name != 'BISLPS-25345', 'Choose an MX manual save, not system data')
    require({name, 'icon.sys', 'mx1.ico'}.issubset(files), 'PS2 manual save payload or icons are missing')
    mx.inspect_ps2_save(name, files[name])
    require(mx.inspect_balance(files[name])['status'] == 'valid',
            'This test profile needs a fresh PS2 English-port save with a valid balance marker; old/stock saves are unsupported')
    require(files['icon.sys'][:4] == b'PS2D', 'Invalid PS2 icon metadata')
    return name, files, backup


def load_psp(path, cancel=None):
    path = Path(path)
    require(path.is_dir() and not path.is_symlink(), 'Choose the PPSSPP manual slot folder')
    if not mx.PSP_DIRECTORY.fullmatch(path.name):
        folders = [p for p in path.iterdir() if mx.PSP_DIRECTORY.fullmatch(p.name) and not p.name.endswith('9999')]
        require(len(folders) == 1, 'Choose one PPSSPP manual slot folder (for example ULJS000410000)')
        path = folders[0]
    require(not path.name.endswith('9999'), 'System saves are outside this experimental converter')
    files = read_folder(path, ('DATA.BIN', 'PARAM.SFO', 'ICON0.PNG'), cancel)
    mx.inspect_psp_save(path.name, files['DATA.BIN'], files['PARAM.SFO'])
    return path.name, files, {'psp/' + path.name + '/' + n: b for n, b in files.items()}


def checkpoint(payload):
    info = mx.inspect_scenario(payload)
    require(struct.unpack_from('<2I', payload, 0xC800) == (1, 0),
            'Unreviewed protagonist/robot selection for this early Hugo/Cerberus test profile')
    require(info['campaign_words'] == [3, 0, 1, 0, 0] and info['completed_maps'] == 2
            and info['campaign_flags_sha256'] == FLAGS_HASH and info['location_history_sha256'] == HISTORY_HASH,
            'This save is outside the reviewed early intermission. Later stages, routes and battle saves are not yet supported.')
    require(info['unit_count'] == 9 and set(info['unit_ids']) == UNIT_IDS
            and info['pilot_count'] in (13, 14) and set(info['pilot_ids']) == PILOT_IDS,
            'Unreviewed party or protagonist for this MX test profile')
    unit_mask = int.from_bytes(payload[8:0x18], 'little')
    pilot_mask = int.from_bytes(payload[0x18:0x38], 'little')
    require(unit_mask == (1 << info['unit_count']) - 1 and pilot_mask == (1 << info['pilot_count']) - 1,
            'Unreviewed party allocation; conversion would risk losing slot references')
    return info


def convert_payload(source, target, boot, balance='keep'):
    require(target in ('ps2', 'psp'), 'Unknown MX destination')
    require(balance in ('keep', 'original', 'psp'), 'Unknown balance choice')
    info = checkpoint(source)
    source_balance = 'psp'
    if target == 'psp':
        mx.validate_ps2(source)
        saved_balance = mx.inspect_balance(source)
        require(saved_balance['status'] == 'valid', 'Unknown PS2 balance extension')
        source_balance = saved_balance['mode']
    favorites = [i for i in range(32) if info['favorite_series_bits'] & (1 << i)]
    require(favorites and all(i <= 21 for i in favorites), 'Unknown favorite-series identity')
    if target == 'ps2':
        require(not any(source[0x28:0x38]), 'PSP pilot slots exceed the PS2 loader capacity')
    result = bytearray(mx.SIZES['scenario'])
    # Only regions consumed by the reviewed native manual-save loaders. Start
    # from zero so PSP's uninitialized padding does not become PS2 state.
    for start, end in ((0, 0x38), (0x400, 0xE00), (0xB804, 0xB9C8),
                       (0xBC00, 0xC0A4), (0xC800, 0xCF9C), (0xD004, 0xD0A4)):
        result[start:end] = source[start:end]
    for kind, base, size, count in (('unit', 0x1400, 0x40, 128), ('pilot', 0x3400, 0x60, 256)):
        for i in range(count):
            offset = base + i * size
            result[offset:offset + size] = mx_records.encode(mx_records.decode(source[offset:offset + size], kind), kind)
    # Native strcpy-based fields. Some default full-width robot names occupy
    # all 32 bytes and terminate in the following slot. Keep that shared native
    # representation intact, including the weapon-name field at 0x1a4..0x1c3.
    strings = [(0xB804 + 16 * i, 16) for i in range(8)] + [(0xB9A4, 32)]
    strings += [(0xB894 + 32 * i, 64) for i in range(8)]
    for start, size in strings:
        field = source[start:start + size]
        require(b'\0' in field, 'Unterminated MX player name')
    if target == 'psp':
        result[0xC0A4:0xC141] = mx_crypto.music_defaults(boot)
        struct.pack_into('<I', result, 0xD000, 0x3EC43)
        effective = ('PSP difficulty (unchanged)' if source_balance == 'psp' else
                     'PSP difficulty (was PS2 Original; existing funds are unchanged)')
    else:
        # The native mask is at player block +0x1008, i.e. full file 0xc808.
        # It was copied above in full. The new selector needs no new field;
        # neither truncate three picks nor cap inherited favorite bits.
        struct.pack_into('<I', result, 0xD000, 0x11B)
        effective = 'psp' if balance == 'keep' else balance
        struct.pack_into('<3I', result, 0xD3E0, mx.BALANCE_MAGIC, 1, int(effective == 'psp'))
        struct.pack_into('<2I', result, len(result) - 8, *mx.checksum_words(result))
        mx.validate_ps2(result)
    after = checkpoint(result)
    require(after == info, 'Converted progression verification failed')
    destination_balance = 'psp' if target == 'psp' else effective
    return bytes(result), {'source': info, 'destination': after, 'effective_balance': effective,
                           'source_balance': source_balance, 'destination_balance': destination_balance,
                           'difficulty_changed': source_balance != destination_balance,
                           'source_favorites': favorites, 'retained_favorites': favorites,
                           'favorite_policy': 'preserve-all-mapped-bits',
                           'retained_series': [SERIES[i] for i in favorites]}


def build(ps2_path, psp_path, output, *, direction='ps2-to-psp', ps2_slot=None, boot_path=None,
          ppsspp_path=None, balance='keep', experimental=False, write=False,
          expected_sources=None, cancel=None, progress=None):
    check_cancel(cancel)
    require(experimental, 'Enable the experimental MX profile after reading its limitations')
    require(direction in DIRECTIONS + ('both',), 'Unknown MX conversion direction')
    output = Path(output)
    require(not output.exists() and not output.is_symlink(), 'Output must be a NEW folder')
    output = output.resolve()
    roots = [Path(ps2_path).resolve(), Path(psp_path).resolve()]
    require(all(root != output and (root if root.is_dir() else root.parent) not in output.parents for root in roots),
            'Output cannot be inside a source save or memory-card folder')
    progress_report(progress, 'Reading and verifying MX manual saves…', .05)
    ps2_name, ps2, ps2_backup = load_ps2(ps2_path, ps2_slot, cancel)
    psp_name, psp, psp_backup = load_psp(psp_path, cancel)
    backups = dict(ps2_backup, **psp_backup)
    identities = {name: mx.identity(data) for name, data in backups.items()}
    require(expected_sources is None or identities == expected_sources,
            'Saves changed since checking. Check saves again before converting.')
    boot = mx_crypto.read_boot(boot_path, cancel) if boot_path else None
    mode = mx.inspect_psp_save(psp_name, psp['DATA.BIN'], psp['PARAM.SFO'])['encryption_mode']
    if mode:
        require(boot_path and ppsspp_path, 'Select your PSP ISO/BOOT.BIN and PPSSPP executable in MX options')
        keys = mx_crypto.Keys(boot_path, ppsspp_path, cancel)
        decoded, authentication = keys.decode(psp_name, psp['DATA.BIN'], psp['PARAM.SFO'])
    else:
        decoded, authentication = psp['DATA.BIN'], 'plaintext: no cryptographic authentication'
    checkpoint(ps2[ps2_name])
    checkpoint(decoded)
    outputs, mappings = {}, []
    for name in DIRECTIONS:
        if direction not in (name, 'both'):
            continue
        check_cancel(cancel)
        target = name.rsplit('-', 1)[-1]
        source = ps2[ps2_name] if target == 'psp' else decoded
        require(target != 'psp' or boot is not None, 'Select your PSP ISO/BOOT.BIN to initialize native PSP music choices')
        converted, details = convert_payload(source, target, boot, balance)
        if target == 'psp':
            files = {n: psp[n] for n in ('ICON0.PNG', 'PIC1.PNG') if n in psp}
            metadata = mx_crypto.plaintext_metadata(psp['PARAM.SFO'])
            text = 'MX conversion TEST - load and verify in game. Funds: {}; maps: {}; turns: {}.'.format(
                details['source']['funds'], details['source']['completed_maps'], details['source']['turns'])
            fields = sfo_fields(metadata)
            changes = {key: value for key, value in (('SAVEDATA_TITLE', 'MX conversion test'),
                       ('SAVEDATA_DETAIL', text)) if key in fields}
            metadata = update_sfo(metadata, changes)
            files.update({'DATA.BIN': converted, 'PARAM.SFO': metadata})
            mx.inspect_psp_save(psp_name, converted, metadata)
            package = {psp_name + '/' + n: b for n, b in files.items()}
        else:
            files = {ps2_name: converted, 'icon.sys': ps2['icon.sys'], 'mx1.ico': ps2['mx1.ico']}
            package = {ps2_name + '/' + n: b for n, b in files.items()}
            package[ps2_name + '.psu'] = ps2_psu.pack(ps2_name, files)
        outputs[name] = package
        mappings.append(dict(direction=name, source_folder=ps2_name if target == 'psp' else psp_name,
                             destination_folder=psp_name if target == 'psp' else ps2_name, **details))
    audit = dict(schema=1, profile=PROFILE, status='experimental-candidate' if write else 'checked',
                 runtime_tested=False, installed=False, source_files=identities, mappings=mappings,
                 warnings=WARNINGS, psp_authentication=authentication, originals_unchanged=True,
                 destination_profiles={'ps2': PS2_PROFILE,
                                       'psp': 'MX Portable English 0.4.9 / PPSSPP'},
                 options={'direction': direction, 'favorite_policy': 'preserve-all-mapped-bits',
                          'balance': balance, 'ps2_slot': ps2_slot})
    if not write:
        return audit
    check_cancel(cancel)
    guide = GUIDE.read_bytes()
    output.parent.mkdir(parents=True, exist_ok=True)
    required = sum(map(len, backups.values())) + 2 * sum(len(b) for p in outputs.values() for b in p.values()) + 16 * 1024 * 1024
    require(shutil.disk_usage(output.parent).free >= required, 'Not enough disk space for MX saves and backups')
    with tempfile.TemporaryDirectory(prefix='.mx-conversion-', dir=str(output.parent)) as temporary:
        stage = Path(temporary)
        progress_report(progress, 'Writing new saves and original backups…', .45)
        put_files(stage / 'original-backups', backups, cancel)
        audit['packages'] = {}
        for name, files in outputs.items():
            package = dict(files, **{'README-FIRST.txt': guide})
            put_files(stage / name, package, cancel)
            audit['packages'][name] = dict(zip=make_zip(stage / (name + '.zip'), package, cancel),
                                          files={n: mx.identity(b) for n, b in files.items()})
        check_cancel(cancel)
        current = dict(load_ps2(ps2_path, ps2_slot, cancel)[2], **load_psp(psp_path, cancel)[2])
        require(current == backups, 'Source saves changed while converting; close both emulators and check again')
        put_files(stage, {'README-FIRST.txt': guide, 'CONVERSION_AUDIT.json':
                         (json.dumps(audit, ensure_ascii=False, indent=2) + '\n').encode('utf-8')}, cancel)
        check_cancel(cancel)
        output.mkdir()
        try:
            for item in stage.iterdir():
                item.rename(output / item.name)
        except BaseException:
            shutil.rmtree(output)
            raise
    progress_report(progress, 'MX test saves created and verified.', 1)
    return audit


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ps2', required=True)
    parser.add_argument('--psp', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--ps2-slot')
    parser.add_argument('--psp-game', dest='boot_path')
    parser.add_argument('--ppsspp', dest='ppsspp_path')
    parser.add_argument('--direction', choices=DIRECTIONS + ('both',), default='ps2-to-psp')
    parser.add_argument('--balance', choices=('keep', 'original', 'psp'), default='keep')
    parser.add_argument('--experimental', action='store_true')
    parser.add_argument('--write', action='store_true')
    args = vars(parser.parse_args(argv))
    try:
        result = build(args.pop('ps2'), args.pop('psp'), args.pop('output'), **args)
    except (OSError, ValueError) as error:
        parser.exit(1, 'MX conversion failed: {}\n'.format(error))
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
