$ErrorActionPreference = "Stop"

$distribution = if ($env:WSL_DISTRO) { $env:WSL_DISTRO } else { "Ubuntu" }

& wsl.exe --distribution $distribution --user root --exec bash -lc "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y bubblewrap python3 nodejs npm default-jdk-headless build-essential && env PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin npm install --global typescript@5.9.3"
if ($LASTEXITCODE -ne 0) {
    throw "Installing the WSL sandbox toolchain failed."
}

Write-Host "WSL sandbox and language toolchains installed. Restart the backend and refresh runner status."
