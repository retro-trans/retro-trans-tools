"""Read-only PS2 memory-card reader. No writer or ECC validation.

Allocation/directory format reference: Ross Ridge's public-domain mymc,
https://github.com/ps2dev/mymc (ps2mc.py and ps2mc_dir.py).
Only data pages are exposed; spare/ECC bytes are deliberately not interpreted.
"""
from dataclasses import dataclass
import struct


def require(condition, message):
    if not condition:
        raise ValueError(message)


@dataclass(frozen=True)
class Entry:
    name: str
    mode: int
    length: int
    cluster: int

    @property
    def is_directory(self):
        return bool(self.mode & 0x20)


class Card:
    """Parse a bounded, immutable snapshot; never open a live card for writing."""

    def __init__(self, data):
        self.data = bytes(data)
        require(340 <= len(data) <= 128 * 1024 * 1024, 'Unsupported memory-card length')
        fields = struct.unpack_from('<28s12sHHHH6I8x128s128sbbxx', self.data)
        require(fields[0] == b'Sony PS2 Memory Card Format ', 'Not a PS2 memory card')
        require(fields[1].split(b'\0', 1)[0] in (b'1.2.0.0', b'1.1.0.0'),
                'Unsupported PS2 memory-card format version')
        self.page_size, self.pages_per_cluster = fields[2:4]
        self.clusters, self.alloc_start, self.alloc_end, self.root = fields[6:10]
        require(self.page_size == 512 and self.pages_per_cluster == 2,
                'Unsupported PS2 memory-card geometry')
        require(0 < self.alloc_start < self.clusters and
                0 < self.alloc_end <= self.clusters - self.alloc_start,
                'Invalid memory-card allocation area')
        require(0 <= self.root < self.alloc_end, 'Invalid memory-card root')
        self.indirect = struct.unpack('<32I', fields[12])
        pages = self.clusters * self.pages_per_cluster
        if len(data) == pages * self.page_size:
            self.raw_page_size = self.page_size
        elif len(data) == pages * (self.page_size + 16):
            self.raw_page_size = self.page_size + 16
        else:
            raise ValueError('Memory-card size does not match its geometry')
        self.cluster_size = self.page_size * self.pages_per_cluster
        self.entries_per_cluster = self.cluster_size // 4

    def cluster(self, number):
        require(0 <= number < self.clusters, 'Cluster outside memory card')
        first = number * self.pages_per_cluster
        return b''.join(self.data[(first + i) * self.raw_page_size:
                                 (first + i) * self.raw_page_size + self.page_size]
                        for i in range(self.pages_per_cluster))

    def fat(self, number):
        require(0 <= number < self.alloc_end, 'Invalid allocation index')
        fat_number, within = divmod(number, self.entries_per_cluster)
        indirect_number, indirect_within = divmod(fat_number, self.entries_per_cluster)
        require(indirect_number < len(self.indirect), 'Allocation table is too large')
        indirect = self.cluster(self.indirect[indirect_number])
        fat_cluster = struct.unpack_from('<I', indirect, indirect_within * 4)[0]
        return struct.unpack_from('<I', self.cluster(fat_cluster), within * 4)[0]

    def chain(self, first):
        seen = set()
        current = first
        while current != 0xFFFFFFFF:
            require(0 <= current < self.alloc_end, 'File chain outside allocation area')
            require(current not in seen, 'Cyclic memory-card allocation chain')
            seen.add(current)
            next_cluster = self.fat(current)
            require(next_cluster & 0x80000000, 'Unallocated cluster in file chain')
            yield self.cluster(self.alloc_start + current)
            current = next_cluster if next_cluster == 0xFFFFFFFF else next_cluster & 0x7FFFFFFF

    def contents(self, first, length):
        require(0 <= length <= self.alloc_end * self.cluster_size, 'Invalid file length')
        data = b''.join(self.chain(first))
        require(len(data) >= length, 'File chain shorter than declared length')
        return data[:length]

    def directory(self, first, count=None):
        data = b''.join(self.chain(first))
        require(len(data) >= 512, 'Empty directory allocation')
        if count is None:
            count = struct.unpack_from('<I', data, 4)[0]
        require(2 <= count <= len(data) // 512, 'Invalid directory entry count')
        result, names = [], set()
        for offset in range(0, count * 512, 512):
            mode, _, length, _, cluster, _, _, _, raw_name = struct.unpack_from(
                '<HHI8sII8sI28x448s', data, offset)
            if not mode & 0x8000:
                continue
            require(b'\0' in raw_name, 'Unterminated memory-card filename')
            # Preserve non-ASCII names for unrelated games without interpreting them.
            name = raw_name.split(b'\0', 1)[0].decode('ascii', errors='surrogateescape')
            require(name and not any(c in name for c in '/\\:\x00'), 'Invalid memory-card filename')
            require(name not in names, 'Duplicate memory-card filename')
            require(bool(mode & 0x10) != bool(mode & 0x20), 'Invalid directory entry type')
            names.add(name)
            result.append(Entry(name, mode, length, cluster))
        return result

    def files(self, directory):
        """Read one selected directory, without recursively traversing other saves."""
        require(directory.is_directory, 'Expected a save directory')
        files = {}
        for entry in self.directory(directory.cluster, directory.length):
            if entry.name in ('.', '..'):
                continue
            require(not entry.is_directory, 'Nested save directories are unsupported')
            files[entry.name] = self.contents(entry.cluster, entry.length)
        return files
