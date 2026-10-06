$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$backendDirectory = Join-Path $projectRoot "backend"
$frontendDirectory = Join-Path $projectRoot "frontend"
$python = Join-Path $backendDirectory "venv\Scripts\python.exe"
$startupDirectory = [Environment]::GetFolderPath("Startup")
$logDirectory = Join-Path $env:LOCALAPPDATA "AICodingAssistant\logs"

if (-not (Test-Path $python)) {
    throw "Backend Python environment is missing. Create backend\venv and install backend requirements first."
}
if (-not (Test-Path (Join-Path $frontendDirectory ".next"))) {
    throw "Frontend production build is missing. Run npm run build in the frontend folder first."
}

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

function Test-ListeningPort([int] $port) {
    return [bool](Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
        Select-Object -First 1)
}

if (-not (Test-ListeningPort 8000)) {
    Start-Process `
        -FilePath $python `
        -ArgumentList @("-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000") `
        -WorkingDirectory $backendDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDirectory "backend.out.log") `
        -RedirectStandardError (Join-Path $logDirectory "backend.err.log") | Out-Null
}

if (-not (Test-ListeningPort 3001)) {
    Start-Process `
        -FilePath $env:ComSpec `
        -ArgumentList @("/d", "/s", "/c", "npm run start -- --hostname 127.0.0.1 --port 3001") `
        -WorkingDirectory $frontendDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDirectory "frontend.out.log") `
        -RedirectStandardError (Join-Path $logDirectory "frontend.err.log") | Out-Null
}

$shortcutPath = Join-Path $startupDirectory "AI Coding Assistant Local Review.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $PSHOME "powershell.exe"
$shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$($MyInvocation.MyCommand.Path)`""
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Description = "Start the AI Coding Assistant for local review when you sign in."
$shortcut.Save()

Write-Output "Local review services are starting."
Write-Output "Frontend: http://localhost:3001"
Write-Output "Backend:  http://127.0.0.1:8000"
Write-Output "Automatic startup is configured for your next Windows sign-in."
Write-Output "Server logs: $logDirectory"
