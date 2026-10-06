$ErrorActionPreference = "Stop"

$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    throw "Docker CLI is not installed. Install Docker Desktop and enable its WSL 2 engine, then rerun this script."
}

docker info | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop is installed but its engine is not running. Start Docker Desktop, then rerun this script."
}

$image = if ($env:CODE_RUNNER_IMAGE) { $env:CODE_RUNNER_IMAGE } else { "ai-coding-assistant-runner:latest" }
docker build --tag $image --file (Join-Path $PSScriptRoot "Dockerfile") $PSScriptRoot
if ($LASTEXITCODE -ne 0) {
    throw "Building the isolated language runner failed."
}

Write-Host "Isolated runner image '$image' is ready for Python, JavaScript, TypeScript, Java, C, and C++."
