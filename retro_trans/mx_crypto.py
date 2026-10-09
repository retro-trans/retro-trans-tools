"""MX Portable mode-3 savedata reads using Windows CNG.

No game or KIRK key material is shipped. The experimental profile reads it
from the user's hash-identified BOOT.BIN and installed PPSSPP executable.
Plaintext outputs intentionally target PPSSPP, not a physical PSP.
"""
import ctypes
import hashlib
import hmac
import os
from pathlib import Path
import struct
import sys

from .core import check_cancel
from .mx_saves import _read_stable, inspect_psp_save
from .ps2_memcard import require
from .z3_saves import sfo_fields

BOOT_HASH = '31b4cae68ef11693cc32c3b50aa471e8bfc65e2f68ea32ca99d43ed5e6a5ee17'
ENGLISH_BOOT_HASH = 'f8b70ca3914817704b39d69ecd543b054f12707ec1de49a1cce0ef90c3461093'
PPSSPP_HASH = '27d3edbb06dc623dab60877d3e3a975aef4034c7d4fac464e92fd4998864d2ec'
# Public format masks, not encryption keys.
X3 = bytes.fromhex('36a53eacc5269ea383d9ec256c484872')
X4 = bytes.fromhex('d8c0b0f33e6b7685fdfb4d7d451e9203')
MAC_MASK = bytes.fromhex('faaa50ec2fde5493ad14b2cea53005df')


def xor(a, b):
    require(len(a) == len(b), 'Invalid crypto block lengths')
    return bytes(x ^ y for x, y in zip(a, b))


class AES:
    """Small bounded AES-CBC interface to the Windows built-in provider."""
    def __init__(self, key):
        if sys.platform == 'darwin':
            require(len(key) == 16, 'Invalid savedata key length')
            self.apple_key = bytearray(key)
            self.dll = ctypes.CDLL('/usr/lib/system/libcommonCrypto.dylib')
            self.dll.CCCrypt.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
            self.dll.CCCrypt.restype = ctypes.c_int32
            return
        require(os.name == 'nt', 'Encrypted PSP saves require Windows')
        require(len(key) == 16, 'Invalid savedata key length')
        self.dll = ctypes.WinDLL('bcrypt')
        ptr, uint, status = ctypes.c_void_p, ctypes.c_ulong, ctypes.c_long
        signatures = {
            'BCryptOpenAlgorithmProvider': [ctypes.POINTER(ptr), ctypes.c_wchar_p, ctypes.c_wchar_p, uint],
            'BCryptSetProperty': [ptr, ctypes.c_wchar_p, ptr, uint, uint],
            'BCryptGenerateSymmetricKey': [ptr, ctypes.POINTER(ptr), ptr, uint, ptr, uint, uint],
            'BCryptEncrypt': [ptr, ptr, uint, ptr, ptr, uint, ptr, uint, ctypes.POINTER(uint), uint],
            'BCryptDecrypt': [ptr, ptr, uint, ptr, ptr, uint, ptr, uint, ctypes.POINTER(uint), uint],
            'BCryptDestroyKey': [ptr], 'BCryptCloseAlgorithmProvider': [ptr, uint],
        }
        for name, args in signatures.items():
            function = getattr(self.dll, name)
            function.argtypes, function.restype = args, status
        self.algorithm, self.handle = ptr(), ptr()
        try:
            self._ok(self.dll.BCryptOpenAlgorithmProvider(ctypes.byref(self.algorithm), 'AES', None, 0))
            mode = ctypes.create_unicode_buffer('ChainingModeCBC')
            self._ok(self.dll.BCryptSetProperty(self.algorithm, 'ChainingMode', mode, ctypes.sizeof(mode), 0))
            secret = ctypes.create_string_buffer(key)
            self._ok(self.dll.BCryptGenerateSymmetricKey(self.algorithm, ctypes.byref(self.handle), None, 0,
                                                       secret, len(key), 0))
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _ok(status):
        require(status >= 0, 'Windows savedata cryptography failed')

    def crypt(self, data, decrypt=False, iv=bytes(16)):
        require(len(data) > 0 and len(data) % 16 == 0 and len(iv) == 16, 'Invalid AES data length')
        if hasattr(self, 'apple_key'):
            require(len(self.apple_key) == 16, 'Savedata cipher is closed')
            output = ctypes.create_string_buffer(len(data))
            written = ctypes.c_size_t()
            # kCCAlgorithmAES=0, CBC/no padding=0, encrypt=0/decrypt=1.
            result = self.dll.CCCrypt(int(decrypt), 0, 0, bytes(self.apple_key), 16,
                iv, data, len(data), output, len(data), ctypes.byref(written))
            require(result == 0 and written.value == len(data), 'Mac savedata cryptography failed')
            return output.raw
        source = ctypes.create_string_buffer(data)
        output = ctypes.create_string_buffer(len(data))
        vector = ctypes.create_string_buffer(iv)
        written = ctypes.c_ulong()
        function = self.dll.BCryptDecrypt if decrypt else self.dll.BCryptEncrypt
        self._ok(function(self.handle, source, len(data), None, vector, 16, output, len(data),
                          ctypes.byref(written), 0))
        require(written.value == len(data), 'Incomplete AES result')
        return output.raw

    def close(self):
        if hasattr(self, 'apple_key'):
            self.apple_key[:] = bytes(len(self.apple_key))
            self.apple_key.clear()
            return
        if self.handle:
            self.dll.BCryptDestroyKey(self.handle)
            self.handle = ctypes.c_void_p()
        if self.algorithm:
            self.dll.BCryptCloseAlgorithmProvider(self.algorithm, 0)
            self.algorithm = ctypes.c_void_p()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def aes(key, data, decrypt=False):
    with AES(key) as cipher:
        return cipher.crypt(data, decrypt)


def cmac(key, data):
    def double(block):
        number = int.from_bytes(block, 'big')
        return (((number << 1) & ((1 << 128) - 1)) ^ (0x87 if number >> 127 else 0)).to_bytes(16, 'big')
    with AES(key) as cipher:
        subkey = double(cipher.crypt(bytes(16)))
        if data and len(data) % 16 == 0:
            last, prefix = xor(data[-16:], subkey), data[:-16]
        else:
            prefix = data[:len(data) // 16 * 16]
            tail = data[len(prefix):] + b'\x80'
            last = xor(tail.ljust(16, b'\0'), double(subkey))
        return cipher.crypt(prefix + last)[-16:]


def read_boot(path, cancel=None):
    """Read the exact reviewed ELF, directly or from a plain ISO9660 image."""
    path = Path(path)
    if path.suffix.lower() != '.iso':
        data = _read_stable(path, 16 * 1024 * 1024, cancel)
    else:
        before = path.stat()
        require(path.is_file() and not path.is_symlink(), 'Choose a plain PSP ISO or BOOT.BIN')
        with path.open('rb') as stream:
            def read_at(offset, length):
                check_cancel(cancel)
                require(0 <= offset <= before.st_size and 0 < length <= 16 * 1024 * 1024
                        and offset + length <= before.st_size, 'Invalid PSP ISO extent')
                stream.seek(offset)
                result = stream.read(length)
                require(len(result) == length, 'Truncated PSP ISO')
                return result
            pvd = read_at(16 * 2048, 2048)
            require(pvd[:7] == b'\x01CD001\x01' and struct.unpack_from('<H', pvd, 128)[0] == 2048,
                    'Expected a plain ISO9660 PSP image; extract compressed images first')
            entry = pvd[156:190]
            for index, component in enumerate(('PSP_GAME', 'SYSDIR', 'BOOT.BIN')):
                require(entry[25] & 2, 'Invalid PSP ISO directory')
                sector, size = struct.unpack_from('<I', entry, 2)[0], struct.unpack_from('<I', entry, 10)[0]
                directory = read_at(sector * 2048, size)
                matches, pos = [], 0
                while pos < len(directory):
                    length = directory[pos]
                    if not length:
                        pos = (pos // 2048 + 1) * 2048
                        continue
                    require(length >= 34 and pos + length <= len(directory), 'Invalid ISO directory entry')
                    record = directory[pos:pos + length]
                    name = record[33:33 + record[32]].split(b';', 1)[0]
                    if name == component.encode('ascii'):
                        matches.append(record)
                    pos += length
                require(len(matches) == 1, 'Cannot find a unique PSP BOOT.BIN in this ISO')
                entry = matches[0]
            require(not entry[25] & (2 | 0x80), 'Unsupported BOOT.BIN extent')
            data = read_at(struct.unpack_from('<I', entry, 2)[0] * 2048,
                           struct.unpack_from('<I', entry, 10)[0])
        after = path.stat()
        require((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
                'PSP ISO changed during reading')
    require(hashlib.sha256(data).hexdigest() in (BOOT_HASH, ENGLISH_BOOT_HASH),
            'Unrecognized PSP executable. This MX test profile needs the original MX Portable BOOT.BIN.')
    return data


def music_defaults(boot):
    """Read the reviewed game's 157 assignments, without shipping its table."""
    require(hashlib.sha256(boot).hexdigest() in (BOOT_HASH, ENGLISH_BOOT_HASH), 'Unrecognized PSP executable')
    registers, values = {0: 0}, {}
    for offset in range(0x5476C + 0x60, 0x54A50 + 0x60, 4):
        word = struct.unpack_from('<I', boot, offset)[0]
        opcode, source, target, immediate = word >> 26, (word >> 21) & 31, (word >> 16) & 31, word & 0xFFFF
        if opcode == 9 and source == 0:  # addiu reg, zero, constant
            registers[target] = immediate
        elif opcode == 40 and source == 4 and 0x1C4 <= immediate <= 0x260:
            require(target in registers, 'Unknown native music initialization')
            values[immediate - 0x1C4] = registers[target] & 255
        else:
            require(word == 0x03E00008, 'Unexpected native music initialization')  # jr ra
    require(set(values) == set(range(157)), 'Incomplete native music defaults')
    return bytes(values[i] for i in range(157))


class Keys:
    def __init__(self, boot_path, ppsspp_path, cancel=None):
        boot = read_boot(boot_path, cancel)
        emulator = _read_stable(ppsspp_path, 32 * 1024 * 1024, cancel)
        require(hashlib.sha256(emulator).hexdigest() == PPSSPP_HASH,
                'This encrypted-save profile needs the official PPSSPP 1.20.4 Windows 64-bit executable.')
        self.game = boot[0x276BC0:0x276BD0]
        self.seeds = {i: emulator[0xF1E930 + i * 16:0xF1E940 + i * 16] for i in (3, 12, 14, 87)}

    def decode(self, folder, encrypted, metadata):
        info = inspect_psp_save(folder, encrypted, metadata)
        if info['encryption_mode'] == 0:
            return encrypted, 'plaintext (no cryptographic authentication)'
        require(info['encryption_mode'] == 3, 'Only MX mode-3 encrypted saves are supported')
        fields = sfo_fields(metadata)
        start, length = fields['SAVEDATA_FILE_LIST'][2:4]
        record = next(metadata[i:i + 32] for i in range(start, start + length, 32)
                      if metadata[i:i + 13].split(b'\0', 1)[0] == b'DATA.BIN')
        actual = aes(self.seeds[12], xor(xor(cmac(self.seeds[12], encrypted), MAC_MASK), self.game))
        require(hmac.compare_digest(actual, record[13:29]), 'PSP DATA.BIN authentication failed')
        # These two portable SFO hashes bind the entire metadata, including the
        # fuse-dependent hash. We do not claim to recreate a physical PSP fuse.
        params = fields['SAVEDATA_PARAMS'][2]
        checked = bytearray(metadata)
        expected = bytes(checked[params + 0x10:params + 0x20])
        checked[params + 0x10:params + 0x20] = bytes(16)
        padded = bytes(checked).ljust((len(checked) + 15) // 16 * 16, b'\0')
        require(hmac.compare_digest(cmac(self.seeds[3], padded), expected), 'PSP metadata final hash failed')
        expected = bytes(checked[params + 0x70:params + 0x80])
        checked[params + 0x70:params + 0x80] = bytes(16)
        padded = bytes(checked).ljust((len(checked) + 15) // 16 * 16, b'\0')
        require(hmac.compare_digest(xor(cmac(self.seeds[12], padded), MAC_MASK), expected),
                'PSP metadata secondary hash failed')
        base = xor(aes(self.seeds[14], xor(xor(encrypted[:16], self.game), X4), True), X3)
        counters = b''.join(base[:12] + struct.pack('<I', i) for i in range(1, len(encrypted) // 16))
        plaintext = xor(encrypted[16:], aes(self.seeds[87], counters, True))
        return plaintext, 'keyed file MAC and both portable SFO hashes verified'


def plaintext_metadata(metadata):
    output = bytearray(metadata)
    fields = sfo_fields(metadata)
    start, length = fields['SAVEDATA_PARAMS'][2:4]
    output[start:start + length] = bytes(length)
    start, length = fields['SAVEDATA_FILE_LIST'][2:4]
    for i in range(start, start + length, 32):
        if output[i:i + 13].split(b'\0', 1)[0] == b'DATA.BIN':
            output[i + 13:i + 29] = bytes(16)
    return bytes(output)
