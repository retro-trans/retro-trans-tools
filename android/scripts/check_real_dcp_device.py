"""Opt-in local real-disc tests on an explicitly selected disposable Android emulator.

Requires a root-capable test emulator with both debug APKs already installed.
Never discovers devices, installs to a personal phone, uploads files, or deletes
prior outputs. Original discs are read-only and rehashed against release metadata.
"""
import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from retro_trans.core import sha256_file


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--adb', type=Path, required=True)
    p.add_argument('--serial', required=True)
    p.add_argument('--game-root', type=Path, required=True)
    p.add_argument('--work', type=Path, required=True)
    p.add_argument('--discs', type=int, nargs='+', default=[1, 2], choices=[1, 2])
    a = p.parse_args()
    if not a.serial.startswith('emulator-') or a.work.exists():
        raise ValueError('Explicit emulator serial and NEW local work directory required.')
    a.work.mkdir(parents=True)
    def adb(*args):
        return subprocess.run([str(a.adb), '-s', a.serial, *args], check=True,
                              capture_output=True, text=True, encoding='utf-8', errors='replace')
    def shell(command):
        return adb('shell', command).stdout
    assert shell('id -u').strip() == '0', 'Use only an explicitly rooted disposable test emulator.'
    manifest = json.loads((a.game_root / 'build/automatic-dcp-0.5.20/ready/DCP-AUTOMATIC.json').read_text())
    package = 'org.retrotrans.tools.debug'
    remote = '/data/user/0/' + package + '/files/' + a.work.name
    assert shell('test -e ' + shlex.quote(remote) + '; echo $?').strip() == '1', 'Preserve prior device outputs.'
    shell('run-as ' + package + ' mkdir ' + shlex.quote('files/' + a.work.name))
    uid = shell('stat -c %u ' + shlex.quote(remote)).strip()
    for row in manifest['patches']:
        disc = row['metadata']['disc']
        if disc not in a.discs:
            continue
        srcdir = remote + f'/disc{disc}'
        shell('run-as ' + package + ' mkdir ' + shlex.quote(f'files/{a.work.name}/disc{disc}'))
        cue = a.game_root / f'Black-Matrix Advanced (Japan) (Disc {disc}).cue'
        text = cue.read_text()
        for i, identity in enumerate(row['source_tracks'], 1):
            original = a.game_root / f'Black-Matrix Advanced (Japan) (Disc {disc}) (Track {i}).bin'
            assert original.stat().st_size == identity['bytes'] and sha256_file(original) == identity['sha256']
            print('Copying local test input, disc', disc, 'track', i, flush=True)
            adb('push', str(original), srcdir + f'/track0{i}.bin')
            text = text.replace('"' + original.name + '"', f'"track0{i}.bin"')
        descriptor = a.work / f'disc{disc}.cue'
        descriptor.write_text(text)
        adb('push', str(descriptor), srcdir + '/disc.cue')
        patch = a.game_root / 'build/dcp-v0.9.0/ready' / row['patch']
        assert patch.stat().st_size == row['bytes'] and sha256_file(patch) == row['sha256']
        adb('push', str(patch), srcdir + '/patch.dcp')
        shell('chown -R ' + uid + ':' + uid + ' ' + shlex.quote(srcdir))
        shell('restorecon -R ' + shlex.quote(srcdir))
        command = ['am', 'instrument', '-w', '-e', 'class',
                   'org.retrotrans.tools.DcpDeviceTest#optionalRealDiscWithAndroidNativeDecoder',
                   '-e', 'dcp_source', srcdir + '/disc.cue', '-e', 'dcp_patch', srcdir + '/patch.dcp',
                   '-e', 'dcp_output', remote + f'/disc{disc}-gdi',
                   package + '.test/androidx.test.runner.AndroidJUnitRunner']
        print('Running real Android native DCP, disc', disc, flush=True)
        result = shell(shlex.join(command))
        (a.work / f'disc{disc}-instrumentation.log').write_text(result)
        print(result[-2500:], flush=True)
        assert 'OK (1 test)' in result and 'FAILURES' not in result and 'INSTRUMENTATION_FAILED' not in result
        # adb's directory semantics depend on whether the destination exists.
        # Use a fresh parent per attempt; preserve any partial previous transfer.
        # Emulator adbd may reconnect after the instrumentation process exits.
        for _ in range(30):
            state = subprocess.run([str(a.adb), '-s', a.serial, 'get-state'], capture_output=True, text=True)
            if state.returncode == 0 and state.stdout.strip() == 'device':
                break
            time.sleep(2)
        for attempt in range(1, 4):
            parent = a.work / f'disc{disc}-download-{attempt}'
            parent.mkdir()
            try:
                adb('pull', remote + f'/disc{disc}-gdi', str(parent))
                downloaded = parent / f'disc{disc}-gdi'
                proof = json.loads((downloaded / 'DCP-VALIDATION.json').read_text())
                for name, identity in proof['output_files'].items():
                    file = downloaded / name
                    assert file.stat().st_size == identity['bytes'] and sha256_file(file) == identity['sha256']
                (a.work / f'disc{disc}-download.json').write_text(json.dumps({'output': str(downloaded.resolve()), 'proof': proof}, indent=2))
                break
            except subprocess.CalledProcessError as error:
                print('Local transfer retry:', (error.stderr or error.stdout)[-1000:], flush=True)
                if attempt == 3:
                    raise
                time.sleep(3)
        for i, identity in enumerate(row['source_tracks'], 1):
            original = a.game_root / f'Black-Matrix Advanced (Japan) (Disc {disc}) (Track {i}).bin'
            assert original.stat().st_size == identity['bytes'] and sha256_file(original) == identity['sha256']
        print('Disc', disc, 'Android output retained locally; originals unchanged.', flush=True)


if __name__ == '__main__':
    main()
