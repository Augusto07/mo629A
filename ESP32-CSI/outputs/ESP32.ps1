param(
    [ValidateSet('build','flash','monitor','menuconfig')]
    [string]$Action = 'build',
    [string]$Port = 'COM7'
)
$ErrorActionPreference = 'Stop'
$taskWork = Join-Path (Split-Path $PSScriptRoot -Parent) 'work'
$taskPython = Join-Path $taskWork 'espressif-tools\python_env\idf5.5_py3.12_env\Scripts\python.exe'
$taskRunner = Join-Path $taskWork 'run_idf.py'
if (!(Test-Path -LiteralPath $taskPython) -or !(Test-Path -LiteralPath $taskRunner)) {
    throw 'O ambiente ESP-IDF na pasta work nao foi encontrado. Mantenha outputs e work juntas dentro de ESP32-CSI.'
}
if ($Action -eq 'flash') {
    & $taskPython $taskRunner -p $Port -b 115200 flash
} elseif ($Action -eq 'monitor') {
    & $taskPython $taskRunner -p $Port monitor
} else {
    & $taskPython $taskRunner $Action
}
exit $LASTEXITCODE
