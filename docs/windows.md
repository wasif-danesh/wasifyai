# Running wasifyai on Windows (WSL2)

The repo's tooling is bash, so on Windows you run everything **inside WSL2** with an Ubuntu
distro. That is a real Linux environment, so `make setup`, `make dev`, `make kind-up` and the
rest behave exactly as on Linux. Native PowerShell/cmd is not supported.

> Status: the Linux path is tested in Ubuntu and Fedora containers and in CI. The WSL2 specifics
> below, and `scripts/windows-bootstrap.ps1`, have **not** been run on a Windows machine yet.
> Please record anything that differs.

## One-time Windows setup

Requirements: Windows 10 22H2 or Windows 11, virtualisation enabled in BIOS/UEFI, an
administrator account. For GPU acceleration, a current NVIDIA driver on Windows (WSL2 uses it
directly; install no driver inside Linux).

Either run the helper from an elevated PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows-bootstrap.ps1
```

or do it by hand:

```powershell
wsl --install -d Ubuntu-24.04     # reboot if asked, then finish the Ubuntu first-run prompts
```

## Inside Ubuntu (WSL)

1. Enable systemd (recommended; Podman and Ollama services work best with it):

   ```bash
   printf '[boot]\nsystemd=true\n' | sudo tee /etc/wsl.conf
   ```

   Then, from PowerShell: `wsl --shutdown`, and reopen Ubuntu.

2. Clone **inside the Linux filesystem** (your home directory), not under `/mnt/c`. The Windows
   mounts are slow, break file permissions and can introduce CRLF line endings.

   ```bash
   cd ~ && git clone https://github.com/wasif-danesh/wasifyai.git && cd wasifyai
   ```

3. Run the normal flow:

   ```bash
   make setup        # installs tools, Podman, Ollama, pulls the model, creates .env
   make dev          # starts the stack and applies migrations
   ```

4. Open http://localhost:3000 in your Windows browser. WSL2 forwards `localhost`.

Optional: `make setup-k8s`, then `make kind-up` for the local Kubernetes cluster. Rootless
Podman needs cgroup delegation for kind; see [runbooks/linux-kind.md](runbooks/linux-kind.md).

## Tips

- **Memory:** WSL2 uses up to half of your RAM by default. `gemma4:e4b` needs about 8 GB (16 GB is comfortable); raise
  the limit in `%UserProfile%\.wslconfig` (`[wsl2]` then `memory=20GB`) and run `wsl --shutdown`.
- **Docker Desktop instead of Podman:** `CONTAINER_ENGINE=docker make dev` works, because the
  repo uses the standard Compose spec. Enable WSL integration for your distro in Docker Desktop.
- **Ollama on Windows instead of WSL:** not needed. Install it inside WSL so containers reach it
  the same way as on Linux. If it listens on loopback only, `make setup` offers to fix that.
- **Line endings:** `.gitattributes` forces LF for scripts, Makefiles and Containerfiles, so a
  checkout made by Windows Git still works. Prefer cloning inside WSL anyway.
