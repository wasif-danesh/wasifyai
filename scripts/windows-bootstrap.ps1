# Bootstrap wasifyai on Windows by setting up WSL2 + Ubuntu and running the normal Linux setup
# inside it. Run from an elevated PowerShell. NOT yet tested on a Windows machine.
#   powershell -ExecutionPolicy Bypass -File scripts\windows-bootstrap.ps1
$ErrorActionPreference = "Stop"
$distro = "Ubuntu-24.04"
$repo = "https://github.com/wasif-danesh/wasifyai.git"

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Write-Error "Run this from an elevated (Administrator) PowerShell."
}

$installed = (wsl --list --quiet 2>$null) -replace "`0", "" | Where-Object { $_ -eq $distro }
if (-not $installed) {
  Write-Host "Installing WSL2 with $distro. A reboot may be required; if so, reboot and run this script again."
  wsl --install -d $distro
  Write-Host "Finish the Ubuntu first-run user setup, then run this script again."
  exit 0
}

Write-Host "Enabling systemd in $distro (restart follows)."
wsl -d $distro -u root -- bash -c "grep -q systemd=true /etc/wsl.conf 2>/dev/null || printf '[boot]\nsystemd=true\n' >> /etc/wsl.conf"
wsl --terminate $distro

Write-Host "Cloning wasifyai into the Linux home directory and running setup."
wsl -d $distro -- bash -lc "cd ~ && { [ -d wasifyai ] || git clone $repo; } && cd wasifyai && make setup"

Write-Host ""
Write-Host "Setup finished. In Ubuntu: cd ~/wasifyai && make dev   then open http://localhost:3000"
