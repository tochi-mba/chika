Set-Location (Join-Path $PSScriptRoot "frontend")
Write-Host "  Chika Frontend  --  http://localhost:5173" -ForegroundColor Magenta
Write-Host ""
if (-not (Test-Path "node_modules")) {
    Write-Host "  Installing dependencies..." -ForegroundColor Yellow
    npm install
}
npm run dev
