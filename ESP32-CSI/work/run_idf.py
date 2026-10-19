import os
import pathlib
import subprocess
import sys
from datetime import datetime

root = pathlib.Path(__file__).resolve().parent
idf = root / 'esp-idf'
tools = root / 'espressif-tools'
python_env = tools / 'python_env' / 'idf5.5_py3.12_env'
python = python_env / 'Scripts' / 'python.exe'
os.environ.update({
    'IDF_PATH': str(idf),
    'IDF_TOOLS_PATH': str(tools),
    'IDF_PYTHON_ENV_PATH': str(python_env),
    'IDF_SKIP_CHECK_SUBMODULES': '1',
    'PIP_CACHE_DIR': str(root / 'pip-cache'),
    'CCACHE_DIR': str(root / 'ccache'),
    'IDF_COMPONENT_CACHE_PATH': str(root / 'component-cache'),
})
os.environ['PATH'] = str(python.parent) + os.pathsep + os.environ['PATH']
exports = subprocess.check_output([str(python), str(idf / 'tools/idf_tools.py'), 'export', '--format', 'key-value'], text=True)
for line in exports.splitlines():
    if '=' in line:
        key, value = line.split('=', 1)
        os.environ[key] = value.replace('%PATH%', os.environ['PATH']).replace('$PATH', os.environ['PATH'])
project = root / 'esp-csi/examples/get-started/csi_recv_router'
os.environ.update({
    'GIT_CONFIG_COUNT': '2',
    'GIT_CONFIG_KEY_0': 'safe.directory',
    'GIT_CONFIG_VALUE_0': str(root / 'esp-csi').replace('\\', '/'),
    'GIT_CONFIG_KEY_1': 'safe.directory',
    'GIT_CONFIG_VALUE_1': str(idf).replace('\\', '/'),
})
ninja = next((tools / 'tools/ninja').rglob('ninja.exe'))
os.environ['CSI_NINJA'] = str(ninja)
gcc = next((tools / 'tools/xtensa-esp-elf').rglob('xtensa-esp-elf-gcc.exe'))
gxx = gcc.with_name('xtensa-esp-elf-g++.exe')
os.environ['CSI_TOOLCHAIN_BIN'] = str(gcc.parent)
os.environ['XTENSA_GNU_CONFIG'] = str(gcc.parent.parent / 'lib/xtensa_esp32.so')
os.environ['IDF_CCACHE_ENABLE'] = '0'
build = root / 'csi-build-esp32'
cache = build / 'CMakeCache.txt'
if '--help' not in sys.argv and cache.exists():
    old_home = next((line.split('=', 1)[1] for line in cache.read_text(encoding='utf-8').splitlines()
                     if line.startswith('CMAKE_HOME_DIRECTORY:INTERNAL=')), None)
    if old_home and os.path.normcase(os.path.normpath(old_home)) != os.path.normcase(str(project)):
        archived = root / ('csi-build-esp32-before-move-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        if build.resolve().parent != root or archived.resolve().parent != root:
            raise RuntimeError('Build archive must remain inside this work directory')
        build.rename(archived)
        print(f'Previous build preserved at {archived}. Rebuilding for the new location.', flush=True)
raise SystemExit(subprocess.call([
    str(python), str(idf / 'tools/idf.py'), '-C', str(project), '-B', str(build),
    '-D', 'SDKCONFIG_DEFAULTS=sdkconfig.local.defaults',
    '-D', f'CMAKE_TOOLCHAIN_FILE={(idf / "tools/cmake/toolchain-esp32.cmake").as_posix()}',
    '-D', f'CMAKE_MAKE_PROGRAM={ninja.as_posix()}',
    '-D', f'CMAKE_PROGRAM_PATH={gcc.parent.as_posix()};{ninja.parent.as_posix()}',
    '-D', f'CMAKE_C_COMPILER={gcc.as_posix()}',
    '-D', f'CMAKE_CXX_COMPILER={gxx.as_posix()}',
    '-D', f'CMAKE_ASM_COMPILER={gcc.as_posix()}',
    '-D', 'CCACHE_ENABLE=0', *sys.argv[1:]
]))


