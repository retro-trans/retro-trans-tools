"""Reproduce the pinned offline CHD engine bundle from the official MAME archive."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import tempfile
import urllib.request
import zipfile

VERSION = '0.289'
URL = 'https://github.com/mamedev/mame/releases/download/mame0289/mame0289b_x64.exe'
SIZE = 87626249
SHA256 = 'a1aa7912168c9d1b05e611906bc21b8b9be3935822aead36d12a1da363150b7d'
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seven-zip', default='C:/Program Files/7-Zip/7z.exe')
    args = parser.parse_args()
    archive = ROOT / '.build-tools/mame0289b_x64.exe'
    archive.parent.mkdir(exist_ok=True)
    if not archive.exists():
        urllib.request.urlretrieve(URL, archive)
    if archive.stat().st_size != SIZE or hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise ValueError('Official MAME archive failed verification')
    with tempfile.TemporaryDirectory(dir=str(archive.parent)) as temporary:
        stage = Path(temporary)
        subprocess.run([args.seven_zip, 'x', str(archive), '-o' + str(stage), '-y',
                        'chdman.exe', 'COPYING', 'docs/legal/*'], check=True, capture_output=True)
        # Include the original notices and license texts, plus tool provenance.
        notice = ('chdman ' + VERSION + ' (unmodified official Windows x64 build)\n'
            'Copyright Aaron Giles, MAMEdev and contributors. Tool source: BSD-3-Clause.\n'
            'Source: https://github.com/mamedev/mame/tree/mame0289\n'
            'Binary archive: ' + URL + '\nArchive SHA-256: ' + SHA256 + '\n'
            'Original distribution notices: COPYING and docs/legal/.\n'
            'Windows 10+; x86-64-v2 CPU required by the official MAME build.\n')
        (stage / 'NOTICE.txt').write_text(notice, encoding='utf-8')
        output = ROOT / 'retro_trans/resources/chdman-windows.zip'
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            for path in sorted(stage.rglob('*')):
                if path.is_file():
                    item = zipfile.ZipInfo(path.relative_to(stage).as_posix(), (2026, 7, 30, 0, 0, 0))
                    item.compress_type = zipfile.ZIP_DEFLATED
                    item.external_attr = 0o644 << 16
                    bundle.writestr(item, path.read_bytes())
        (ROOT / 'retro_trans/resources/CHDMAN-NOTICE.txt').write_bytes(notice.encode('utf-8'))
        print('Bundle SHA-256:', hashlib.sha256(output.read_bytes()).hexdigest())
        print('Executable SHA-256:', hashlib.sha256((stage / 'chdman.exe').read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
