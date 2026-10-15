# Provenance of imported code

Source: Unsloth Studio, <https://github.com/unslothai/unsloth>, folder `studio/src-tauri`,
tag `v0.1.907-beta`, commit `133a8076d10aa109f812f85a953636b3488926f6`. Licence: AGPL-3.0
(`studio/LICENSE.AGPL-3.0`, kept here as `apps/desktop/LICENSE-AGPL`). Imported on 2026-10-15
(ADR-0061: reference clone and selective import, not a repository move).

## Imported files

| File here | Source file | Changes |
|---|---|---|
| `windows_job.rs` | `src/windows_job.rs` | Header added. One doc comment reworded to drop Unsloth's install paths. Code unchanged. Windows only; not compiled or run by hand here, built by CI. |
| `loopback_http.rs` | `src/loopback_http.rs` | Header added. Doc comments and the redirect test no longer name Unsloth's `desktop-login` route (the test posts to `/session`). Test environment variable renamed `WASIFYAI_TEST_LOOPBACK_HTTP_CHILD`. Code unchanged. |

## Adapted, not copied

These were read and the approach was followed; the code is written for this engine.

| File here | Source | What was taken |
|---|---|---|
| `engine.rs` | `src/process.rs` (`ProcessGroup::leader()` spawn, `force_kill_process_tree`), `src/main.rs` | A process group on Unix and `taskkill /T /F` on Windows to end the whole tree; the app-wide job object (`windows_job`) as the crash-safe backstop. |
| `main.rs` | `src/main.rs` (`tauri_plugin_single_instance` setup, show-the-window callback) | The single-instance pattern. |
| `../tauri.conf.json` | `tauri.conf.json` | The shape of the security (CSP) and window sections. |
| `provision.rs`, `manifest.rs`, `download.rs` | `install.rs`, `install.sh`, `install_*_prebuilt.py` and the `*_prebuilt_pins.json` files (read only) | The approach: exact version pins with checksums kept in one manifest, an installer that reports named steps, and a repair that starts over. Unsloth drives shell and Python scripts and reads their stdout markers; this installer is Rust, uses uv and a hash-locked requirements file, and reports typed progress. |
| `updater.rs` | `desktop_updater.rs`, `main.rs` (the Tauri updater plugin set-up) | That the shell uses Tauri's updater plugin with a minisign key and a `latest.json` feed. Unsloth's staged-update and installer-handover logic is not taken. |

## Read and not imported

`process.rs` (6.7k lines), `desktop_backend_owner.rs`, `preflight*`, `install.rs`, `desktop_auth.rs`,
`update*.rs`, `staged_update.rs`, the `browser_*` modules, `native_*`, `diagnostics/`. They are built around
Unsloth's managed `unsloth` CLI, its home-directory and install-guard rules, its pid records and its
backend's login route, and the browser panel, none of which wasifyai has. Importing them would import those
assumptions. The installer and the updater skeleton above were written for wasifyai after reading them.
`staged_update.rs` (downloading an update while the app runs and applying it on the next start) may be worth
adapting when the updater is switched on; this file is updated when it is.
