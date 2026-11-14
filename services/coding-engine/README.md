# The coding engine's pins

The coding agent runs on OpenHands' Agent Server (ADR-0101). The server is not part of the app: it is an
optional part, set up on request and run inside a sandbox by the Wasify engine (ADR-0102). This folder holds
what pins it. There is no package of ours here and none of OpenHands' source.

| File | What it is |
|---|---|
| `VERSION` | The one version pin. The four packages (`openhands-agent-server`, `openhands-sdk`, `openhands-tools`, `openhands-workspace`) are always taken at this version |
| `leave-out.txt` | Packages the four pull in that nothing we use imports. They are taken out of the lock |
| `requirements-aarch64-apple-darwin.lock` | Every package that is installed, with its version and hashes. Written by `scripts/lock-coding-engine.sh`; never edited by hand |
| `build-constraints.txt` | The one build tool, with its hash. One package of the lock (`func-timeout`) is published as source only and is built while installing; without this file uv would fetch the newest `setuptools`, unchecked |
| `engine.sb.template` | The macOS sandbox profile. The Wasify engine fills in four lists of folders at every start |

Where each is used:

- **Setting it up** is `services/api/src/wasifyai_api/components/coding.py`, on the one installer. The pins
  of the download (the lock's SHA-256, the extensions catalogue's address, size and SHA-256) are in
  `services/api/src/wasifyai_api/components/manifests/darwin-arm64.yaml`, under `coding`.
- **Running it** is `services/api/src/wasifyai_api/coding_server.py`.
- **A packaged app** gets a copy of this folder in its engine bundle (`scripts/build-engine-bundle.sh`), and
  the shell checks each file's SHA-256 before the engine runs.

## Moving the version

The version moves as its own piece of work, about monthly (ADR-0101, decision 9).

1. Change `VERSION`, and `version:` under `coding` in all five manifests.
2. Run `scripts/lock-coding-engine.sh`. It resolves the four packages for Python 3.12 on an Apple-silicon
   Mac, takes out what `leave-out.txt` names, and prints the new lock's SHA-256. Put that in `lock_sha256`
   in `manifests/darwin-arm64.yaml`. This fetches from PyPI: ask the owner first. If the lock gains another
   package without a prebuilt file, its build tool goes into `build-constraints.txt` with a hash, and the
   file's new SHA-256 into `build_constraints_sha256`.
3. Set the part up from the app (Settings, Optional parts), then run `make test-coding`. The server must
   start inside the sandbox on the trimmed list, and every hostile test must pass.
4. Measure the size on disk again and put it in `install_bytes`.

A package may be added to `leave-out.txt` only after the server and a real session were shown to work
without it. The lock is installed with `--no-deps`, so a package that is not listed is never fetched.

## The sandbox profile

The profile starts from "allow" and closes what the engine must not reach (ADR-0102, decision 3):

- **Writes:** only its own state (`<app data>/coding`), the workspaces, and its terminal folder.
- **Reads:** `/Users`, `/Volumes`, the per-user temp folders, `/tmp` and the app's own data folder are
  closed. Its own packages, its Python, its state and the workspaces are opened again inside them. The
  system and the tools (`/usr`, `/bin`, `/opt/homebrew`, Apple's developer tools) stay readable.
- **Network:** this computer only.
- **Other programs:** no signal to a process outside the sandbox, no app opened (`open`), no message to
  another app, no job handed to the system. Without these four rules a command could have a program
  outside the sandbox run a file for it.

The four lists (`{{WRITE}}`, `{{CLOSED}}`, `{{OPEN}}`, `{{WAY}}`) are filled in by `fill_profile` in
`coding_server.py`. A later rule decides over an earlier one, so the order of the blocks matters. Change the
profile only together with `services/api/tests/integration/test_coding_sandbox.py`, and run
`make test-coding` after any change. Measurements are in `docs/spikes/coding-c1a.md`.
