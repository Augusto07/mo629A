$taskRoot = $PSScriptRoot
$env:IDF_PATH = Join-Path $taskRoot 'esp-idf'
$env:IDF_TOOLS_PATH = Join-Path $taskRoot 'espressif-tools'
$env:PIP_CACHE_DIR = Join-Path $taskRoot 'pip-cache'
$env:CCACHE_DIR = Join-Path $taskRoot 'ccache'
$env:IDF_PYTHON_ENV_PATH = Join-Path $env:IDF_TOOLS_PATH 'python_env\idf5.5_py3.12_env'
$env:IDF_SKIP_CHECK_SUBMODULES = '1'
$env:GIT_CONFIG_COUNT = '1'
$env:GIT_CONFIG_KEY_0 = 'http.sslBackend'
$env:GIT_CONFIG_VALUE_0 = 'openssl'
$taskPython = Join-Path $env:IDF_PYTHON_ENV_PATH 'Scripts\python.exe'
$env:PATH = (Join-Path $env:IDF_PYTHON_ENV_PATH 'Scripts') + ';C:\Program Files\Git\cmd;' + $env:PATH
$taskExports = & $taskPython (Join-Path $env:IDF_PATH 'tools\idf_tools.py') export --format key-value
if ($LASTEXITCODE -ne 0) { throw 'Falha ao carregar ferramentas ESP-IDF' }
foreach ($taskLine in $taskExports) {
    if ($taskLine -match '^([^=]+)=(.*)$') {
        $taskValue = $Matches[2].Replace('%PATH%', $env:PATH).Replace('$PATH', $env:PATH)
        [Environment]::SetEnvironmentVariable($Matches[1], $taskValue, 'Process')
    }
}
