$ErrorActionPreference = 'Stop'
$bat = Join-Path $PSScriptRoot 'StartBot.bat'
if (-not (Test-Path $bat)) { throw "missing $bat" }
Start-Process -FilePath $bat -WorkingDirectory $PSScriptRoot -Verb RunAs
