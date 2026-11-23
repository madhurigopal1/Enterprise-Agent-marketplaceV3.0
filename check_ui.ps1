# Verifies that the RUNNING server is this build and that the Approvals tab is served.
# Usage (from the repo folder, while run.bat is running in another window):
#   powershell -ExecutionPolicy Bypass -File .\scripts\check_ui.ps1
param([string]$Base = "http://127.0.0.1:8000")
$ErrorActionPreference = "Stop"
Write-Host "1) Local file contains Approvals tab:" -NoNewline
if (Select-String -Path ".\app\static\index.html" -Pattern 'data-tab="approvals"' -Quiet) { Write-Host " YES" -ForegroundColor Green } else { Write-Host " NO - wrong folder/ZIP" -ForegroundColor Red }
try {
  $v = Invoke-RestMethod "$Base/api/version"
  Write-Host "2) Running server version: $($v.version)"
  Write-Host "   Server static folder : $($v.static_dir)"
  Write-Host "   Server UI has Approvals tab:" -NoNewline
  if ($v.ui_has_approvals_tab) { Write-Host " YES" -ForegroundColor Green } else { Write-Host " NO" -ForegroundColor Red }
} catch {
  Write-Host "2) /api/version not found -> port 8000 is running an OLD build. Stop it:" -ForegroundColor Red
  Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    $p = Get-Process -Id $_.OwningProcess; Write-Host "   PID $($p.Id) $($p.ProcessName)  ->  Stop-Process -Id $($p.Id) -Force" }
  exit 1
}
$html = (Invoke-WebRequest -UseBasicParsing "$Base/").Content
Write-Host "3) Served HTML contains Approvals tab:" -NoNewline
if ($html -match 'data-tab="approvals"') { Write-Host " YES - press Ctrl+F5 in the browser" -ForegroundColor Green } else { Write-Host " NO" -ForegroundColor Red }
