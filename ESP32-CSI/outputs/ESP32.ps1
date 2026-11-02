param(
    [ValidateSet('build','flash','monitor','menuconfig','reconfigure')]
    [string]$Action = 'build',
    [string]$Port = 'COM7',
    [ValidateSet(9600,19200,38400,57600,115200,230400,460800,921600)]
    [int]$Baud = 115200
)
$ErrorActionPreference = 'Stop'
$taskWork = Join-Path (Split-Path $PSScriptRoot -Parent) 'work'
$taskPython = Join-Path $taskWork 'espressif-tools\python_env\idf5.5_py3.12_env\Scripts\python.exe'
$taskRunner = Join-Path $taskWork 'run_idf.py'
if (!(Test-Path -LiteralPath $taskPython) -or !(Test-Path -LiteralPath $taskRunner)) {
    throw 'O ambiente ESP-IDF na pasta work nao foi encontrado. Mantenha outputs e work juntas dentro de ESP32-CSI.'
}
$taskArguments = @($taskRunner)
if ($Action -eq 'flash') {
    $taskArguments += @('-p', $Port, '-b', [string]$Baud, 'flash')
} elseif ($Action -eq 'monitor') {
    $taskArguments += @('-p', $Port, 'monitor')
} else {
    $taskArguments += $Action
}

# CMake writes informational messages and warnings to stderr. Windows
# PowerShell 5.1 can turn redirected native stderr into ErrorRecord objects;
# Stop would abort the script even when the compiler subsequently succeeds.
$taskExitCode = 1
try {
    $ErrorActionPreference = 'Continue'
    $PSNativeCommandUseErrorActionPreference = $false
    $global:LASTEXITCODE = 1  # Also report failure if Python cannot start.
    if ($Action -in @('build', 'flash', 'reconfigure')) {
        & $taskPython @taskArguments 2>&1 | ForEach-Object { $_.ToString() }
    } else {
        # Keep real console handles for the interactive monitor/menuconfig.
        & $taskPython @taskArguments
    }
    $taskExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = 'Stop'
}
exit $taskExitCode
