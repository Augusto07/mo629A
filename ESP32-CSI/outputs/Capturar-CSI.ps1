param(
    [ValidateRange(0, 2147483647)]
    [int]$Segundos = 60,
    [string]$Porta = 'COM7'
)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskPython = Join-Path $taskRoot 'work\espressif-tools\python_env\idf5.5_py3.12_env\Scripts\python.exe'
& $taskPython -u (Join-Path $PSScriptRoot 'Capturar-CSI.py') --port $Porta --seconds $Segundos
exit $LASTEXITCODE
