// SPDX-License-Identifier: AGPL-3.0-only
//! The wasifyai desktop shell: one window, one engine process, one instance.
//!
//! The shell starts the engine in the desktop profile (ADR-0056), tells the window where it is and
//! gives it a short-lived token. Everything else (the image product, its storage, its queue) is the
//! engine's, so the shell stays small.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod comfyui;
mod disk;
mod download;
mod engine;
mod llamacpp;
mod logsink;
#[allow(dead_code)]
mod loopback_http;
mod manifest;
mod memory;
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

/// Whether this is an address the window may hand to the system browser: an ordinary web address,
/// one word with no spaces or control characters (so it is one argument and nothing else).
fn web_address_ok(url: &str) -> bool {
    (url.starts_with("https://") || url.starts_with("http://"))
        && url.len() <= 2000
        && !url.chars().any(|c| c.is_control() || c.is_whitespace())
}

/// Open a web address in the person's own browser. The window's links (a source under an answer, a
/// key's page in Settings) go here because the window itself does not open new windows. Only http
/// and https, and the address is passed as one argument, never through a shell.
#[tauri::command]
fn open_external(url: String) -> Result<(), String> {
    if !web_address_ok(&url) {
        return Err("only web addresses can be opened".into());
    }
    #[cfg(target_os = "macos")]
    let mut command = std::process::Command::new("open");
    #[cfg(target_os = "windows")]
    let mut command = {
        let mut c = std::process::Command::new("rundll32");
        c.arg("url.dll,FileProtocolHandler");
        c
    };
    #[cfg(all(unix, not(target_os = "macos")))]
    let mut command = std::process::Command::new("xdg-open");
    command
        .arg(&url)
        .spawn()
        .map(|_| ())
        .map_err(|e| format!("the browser could not be opened: {e}"))
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
fn component_status(
    id: String,
    comfy: State<'_, comfyui::Components>,
    llama: State<'_, llamacpp::Components>,
) -> Result<comfyui::ComponentStatus, String> {
    match id.as_str() {
        comfyui::COMPONENT => Ok(comfy.status()),
        llamacpp::COMPONENT => Ok(llama.status()),
        _ => Err(format!("unknown component {id}")),
    }
}

#[tauri::command]
fn component_install(
    id: String,
    repair: bool,
    app: tauri::AppHandle,
    comfy: State<'_, comfyui::Components>,
    llama: State<'_, llamacpp::Components>,
) -> Result<(), String> {
    match id.as_str() {
        comfyui::COMPONENT => comfy.start(app, repair),
        llamacpp::COMPONENT => llama.start(app, repair),
        _ => Err(format!("unknown component {id}")),
    }
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

/// With the self-test on, the optional component it should set up instead of making an image.
#[tauri::command]
fn smoke_component() -> Option<String> {
    if !smoke_requested() {
        return None;
    }
    std::env::var("WASIFYAI_SMOKE_COMPONENT")
        .ok()
        .filter(|c| !c.is_empty())
}

/// The self-test's verdict: print it and quit with 0 (passed) or 1. Does nothing in a normal run.
#[tauri::command]
fn smoke_report(app: tauri::AppHandle, engine: State<'_, Engine>, ok: bool, detail: String) {
    if !smoke_requested() {
        return;
    }
    let mut lines = vec![format!(
        "SMOKE {} {}",
        if ok { "PASS" } else { "FAIL" },
        detail
    )];
    // timings and memory of this run, one JSON line, for the evidence documents (see memory.rs)
    if let Ok(json) = serde_json::to_string(&engine.measurements()) {
        lines.push(format!("SMOKE_METRICS {json}"));
    }
    for l in &lines {
        println!("{l}");
    }
    // A release build on Windows has no console, so the lines also go to a file when asked
    // (WASIFYAI_SMOKE_OUT), which is how CI reads the packaged app's verdict.
    if let Some(path) = std::env::var_os("WASIFYAI_SMOKE_OUT") {
        use std::io::Write;
        if let Ok(mut f) = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(path)
        {
            for l in &lines {
                let _ = writeln!(f, "{l}");
            }
        }
    }
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
            open_external,
            engine_repair,
            component_status,
            component_install,
            update_check,
            update_install,
            smoke_enabled,
            smoke_component,
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
            let input = engine::Input {
                data_dir,
                resource_dir: app.path().resource_dir().ok(),
            };
            app.manage(comfyui::Components::new(input.clone()));
            app.manage(llamacpp::Components::new(input.clone()));
            engine.start(app.handle().clone(), input);
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

#[cfg(test)]
mod tests {
    use super::web_address_ok;

    #[test]
    fn only_ordinary_web_addresses_are_opened() {
        assert!(web_address_ok("https://example.com/a?b=c#d"));
        assert!(web_address_ok("http://example.com"));
        for bad in [
            "",
            "file:///etc/passwd",
            "javascript:alert(1)",
            "ftp://example.com",
            "https://exa mple.com",
            "https://example.com\nopen -a Calculator",
            "-a Calculator",
            "https:",
        ] {
            assert!(!web_address_ok(bad), "{bad:?}");
        }
        assert!(!web_address_ok(&format!("https://example.com/{}", "a".repeat(2000))));
    }
}
