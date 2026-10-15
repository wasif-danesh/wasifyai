# wasifyai desktop

The Tauri 2 shell and the window of the wasifyai desktop app (ADR-0056). The shell is small on purpose:
it starts the engine (`services/api` in the desktop profile, see `docs/desktop-profile.md`), supervises it,
and gives the window a token. The product screens come from `packages/ui`: the window mounts the same image create screen as the web app, with a
transport that talks to the engine (`src/transport.ts`).

```
apps/desktop/
├─ src/                 the window (Vite + React): the shared create screen, or the engine's state
│                       transport.ts (loopback + token), smoke.ts (the self-test)
├─ src-tauri/           the shell (Rust)
│  └─ src/              engine.rs (supervision), session.rs (the window's token), main.rs
│                       windows_job.rs, loopback_http.rs: imported, see PROVENANCE.md
└─ LICENSE-AGPL
```

## Licence

This folder is **AGPL-3.0-only**, because it contains code imported from Unsloth Studio (AGPL-3.0). The rest of
the repository is Apache-2.0 (see the root `LICENSE` and `NOTICE`). Do not copy code from here into the
Apache-2.0 packages without a decision about the licence boundary.

## Commands

```
pnpm --filter @wasifyai/desktop dev       # the window on http://localhost:1420
pnpm --filter @wasifyai/desktop build     # type-check and build apps/desktop/dist
cd src-tauri && cargo run                 # shell + engine (builds with the embedded dist)
cd src-tauri && cargo test
pnpm --filter @wasifyai/desktop test      # the transport
cd src-tauri && WASIFYAI_SMOKE=1 cargo run   # the self-test: make an image in the real window, exit 0 or 1
```

The engine's Python is taken from `WASIFYAI_ENGINE_PYTHON`, then `<app data>/engine/venv`, then the
checkout's `.venv`. Logs: `<app data>/logs/engine.log` (macOS: `~/Library/Application Support/ai.wasifyai.desktop`).

## Not yet

Signing and notarisation, the updater, the installer/provisioner, tray and deep links. The bundle identifier
`ai.wasifyai.desktop` and the icons are placeholders.
