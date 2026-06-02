#Requires -RunAsAdministrator
# NetNavi OS Windows Deployment Bootstrapper

Write-Host "=================================================" -ForegroundColor Cyan
Write-Host " 🌐 Initializing NetNavi OS Deployment Sequence 🌐" -ForegroundColor Cyan
Write-Host "=================================================" -ForegroundColor Cyan

Write-Host "`n[1/4] Installing Core Dependencies via Winget..." -ForegroundColor Yellow
# Install Python
Write-Host "-> Installing Python..."
winget install --id Python.Python.3.11 -e --accept-package-agreements --accept-source-agreements --silent

# Install Node.js
Write-Host "-> Installing Node.js..."
winget install --id OpenJS.NodeJS -e --accept-package-agreements --accept-source-agreements --silent

# Install Obsidian
Write-Host "-> Installing Obsidian..."
winget install --id Obsidian.Obsidian -e --accept-package-agreements --accept-source-agreements --silent

# Install Gephi
Write-Host "-> Installing Gephi..."
winget install --id Gephi.Gephi -e --accept-package-agreements --accept-source-agreements --silent

Write-Host "`n[2/4] Refreshing Environment Variables..." -ForegroundColor Yellow
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

Write-Host "`n[3/4] Installing Gemini CLI & Action Layer Dependencies..." -ForegroundColor Yellow
npm install -g @google/gemini-cli

Write-Host "`n[4/5] Opening Antigravity IDE plugin page in your browser..." -ForegroundColor Yellow
Start-Process "https://antigravity.google/"

Write-Host "`n[4.5/5] Installing Python Package Dependencies..." -ForegroundColor Yellow
pip install websockets cryptography

Write-Host "`n[5/5] Installation Complete!" -ForegroundColor Green
Write-Host "=================================================" -ForegroundColor Cyan

Write-Host "`nExecuting The Awakening Sequence..." -ForegroundColor Magenta
Start-Sleep -Seconds 2

# Check if Python is globally available before running the Awakening script
if (Get-Command "python" -ErrorAction SilentlyContinue) {
    python .\Awakening.py
} else {
    Write-Host "Python path not found. Please restart your terminal and run 'python Awakening.py' manually." -ForegroundColor Red
}
