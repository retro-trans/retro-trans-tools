"""Verify favorite identities and native save-field preservation from owned ELFs.

Requires the development-only Unicorn package. No game data is bundled or
emitted. This tests the field and title tables, not a complete in-game reload.
"""
import argparse
import itertools
import json
from pathlib import Path
import struct
import sys
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.verify_mx_native_layout import Native, MANAGER, BUFFER, PS2_FAVORITES_HASH
from retro_trans.mx_converter import SERIES


def verify(ps2_path, psp_path):
    ps2, psp = Native('ps2', ps2_path), Native('psp', psp_path)
    if ps2.sha256 != PS2_FAVORITES_HASH:
        raise ValueError('This verification requires the reviewed PS2 0.1.18 executable')
    left, right = ps2.machine(), psp.machine()
    title_matches = []
    # PS2 abbreviates these two labels; both refer to the corresponding PSP title.
    abbreviated = {2: 'THE END OF EVA', 16: '\u5287\u5834\u7248 \u30de\u30b8\u30f3\u30ac\u30fc'}
    for i in range(len(SERIES)):
        a = bytes(left.mem_read(0x4771F0 + 40 * i, 40)).split(b'\0')[0].decode('cp932')
        ptr = struct.unpack('<I', right.mem_read(0x28A2F0 + 4 * i, 4))[0]
        b = bytes(right.mem_read(ptr, 100)).split(b'\0')[0].decode('cp932')
        a, b = unicodedata.normalize('NFKC', a), unicodedata.normalize('NFKC', b)
        if a != b and (i not in abbreviated or a != abbreviated[i]):
            raise ValueError('Favorite title identity differs at index {}'.format(i))
        title_matches.append(dict(series_id=i, name=SERIES[i], ps2_abbreviated=i in abbreviated))
    selectable = [0, 1, 3, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15, 17, 18, 19, 20, 21]
    masks = [1 << i for i in range(22)]
    masks += [sum(1 << i for i in triple) for triple in itertools.combinations(selectable, 3)]
    masks += [0x1A0 | (1 << 21), (1 << 22) - 1]
    for native, vm, member, source, destination, load, save in (
            (ps2, left, 0x5E8, ps2.r.UC_MIPS_REG_S3, ps2.r.UC_MIPS_REG_S2, 0x335CA8, 0x335808),
            (psp, right, 0x688, psp.r.UC_MIPS_REG_S5, psp.r.UC_MIPS_REG_S5, 0x57CB0, 0x57668)):
        r = native.r
        for mask in masks:
            vm.mem_write(BUFFER + 0xC808, struct.pack('<I', mask))
            vm.reg_write(source, BUFFER + 0xB800)
            vm.reg_write(r.UC_MIPS_REG_S4, MANAGER)
            vm.emu_start(load, load + 8, count=2)
            if struct.unpack('<I', vm.mem_read(MANAGER + member, 4))[0] != mask:
                raise ValueError('Native favorite load truncated bits')
            vm.mem_write(BUFFER + 0xC808, bytes(4))
            vm.reg_write(destination, BUFFER + 0xB800)
            vm.emu_start(save, save + 8, count=2)
            if struct.unpack('<I', vm.mem_read(BUFFER + 0xC808, 4))[0] != mask:
                raise ValueError('Native favorite save truncated bits')
    return dict(passed=True, series=title_matches, field_offset='0xc808',
                masks_per_platform=len(masks), native_field_round_trips=2 * len(masks),
                executables={'ps2': ps2.sha256, 'psp': psp.sha256},
                scope='Native favorite field loads/stores and title identity; not in-game acceptance')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ps2-elf', type=Path, required=True)
    parser.add_argument('--psp-elf', type=Path, required=True)
    parser.add_argument('--dependencies', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.dependencies:
        sys.path.insert(0, str(args.dependencies.resolve()))
    result = verify(args.ps2_elf, args.psp_elf)
    with args.report.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print('Passed: {} series identities, {} native field round trips.'.format(
        len(result['series']), result['native_field_round_trips']))


if __name__ == '__main__':
    main()
