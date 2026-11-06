"""Bundle the unmodified official DolphinTool; no emulator or game data."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://dl.dolphin-emu.org/releases/2609a/dolphin-2609a-x64.7z'
SHA256 = 'bbfd13bf9e6d2a4164a15c392b1f32a9b18150e5136746b388704608fbb60f76'
TOOL_SHA256 = '63dd9bad68996f4c75302fde1a2374ebecfa767df6780619d658f41684f97e8a'
SOURCE = 'https://github.com/dolphin-emu/dolphin/tree/409881c34357d0f105fd473167d15ab0bd9c1628'

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--write', action='store_true')
    p.add_argument('--seven-zip', default='C:/Program Files/7-Zip/7z.exe')
    a = p.parse_args()
    print('Official DolphinTool 2609a, Windows x64; pinned archive/tool hashes; COPY/ license texts and exact source URL. No game/emulator files.')
    if not a.write:
        return
    archive = ROOT/'.build-tools/dolphin-2609a-x64.7z'
    archive.parent.mkdir(exist_ok=True)
    if not archive.exists():
        urllib.request.urlretrieve(URL, archive)
    if archive.stat().st_size != 20037671 or hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise ValueError('Official Dolphin archive failed verification')
    with tempfile.TemporaryDirectory(dir=str(archive.parent)) as folder:
        stage = Path(folder)
        subprocess.run([a.seven_zip, 'x', str(archive), '-o'+str(stage), '-y',
                        'Dolphin-x64/DolphinTool.exe', 'Dolphin-x64/COPYING', 'Dolphin-x64/Licenses/*'],
                       check=True, capture_output=True)
        source = stage/'Dolphin-x64'
        if hashlib.sha256((source/'DolphinTool.exe').read_bytes()).hexdigest() != TOOL_SHA256:
            raise ValueError('Official DolphinTool failed verification')
        notice = ('DolphinTool 2609a, unmodified official Windows x64 binary.\n'
                  'Copyright Dolphin Emulator Project and contributors.\n'
                  'COPYING and Licenses/ retain the original distribution notices.\n'
                  'Exact corresponding source: '+SOURCE+'\n'
                  'Source archive: https://github.com/dolphin-emu/dolphin/archive/409881c34357d0f105fd473167d15ab0bd9c1628.zip\n'
                  'Binary archive: '+URL+'\nArchive SHA-256: '+SHA256+'\n'
                  'Tool SHA-256: '+TOOL_SHA256+'\n'
                  'Windows 10 1903+ x64; Microsoft Visual C++ v14 runtime required.\n'
                  'Only disc conversion is used; Dolphin.exe and game assets are not bundled or launched.\n')
        (source/'NOTICE.txt').write_text(notice, encoding='utf-8')
        output = ROOT/'retro_trans/resources/dolphin-tool-windows.zip'
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for f in sorted(source.rglob('*')):
                if f.is_file():
                    info = zipfile.ZipInfo(f.relative_to(source).as_posix(), (2026, 11, 6, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o644 << 16
                    z.writestr(info, f.read_bytes())
        (ROOT/'retro_trans/resources/RVZ-NOTICE.txt').write_text(notice, encoding='utf-8')
        print('Bundle SHA-256:', hashlib.sha256(output.read_bytes()).hexdigest())

if __name__ == '__main__':
    main()
