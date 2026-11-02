"""Regression: native stderr must not abort ESP32.ps1 or hide a failing exit code.

Uses a fake Python runner; never invokes a compiler or touches a serial port.
"""
from pathlib import Path
from itertools import product
import os
import shutil
import subprocess
import tempfile

here = Path(__file__).resolve().parent
work_root = here.parents[4]
project = work_root.parent
scratch = work_root / 'host-tools/powershell-check'
scratch.mkdir(parents=True, exist_ok=True)
real_env = work_root / 'espressif-tools/python_env/idf5.5_py3.12_env'
shells = [shutil.which('powershell.exe'), shutil.which('pwsh.exe')]
assert any(shells), 'PowerShell not found'
with tempfile.TemporaryDirectory(prefix='stderr-', dir=scratch) as temp:
    root = Path(temp)
    assert root.resolve().parent == scratch.resolve()
    outputs = root / 'outputs'
    outputs.mkdir()
    shutil.copy2(project / 'outputs/ESP32.ps1', outputs / 'ESP32.ps1')
    env = root / 'work/espressif-tools/python_env/idf5.5_py3.12_env'
    (env / 'Scripts').mkdir(parents=True)
    shutil.copy2(real_env / 'Scripts/python.exe', env / 'Scripts/python.exe')
    shutil.copy2(real_env / 'pyvenv.cfg', env / 'pyvenv.cfg')
    (root / 'work/run_idf.py').write_text(
        "import os,sys\n"
        "sys.stderr.write('skip submodule check on internal CI\\n')\n"
        "sys.stderr.flush()\n"
        "assert sys.argv[1:] == (['-p','COM8','-b',os.environ['TEST_BAUD'],'flash'] "
        "if os.environ['TEST_ACTION']=='flash' else [os.environ['TEST_ACTION']])\n"
        "code=int(os.environ['TEST_EXIT'])\n"
        "print('Project build complete' if code==0 else 'fatal error: simulated failure')\n"
        "sys.exit(code)\n", encoding='utf-8')
    caller = root / 'caller.ps1'
    caller.write_text(
        "$ErrorActionPreference='Stop'\n"
        "$params=@{Action=$env:TEST_ACTION;Port='COM8'}\n"
        "if($env:TEST_BAUD -ne '115200'){$params.Baud=[int]$env:TEST_BAUD}\n"
        "& (Join-Path $PSScriptRoot 'outputs/ESP32.ps1') @params "
        "2>&1 | Tee-Object -FilePath (Join-Path $PSScriptRoot 'captured.log')\n"
        "$result=$LASTEXITCODE\n"
        "Write-Output ('WRAPPER_EXIT='+$result)\n"
        "exit $result\n", encoding='utf-8')
    for shell in filter(None, shells):
        cases = [(action, code, 115200) for action, code in product(('build', 'flash', 'reconfigure'), (0, 7))]
        cases += [('flash', 0, 57600), ('flash', 7, 57600)]
        for action, code, baud in cases:
            child_env = dict(os.environ, TEST_ACTION=action, TEST_EXIT=str(code), TEST_BAUD=str(baud))
            result = subprocess.run([
                shell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(caller)
            ], env=child_env, capture_output=True, text=True, errors='replace', timeout=60)
            assert result.returncode == code, (shell, action, code, result.stdout, result.stderr)
            assert 'skip submodule check on internal CI' in result.stdout
            assert f'WRAPPER_EXIT={code}' in result.stdout
            assert 'NativeCommandError' not in result.stdout + result.stderr
            assert ('Project build complete' if code == 0 else 'fatal error: simulated failure') in result.stdout
            print(f'{Path(shell).name}: {action}, baud {baud}, native exit {code}: passed')
print('PowerShell stderr and exit-code regression tests passed.')
