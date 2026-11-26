"""Package the locally verified Android DCP test APK. Does not publish anything."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    assert not args.out.exists(), 'Never overwrite a delivered APK directory.'
    evidence = ROOT / 'build/android-dcp-test2'
    apk = ROOT / 'android/app/build/outputs/apk/debug/app-debug.apk'
    old = evidence / 'installed-tested-before-notices.apk'
    native_proofs = json.loads((evidence / 'independent-device-v1/verification.json').read_text())
    host_proofs = json.loads((evidence / 'independent-host-v1/verification.json').read_text())
    assert {p['disc'] for p in native_proofs} == {1, 2}
    assert native_proofs == host_proofs
    for proof in native_proofs:
        assert proof['originals_unchanged'] and proof['audio_content_and_sample_alignment_preserved']
    final_log = (evidence / 'device-workflow-final-apk.log').read_text(encoding='utf-8-sig')
    assert 'OK (14 tests)' in final_log and 'FAILURES' not in final_log
    for folder, disc in [('real-device-v1', 1), ('real-device-v2', 2)]:
        log = (evidence / folder / f'disc{disc}-instrumentation.log').read_text()
        assert 'OK (1 test)' in log and 'FAILURES' not in log
    libraries = []
    with zipfile.ZipFile(apk) as archive, zipfile.ZipFile(old) as previous:
        executable_names = [n for n in archive.namelist() if n.endswith(('.dex', '.so'))]
        assert executable_names and all(archive.read(n) == previous.read(n) for n in executable_names)
        assets = [n for n in archive.namelist() if n.startswith('assets/')]
        assert set(assets) == {'assets/catalog.json', 'assets/NOTICES.txt', 'assets/APACHE-2.0.txt',
                               'assets/XDELTA-LICENSE.txt', 'assets/XZ-LICENSE.txt'}
        catalog = json.loads(archive.read('assets/catalog.json'))
        assert sum(len(r['manifest']['patches']) for r in catalog['dcp_releases']) == 2
        for name in executable_names:
            if not name.endswith('.so'):
                continue
            data = archive.read(name)
            assert data[:6] == b'\x7fELF\x02\x01'
            phoff = struct.unpack_from('<Q', data, 32)[0]
            phsize, count = struct.unpack_from('<HH', data, 54)
            alignments = [struct.unpack_from('<Q', data, phoff + i * phsize + 48)[0]
                          for i in range(count) if struct.unpack_from('<I', data, phoff + i * phsize)[0] == 1]
            assert alignments and all(n >= 16384 for n in alignments)
            libraries.append({'library': name, 'load_segment_alignments': alignments})
    jvm_tests = []
    for path in (ROOT / 'android/patch-core/build/test-results/test').glob('TEST-*.xml'):
        row = ET.parse(path).getroot().attrib
        assert row['failures'] == row['errors'] == '0'
        jvm_tests.append({k: row[k] for k in ['name', 'tests', 'skipped', 'failures', 'errors']})
    lint = ET.parse(ROOT / 'android/app/build/reports/lint-results-debug.xml').getroot()
    assert not any(i.attrib.get('severity') in ('Fatal', 'Error') for i in lint.findall('issue'))
    report = {
        'version_name': '0.1.0-test2', 'version_code': 2, 'package': 'org.retrotrans.tools.debug',
        'local_test_only': True, 'published': False, 'date': '2026-11-02',
        'apk': {'name': 'Retro-Trans-Android-0.1.0-test2.apk', 'bytes': apk.stat().st_size, 'sha256': sha(apk)},
        'signing': {'type': 'Android debug', 'certificate_sha256': '32fcd938f3658c416b38bfae12d4c5de22f7811cab981ca9a2854244926ea5f7'},
        'compiled_abis': ['arm64-v8a', 'x86_64'], 'min_sdk': 26, 'target_sdk': 36,
        'jvm_tests': jvm_tests, 'emulator_suite': {'result': 'OK (14 tests)', 'api': 36, 'abi': 'x86_64', 'page_size': 4096},
        'real_disc_android_native_tests': {'disc1_seconds': 66.671, 'disc2_seconds': 48.071, 'result': 'Both passed'},
        'independent_desktop_udp_verification': native_proofs,
        'tested_dex_and_native_bytes_identical_to_final_apk': True,
        'only_apk_content_change_after_real_disc_tests': 'assets/NOTICES.txt',
        'final_apk_signature_verified': True, 'final_apk_zip_alignment_16kb_verified': True,
        'native_elf_alignment': libraries,
        'lint_errors': 0, 'lint_warnings': len(lint.findall('issue')),
        'features': ['Automatic DCP for both Black/Matrix AD discs', 'Local DCP tab', 'Verified new-folder SAF export'],
        'limits': ['Experimental three-track MODE1 CUE/GDI to GDI only', 'Requires Retro Trans DCP ZIP-comment verification metadata',
                   'Same-tree file replacements only; no added files/directories', 'No CHD, supplementary/Joliet volumes, multi-extent files or nonzero GDI offsets',
                   'Real ARM64 phone, minimum Android API and 16 KB runtime remain untested', 'No new gameplay or physical Dreamcast tests',
                   'Transient emulator adb output-transfer disconnects were recovered; retained output hashes independently verified'],
        'no_original_game_or_full_translated_disc_in_apk': True,
        'no_github_release_upload_tag_or_catalog_mutation': True,
    }
    args.out.mkdir(parents=True)
    shutil.copyfile(apk, args.out / report['apk']['name'])
    assert sha(args.out / report['apk']['name']) == report['apk']['sha256']
    (args.out / 'VALIDATION.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    shutil.copyfile(ROOT / 'android/README.md', args.out / 'README.md')
    shutil.copyfile(ROOT / 'android/CHANGELOG.md', args.out / 'CHANGELOG.md')
    entries = sorted(p for p in args.out.iterdir() if p.is_file())
    (args.out / 'SHA256SUMS.txt').write_text(''.join(sha(p) + '  ' + p.name + '\n' for p in entries), encoding='ascii')
    print(json.dumps(report['apk'], indent=2))


if __name__ == '__main__':
    main()
