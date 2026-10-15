param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
& $Python -m venv "$PSScriptRoot/.venv"
if ($LASTEXITCODE) { exit $LASTEXITCODE }
& "$PSScriptRoot/.venv/Scripts/python.exe" -m pip install -r "$PSScriptRoot/requirements.txt"
if ($LASTEXITCODE) { exit $LASTEXITCODE }
& "$PSScriptRoot/.venv/Scripts/python.exe" "$PSScriptRoot/manage.py" plugins
exit $LASTEXITCODE
