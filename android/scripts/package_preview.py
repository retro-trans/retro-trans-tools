"""Validate and collect the current Android preview; never publish or read games."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from retro_trans import __version__


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def results(paths):
    rows = []
    for path in paths:
        row = ET.parse(path).getroot().attrib
        if 'tests' not in row:
            continue
        if int(row.get('failures', 0)) or int(row.get('errors', 0)):
            raise RuntimeError('Tests failed: ' + path.name)
        rows.append({k: int(row.get(k, 0)) for k in ('tests', 'failures', 'errors', 'skipped')})
    if not rows or sum(r['tests'] - r['skipped'] for r in rows) < 1:
        raise RuntimeError('No successful test results.')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise RuntimeError('Use a new package directory.')
    android = ROOT/'android'
    apk = android/'app/build/outputs/apk/debug/app-debug.apk'
    sdk = Path(os.environ.get('ANDROID_HOME') or os.environ['ANDROID_SDK_ROOT'])/'build-tools/36.0.0'
    suffix = '.bat' if os.name == 'nt' else ''
    signature = subprocess.check_output([str(sdk/('apksigner'+suffix)), 'verify', '--verbose',
                                        '--print-certs', str(apk)], text=True)
    signer = re.search(r'Signer #1 certificate SHA-256 digest: ([a-fA-F0-9]{64})', signature)
    if not signer:
        raise RuntimeError('Missing verified APK signing identity.')
    subprocess.run([str(sdk/('zipalign.exe' if os.name == 'nt' else 'zipalign')),
                    '-c', '-P', '16', '4', str(apk)], check=True)
    aapt = sdk/('aapt.exe' if os.name == 'nt' else 'aapt')
    badging = subprocess.check_output([str(aapt), 'dump', 'badging', str(apk)], text=True)
    version = __version__ + '-preview'
    if ("name='org.retrotrans.tools.debug'" not in badging or
            "versionName='"+version+"'" not in badging):
        raise RuntimeError('APK package/version mismatch.')
    version_code = int(re.search(r"versionCode='(\d+)'", badging).group(1))
    if 'application-debuggable' not in badging:
        raise RuntimeError('This delivery is explicitly the preview build.')
    libraries = []
    with zipfile.ZipFile(apk) as archive:
        if archive.read('assets/catalog.json') != (ROOT/'retro_trans/resources/catalog.json').read_bytes():
            raise RuntimeError('APK does not contain the release catalog.')
        for name in ('NOTICES.txt', 'APACHE-2.0.txt', 'XDELTA-LICENSE.txt', 'XZ-LICENSE.txt'):
            if not archive.read('assets/'+name).strip():
                raise RuntimeError('Missing dependency notice.')
        for name in archive.namelist():
            if not name.endswith('.so'):
                continue
            data = archive.read(name)
            if data[:6] != b'\x7fELF\x02\x01':
                raise RuntimeError('Expected a 64-bit native engine.')
            offset = struct.unpack_from('<Q', data, 32)[0]
            size, count = struct.unpack_from('<HH', data, 54)
            alignments = [struct.unpack_from('<Q', data, offset+i*size+48)[0] for i in range(count)
                          if struct.unpack_from('<I', data, offset+i*size)[0] == 1]
            if not alignments or min(alignments) < 16384:
                raise RuntimeError('Native library lacks 16 KB alignment: '+name)
            libraries.append(name)
    if not all('lib/'+abi+'/libretro_patch.so' in libraries for abi in ('arm64-v8a', 'x86_64')):
        raise RuntimeError('Both Android architectures are required.')
    jvm = results((android/'patch-core/build/test-results/test').glob('TEST-*.xml'))
    device = results((android/'app/build/outputs/androidTest-results/connected').rglob('TEST-*.xml'))
    lint = ET.parse(android/'app/build/reports/lint-results-debug.xml').getroot()
    if any(i.get('severity') in ('Fatal', 'Error') for i in lint.findall('issue')):
        raise RuntimeError('Android lint failed.')
    name = 'Retro-Trans-Android-'+version+'.apk'
    report = dict(version=__version__, version_name=version, version_code=version_code,
                  package_id='org.retrotrans.tools.debug', preview=True, published=False,
                  source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  apk=dict(name=name, bytes=apk.stat().st_size, sha256=digest(apk)),
                  signer_sha256=signer.group(1).lower(), abis=['arm64-v8a', 'x86_64'],
                  min_sdk=26, native_16kb_alignment=True, apk_16kb_alignment=True,
                  jvm_tests=jvm, emulator_tests=device, lint_errors=0,
                  limitations=['Android preview; manual APK updates.',
                               'ARM64 is compiled; real-phone and 16 KB runtime validation remain outstanding.',
                               'CHD, RVZ, save conversion, combined-source assembly and Vita PKG are desktop-only.',
                               'DCP is experimental three-track/same-tree GDI output.'])
    args.out.mkdir(parents=True)
    shutil.copyfile(apk, args.out/name)
    (args.out/('ANDROID-'+__version__+'-VALIDATION.json')).write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    shutil.copyfile(android/'README.md', args.out/'README-Android.md')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
