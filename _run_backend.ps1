Set-Location $PSScriptRoot
Write-Host "  Chika Backend  --  http://localhost:8000" -ForegroundColor Cyan
Write-Host ""
python api/server.py
