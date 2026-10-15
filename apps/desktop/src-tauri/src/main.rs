// SPDX-License-Identifier: AGPL-3.0-only
//! The wasifyai desktop shell: one window, one engine process, one instance.
//!
//! The shell starts the engine in the desktop profile (ADR-0056), tells the window where it is and
//! gives it a short-lived token. Everything else (the image product, its storage, its queue) is the
//! engine's, so the shell stays small.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod disk;
mod download;
mod engine;
mod logsink;
#[allow(dead_code)]
mod loopback_http;
mod manifest;
mod provision;
mod session;
mod updater;
mod windows_job;

use engine::{Engine, Session, Status};
use tauri::{Manager, RunEvent, State};

#[tauri::command]
fn engine_status(engine: State<'_, Engine>) -> Status {
    engine.status()
}

#[tauri::command]
fn engine_session(engine: State<'_, Engine>) -> Result<Session, String> {
    engine.session()
}

#[tauri::command]
fn engine_restart(engine: State<'_, Engine>) {
    engine.restart();
}

#[tauri::command]
async fn update_check(app: tauri::AppHandle) -> updater::UpdateStatus {
    updater::check(&app).await
}

#[tauri::command]
async fn update_install(app: tauri::AppHandle) -> Result<(), String> {
    updater::install(&app).await
}

#[tauri::command]
fn engine_repair(engine: State<'_, Engine>) {
    engine.repair();
}

/// True when the shell was started to test itself (`WASIFYAI_SMOKE=1`): the window then drives its
/// own create screen and calls `smoke_report`. Used by `cargo run` in CI and by hand.
fn smoke_requested() -> bool {
    std::env::var("WASIFYAI_SMOKE")
        .map(|v| v == "1")
        .unwrap_or(false)
}

#[tauri::command]
fn smoke_enabled() -> bool {
    smoke_requested()
}

/// The self-test's verdict: print it and quit with 0 (passed) or 1. Does nothing in a normal run.
#[tauri::command]
fn smoke_report(app: tauri::AppHandle, ok: bool, detail: String) {
    if !smoke_requested() {
        return;
    }
    println!("SMOKE {} {}", if ok { "PASS" } else { "FAIL" }, detail);
    app.exit(if ok { 0 } else { 1 });
}

fn show_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

/// A termination request (a shutdown, `kill`, Ctrl+C in a terminal) quits through the same path as
/// the Quit menu, so the engine is stopped in order rather than found gone.
fn quit_on_signals(app: tauri::AppHandle) {
    #[cfg(unix)]
    tauri::async_runtime::spawn(async move {
        use tokio::signal::unix::{signal, SignalKind};
        let (Ok(mut term), Ok(mut int)) = (
            signal(SignalKind::terminate()),
            signal(SignalKind::interrupt()),
        ) else {
            return;
        };
        tokio::select! {
            _ = term.recv() => {}
            _ = int.recv() => {}
        }
        app.exit(0);
    });
    #[cfg(not(unix))]
    let _ = app;
}

fn main() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();
    windows_job::initialize();

    let engine = Engine::new();
    let mut builder = tauri::Builder::default()
        // a second launch brings the first window forward instead of starting another engine
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            show_main_window(app);
        }))
        .manage(engine.clone())
        .invoke_handler(tauri::generate_handler![
            engine_status,
            engine_session,
            engine_restart,
            engine_repair,
            update_check,
            update_install,
            smoke_enabled,
            smoke_report
        ])
        .setup(move |app| {
            // WASIFYAI_DATA_DIR: a different app data folder, for tests and for trying the installer
            // without touching the real one.
            let data_dir = match std::env::var_os("WASIFYAI_DATA_DIR") {
                Some(d) => std::path::PathBuf::from(d),
                None => app.path().app_data_dir()?,
            };
            std::fs::create_dir_all(&data_dir)?;
            engine.start(
                app.handle().clone(),
                engine::Input {
                    data_dir,
                    resource_dir: app.path().resource_dir().ok(),
                },
            );
            quit_on_signals(app.handle().clone());
            Ok(())
        });
    // Only a build with a signing key and a feed registers the updater (see updater.rs).
    if updater::configured().is_some() {
        builder = builder.plugin(tauri_plugin_updater::Builder::new().build());
    }
    let app = builder
        .build(tauri::generate_context!())
        .expect("failed to build the wasifyai desktop app");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            // Quitting must not leave the engine behind.
            let engine = handle.state::<Engine>();
            tauri::async_runtime::block_on(engine.stop());
        }
    });
}
