"""Build only the pinned Dolphin disc-image tool, without an emulator frontend."""
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
COMMIT = '409881c34357d0f105fd473167d15ab0bd9c1628'
SOURCE = ROOT/'.build-tools/dolphin-linux-source'
BUILD = ROOT/'.build-tools/dolphin-linux-build'
OFF = ('QT', 'NOGUI', 'TESTS', 'ANALYTICS', 'AUTOUPDATE', 'X11', 'EGL',
       'ALSA', 'PULSEAUDIO', 'CUBEB', 'LLVM', 'VULKAN', 'SDL', 'HWDB', 'EVDEV')
MODULES = ('fmt/fmt', 'implot/implot', 'imgui/imgui', 'glslang/glslang',
           'tinygltf/tinygltf', 'enet/enet', 'xxhash/xxHash', 'zlib-ng/zlib-ng',
           'minizip-ng/minizip-ng', 'libspng/libspng', 'SFML/SFML',
           'watcher/watcher', 'cpp-ipc/cpp-ipc', 'cpp-optparse/cpp-optparse',
           'pugixml/pugixml', 'hidapi/hidapi-src', 'libusb/libusb')


def run(*args, cwd=ROOT):
    subprocess.run(args, cwd=cwd, check=True)


def build():
    SOURCE.mkdir(parents=True, exist_ok=True)
    if not (SOURCE/'.git').exists():
        run('git', 'init', str(SOURCE))
        run('git', 'remote', 'add', 'origin', 'https://github.com/dolphin-emu/dolphin.git', cwd=SOURCE)
    run('git', 'fetch', '--depth=1', 'origin', COMMIT, cwd=SOURCE)
    run('git', 'checkout', '--detach', COMMIT, cwd=SOURCE)
    run('git', 'submodule', 'update', '--init', '--depth=1', '--jobs=4',
        *('Externals/'+name for name in MODULES), cwd=SOURCE)
    flags = ['-DENABLE_'+name+'=OFF' for name in OFF]
    flags += ['-D'+name+'=OFF' for name in ('USE_UPNP', 'USE_DISCORD_PRESENCE',
              'USE_MGBA', 'USE_RETRO_ACHIEVEMENTS', 'ENCODE_FRAMEDUMPS')]
    run('cmake', '-S', str(SOURCE), '-B', str(BUILD), '-G', 'Ninja',
        '-DCMAKE_BUILD_TYPE=Release', '-DENABLE_CLI_TOOL=ON',
        '-DDISTRIBUTOR=Retro Trans', *flags)
    run('cmake', '--build', str(BUILD), '--target', 'dolphin-tool', '--parallel', '2')
    return BUILD/'Binaries/dolphin-tool'


def copy_notices(destination):
    destination.mkdir(parents=True, exist_ok=True)
    for base, dirs, files in os.walk(SOURCE):
        dirs[:] = [name for name in dirs if name != '.git']
        for name in files:
            if name.lower().startswith(('license', 'copying', 'copyright', 'notice')):
                path = Path(base)/name
                target = destination/path.relative_to(SOURCE)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
    modules = subprocess.check_output(['git', 'submodule', 'status'], cwd=SOURCE, text=True)
    (destination/'SOURCE.json').write_text(json.dumps(dict(
        source='https://github.com/dolphin-emu/dolphin/tree/'+COMMIT,
        commit=COMMIT, submodules=modules.splitlines(),
        build_instructions='scripts/bundle_linux_dolphin.py in the Retro Trans source release'), indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    print(build())
