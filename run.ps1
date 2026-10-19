<#
  One command to install, build and start d2bg on Windows:   .\run.cmd   (or .\run.ps1)

  - Python 3.12 and the app's packages come from uv (it downloads Python if needed).
  - The browser UI is built with Node the first time, and again whenever web/ changes.
  - Then the app starts on http://127.0.0.1:4242 and opens your browser.

  Extra arguments go to `d2bg serve`, for example:  .\run.cmd --demo juggernaut   or   .\run.cmd --lan
#>
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Need($cmd, $hint) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Host "Missing: $cmd. $hint" -ForegroundColor Red
        exit 1
    }
}

Need "uv" "Install it with:  winget install astral-sh.uv   (then open a new terminal)"

Write-Host "Installing Python packages (first run takes a minute)..."
uv sync --quiet --inexact
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$dist = Join-Path $PSScriptRoot "src\d2bg\static\index.html"
$newestSource = Get-ChildItem -Path "web\src", "web\index.html", "web\package.json" -Recurse -File |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
$needBuild = -not (Test-Path $dist) -or ($newestSource.LastWriteTime -gt (Get-Item $dist).LastWriteTime)

if ($needBuild) {
    Need "npm" "Install Node.js 20 or newer from https://nodejs.org (needed once to build the UI)"
    Push-Location web
    try {
        if (-not (Test-Path "node_modules")) {
            Write-Host "Installing UI packages..."
            npm ci --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }
        Write-Host "Building the UI..."
        npm run build --silent
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    finally {
        Pop-Location
    }
}

uv run d2bg serve @args
exit $LASTEXITCODE
