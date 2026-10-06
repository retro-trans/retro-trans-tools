"""Compare the MX record codec with locally owned native game routines.

Development only: requires Unicorn 2.1.4, never bundled with the application.
Game getters/setters and PSP value filters are mocked; this verifies the wire
layout at their boundaries, not ID semantics, gameplay, or conversion support.
No game bytes, keys, icons or real saves are written by this script.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from retro_trans import mx_records

HASHES = {
    'ps2': 'beaf6cbd5d025b06dc358e757a4fbaa95414f9d35e2fdfabe2dc63a3184b5eee',
    'psp': '31b4cae68ef11693cc32c3b50aa471e8bfc65e2f68ea32ca99d43ed5e6a5ee17',
}
PS2_FAVORITES_HASH = '533760d188e7af1333021e2ac50ec1b8b702b86e2c2576fea44dc7f76070ebff'
MANAGER, BUFFER, STOP, STACK = 0x900000, 0x940000, 0x980000, 0xA00000


def property_value(kind, prop, index, element, seed):
    # Independent of the Python codec's bit layout; native serializers pack
    # these values, which are then checked against the Python codec and loaders.
    value = (seed * 0x19660D + prop * 113 + index * 67 + element * 19) & 0xFFFFFFFF
    if kind == 'unit':
        if prop in (3, 4, 5, 6, 7, 19):
            mask = 1
        elif prop in (2, 8):
            mask = 0xFF
        else:
            mask = 0xFFFF if prop == 1 else 15
    elif prop == 10:
        mask = 1
    elif prop in (3, 9, 18, 19):
        mask = 0xFF
    else:
        mask = 0xFFFFFFFF if prop == 7 else 0xFFFF
    return value & mask


class Native:
    def __init__(self, platform, path):
        import unicorn
        from unicorn import mips_const
        self.uc, self.r = unicorn, mips_const
        self.platform, self.data = platform, path.read_bytes()
        self.sha256 = hashlib.sha256(self.data).hexdigest()
        if self.sha256 != HASHES[platform] and not (platform == 'ps2' and self.sha256 == PS2_FAVORITES_HASH):
            raise ValueError('Unreviewed {} executable; routine addresses are build-specific'.format(platform))

    def machine(self):
        uc, r = self.uc, self.r
        mode = uc.UC_MODE_MIPS64 if self.platform == 'ps2' else uc.UC_MODE_MIPS32
        vm = uc.Uc(uc.UC_ARCH_MIPS, mode | uc.UC_MODE_LITTLE_ENDIAN)
        model = r.UC_CPU_MIPS64_MIPS64R2_GENERIC if self.platform == 'ps2' else r.UC_CPU_MIPS32_24KF
        vm.ctl_set_cpu_model(model)
        vm.mem_map(0, 0xB00000)
        offset = struct.unpack_from('<I', self.data, 28)[0]
        stride, count = struct.unpack_from('<HH', self.data, 42)
        for i in range(count):
            kind, source, address, _, size, _, _, _ = struct.unpack_from('<8I', self.data, offset + i * stride)
            if kind == 1:
                vm.mem_write(address, self.data[source:source + size])
        vm.reg_write(r.UC_MIPS_REG_A0, MANAGER)
        vm.reg_write(r.UC_MIPS_REG_A1, BUFFER)
        vm.reg_write(r.UC_MIPS_REG_SP, STACK)
        vm.reg_write(r.UC_MIPS_REG_RA, STOP)
        return vm

    def arguments(self, vm, kind):
        r = self.r
        if self.platform == 'ps2':
            return vm.reg_read(r.UC_MIPS_REG_A2), vm.reg_read(r.UC_MIPS_REG_A3)
        bank, stride = (0x6F00, 0x3C) if kind == 'unit' else (0xE700, 0x64)
        relative = vm.reg_read(r.UC_MIPS_REG_A0) - MANAGER - bank
        if relative < 0 or relative % stride:
            raise ValueError('Unexpected PSP record bank')
        return relative // stride, vm.reg_read(r.UC_MIPS_REG_A2)

    def return_value(self, vm, value):
        vm.reg_write(self.r.UC_MIPS_REG_V0, value)
        vm.reg_write(self.r.UC_MIPS_REG_PC, vm.reg_read(self.r.UC_MIPS_REG_RA))

    def run(self, vm, entry, hook):
        vm.hook_add(self.uc.UC_HOOK_CODE, hook)
        vm.emu_start(entry, STOP, count=2000000)
        if vm.reg_read(self.r.UC_MIPS_REG_PC) != STOP:
            raise ValueError('Native routine did not return within the instruction limit')

    def serialize(self, seed):
        vm, r = self.machine(), self.r
        vm.mem_write(MANAGER + 0x20020, struct.pack('<2I', 3, 5))
        vm.mem_write(MANAGER + 0x2FC, bytes((i * 19 + seed) % 256 for i in range(0x2000)))
        getters = ({0x30C4C0: 'unit', 0x30C818: 'pilot'} if self.platform == 'ps2'
                   else {0x17D148: 'unit', 0x17C67C: 'pilot'})

        def hook(machine, pc, size, user):
            if pc in getters:
                kind, prop = getters[pc], machine.reg_read(r.UC_MIPS_REG_A1)
                index, pointer = self.arguments(machine, kind)
                element = struct.unpack('<I', machine.mem_read(pointer, 4))[0] if pointer else 0
                self.return_value(machine, property_value(kind, prop, index, element, seed))
            elif self.platform == 'psp' and pc in (0x17FF74, 0x180374):
                # Bypass the native property filters: their gameplay semantics
                # are outside this layout test and still need separate mapping.
                self.return_value(machine, machine.reg_read(r.UC_MIPS_REG_A3))

        self.run(vm, 0x30D880 if self.platform == 'ps2' else 0x180B50, hook)
        return bytes(vm.mem_read(BUFFER, 0xB800))

    def deserialize(self, data):
        vm, r, collected = self.machine(), self.r, {}
        vm.mem_write(BUFFER, bytes(data))
        setters = ({0x30C630: 'unit', 0x30C978: 'pilot'} if self.platform == 'ps2'
                   else {0x17D198: 'unit', 0x17C6CC: 'pilot'})

        def hook(machine, pc, size, user):
            if pc not in setters:
                return
            kind, prop = setters[pc], machine.reg_read(r.UC_MIPS_REG_A1)
            index, pointer = self.arguments(machine, kind)
            count = mx_records.layout(kind)[0][prop][2]
            element = struct.unpack('<I', machine.mem_read(pointer, 4))[0] if count > 1 else 0
            value = struct.unpack('<I', machine.mem_read(pointer + (4 if count > 1 else 0), 4))[0]
            key = (kind, prop, index, element)
            if key in collected:
                raise ValueError('Native loader set a property twice')
            collected[key] = value
            self.return_value(machine, 0)

        self.run(vm, 0x30EEC0 if self.platform == 'ps2' else 0x182A20, hook)
        return collected, bytes(vm.mem_read(MANAGER + 0x1FF00, 0x60))


def verify(ps2_path, psp_path):
    ps2, psp = Native('ps2', ps2_path), Native('psp', psp_path)
    record_checks, property_checks, signed = 0, 0, set()
    for seed in range(16):
        data = ps2.serialize(seed)
        if data != psp.serialize(seed):
            raise ValueError('Native serializer layouts disagree')
        for kind, offset, stride, count in (('unit', 0x1400, 0x40, 128), ('pilot', 0x3400, 0x60, 256)):
            for index in range(count):
                raw = data[offset + index * stride:offset + (index + 1) * stride]
                properties = mx_records.decode(raw, kind)
                for prop, (_, width, length) in mx_records.layout(kind)[0].items():
                    expected = tuple(property_value(kind, prop, index, i, seed) for i in range(length))
                    if properties[prop] != (expected[0] if length == 1 else expected):
                        raise ValueError('Python decoding disagrees with a native serializer')
                if mx_records.encode(properties, kind) != raw:
                    raise ValueError('Python encoding disagrees with a native serializer')
                record_checks += 1
        left, _ = ps2.deserialize(data)
        right, _ = psp.deserialize(data)
        if left != right or len(left) != 14080:
            raise ValueError('Native record loaders disagree')
        for key, value in left.items():
            width = mx_records.layout(key[0])[0][key[1]][1]
            if property_value(*key, seed) != value & ((1 << width) - 1):
                raise ValueError('Native loader changed a stored property')
            if value >> 31 and width < 32:
                signed.add((key[0], key[1]))
        property_checks += len(left)

    # The PS2 loader copies only the lower half of the serialized pilot bitset;
    # the PSP loader copies all eight words. Make this limitation reproducible.
    data = bytearray(ps2.serialize(0))
    data[0x28:0x38] = b'\xA5' * 16
    _, ps2_bits = ps2.deserialize(data)
    _, psp_bits = psp.deserialize(data)
    if ps2_bits[0x50:0x60] != bytes(16) or psp_bits[0x50:0x60] != b'\xA5' * 16:
        raise ValueError('Pilot bitset behavior differs from the reviewed routines')
    return {
        'passed': True, 'seeds': 16, 'record_checks': record_checks,
        'loader_property_checks': property_checks,
        'native_signed_properties': sorted(signed),
        'pilot_bitset_upper_half_loads_on_ps2': False,
        'pilot_bitset_upper_half_loads_on_psp': True,
        'executables': {'ps2': ps2.sha256, 'psp': psp.sha256},
        'scope': 'Scenario record packing; getters/setters and PSP property filters mocked',
        'conversion_supported': False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ps2-elf', type=Path, required=True)
    parser.add_argument('--psp-elf', type=Path, required=True)
    parser.add_argument('--dependencies', type=Path, help='Optional local directory containing Unicorn')
    parser.add_argument('--report', type=Path, help='Write a new JSON report; refuses existing files')
    args = parser.parse_args()
    if args.dependencies:
        sys.path.insert(0, str(args.dependencies.resolve()))
    result = verify(args.ps2_elf, args.psp_elf)
    text = json.dumps(result, indent=2) + '\n'
    if args.report:
        with args.report.open('x', encoding='utf-8') as stream:
            stream.write(text)
    print(text)


if __name__ == '__main__':
    main()
