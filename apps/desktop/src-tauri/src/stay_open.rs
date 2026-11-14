// SPDX-License-Identifier: AGPL-3.0-only
//! "Open Wasify AI when I log in, and keep it in the menu bar" (ADR-0105, decision 12).
//!
//! Scheduled coding runs happen only while the app is open. This is the one switch that keeps it
//! open without a window in the way:
//!
//! - **at login** the app is started by a launch agent of the person's own
//!   (`~/Library/LaunchAgents/ai.wasifyai.desktop.login.plist`), with `--hidden`, so no window
//!   comes up;
//! - **in the menu bar** there is an item with "Open Wasify AI" and "Quit Wasify AI";
//! - **closing the window** hides it and the app goes on, with its engine and its timer. Quit, from
//!   the menu bar item or the app's own menu, ends it as before.
//!
//! Whether the switch is on is the launch agent's file being there: nothing else keeps it. The
//! file is plain text the person can read and remove. macOS only; elsewhere the switch is not
//! offered.

use serde::Serialize;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
#[cfg(target_os = "macos")]
use tauri::menu::{Menu, MenuItem};
#[cfg(target_os = "macos")]
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Manager, State};

pub const AGENT_FILE: &str = "ai.wasifyai.desktop.login.plist";
pub const HIDDEN_ARG: &str = "--hidden";
#[cfg(target_os = "macos")]
const TRAY: &str = "wasify-stay-open";

/// Whether the app stays open when its window is closed. Read by the run loop.
#[derive(Default)]
pub struct StayOpen(AtomicBool);

impl StayOpen {
    pub fn is_on(&self) -> bool {
        self.0.load(Ordering::Relaxed)
    }
    fn put(&self, on: bool) {
        self.0.store(on, Ordering::Relaxed);
    }
}

#[derive(Serialize)]
pub struct Stays {
    /// false where there is no such thing (not a Mac)
    pub supported: bool,
    pub on: bool,
}

/// The folder of the person's launch agents. `WASIFYAI_LOGIN_DIR` names another one, for tests and
/// for trying the switch without touching the real folder.
pub fn agents_dir() -> Option<PathBuf> {
    if !cfg!(target_os = "macos") {
        return None;
    }
    if let Some(dir) = std::env::var_os("WASIFYAI_LOGIN_DIR") {
        return Some(PathBuf::from(dir));
    }
    std::env::var_os("HOME").map(|home| PathBuf::from(home).join("Library").join("LaunchAgents"))
}

fn escaped(text: &str) -> String {
    text.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}

/// The launch agent: start this program once at login, hidden. Nothing else: it is not kept alive
/// and not started again when it ends.
pub fn agent_text(program: &Path) -> String {
    format!(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n\
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n\
<plist version=\"1.0\">\n<dict>\n\
\t<key>Label</key>\n\t<string>ai.wasifyai.desktop.login</string>\n\
\t<key>ProgramArguments</key>\n\t<array>\n\t\t<string>{}</string>\n\t\t<string>{HIDDEN_ARG}</string>\n\t</array>\n\
\t<key>RunAtLoad</key>\n\t<true/>\n\
\t<key>ProcessType</key>\n\t<string>Interactive</string>\n\
</dict>\n</plist>\n",
        escaped(&program.to_string_lossy())
    )
}

pub fn is_on(dir: &Path) -> bool {
    dir.join(AGENT_FILE).is_file()
}

/// Write the launch agent, or remove it. Only this one file is ever touched.
pub fn set(dir: &Path, program: &Path, on: bool) -> std::io::Result<()> {
    let file = dir.join(AGENT_FILE);
    if !on {
        return match std::fs::remove_file(&file) {
            Err(e) if e.kind() != std::io::ErrorKind::NotFound => Err(e),
            _ => Ok(()),
        };
    }
    if !program.is_absolute() {
        return Err(std::io::Error::other("the app's own place is not known"));
    }
    std::fs::create_dir_all(dir)?;
    let part = dir.join(format!("{AGENT_FILE}.part"));
    std::fs::write(&part, agent_text(program))?;
    std::fs::rename(&part, &file)
}

/// Whether this start was the launch agent's: no window comes up.
pub fn started_hidden() -> bool {
    std::env::args().any(|a| a == HIDDEN_ARG)
}

#[cfg(target_os = "macos")]
fn show(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

#[cfg(not(target_os = "macos"))]
fn menu_bar_item(_app: &AppHandle, _on: bool) -> tauri::Result<()> {
    Ok(()) // never reached: the switch is not offered here
}

#[cfg(target_os = "macos")]
fn menu_bar_item(app: &AppHandle, on: bool) -> tauri::Result<()> {
    if !on {
        let _ = app.remove_tray_by_id(TRAY);
        return Ok(());
    }
    if app.tray_by_id(TRAY).is_some() {
        return Ok(());
    }
    let open = MenuItem::with_id(app, "open", "Open Wasify AI", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit Wasify AI", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open, &quit])?;
    let mut tray = TrayIconBuilder::with_id(TRAY)
        .tooltip("Wasify AI is open, for its scheduled runs")
        .menu(&menu)
        .show_menu_on_left_click(true)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "open" => show(app),
            "quit" => app.exit(0),
            _ => {}
        });
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }
    tray.build(app).map(|_| ())
}

/// At start: if the switch is on, the menu bar item is there, and a start by the launch agent
/// shows no window.
pub fn begin(app: &AppHandle) {
    let on = agents_dir().is_some_and(|dir| is_on(&dir));
    app.state::<StayOpen>().put(on);
    if !on {
        return;
    }
    if let Err(e) = menu_bar_item(app, true) {
        log::warn!("the menu bar item could not be made: {e}");
        app.state::<StayOpen>().put(false); // without it a hidden app could not be opened or quit
        return;
    }
    if started_hidden() {
        if let Some(window) = app.get_webview_window("main") {
            let _ = window.hide();
        }
    }
}

#[tauri::command]
pub fn stay_open_get(stays: State<'_, StayOpen>) -> Stays {
    Stays {
        supported: agents_dir().is_some(),
        on: stays.is_on(),
    }
}

/// Not `async`: it runs on the main thread, where a menu bar item must be made.
#[tauri::command]
pub fn stay_open_set(
    app: AppHandle,
    stays: State<'_, StayOpen>,
    on: bool,
) -> Result<Stays, String> {
    let dir = agents_dir().ok_or("this is offered on a Mac only")?;
    let program = std::env::current_exe().map_err(|e| e.to_string())?;
    // the menu bar item first: the window may only be hidden when there is a way back to it
    menu_bar_item(&app, on).map_err(|e| format!("the menu bar item could not be made: {e}"))?;
    if let Err(e) = set(&dir, &program, on) {
        if on {
            let _ = menu_bar_item(&app, false);
        }
        return Err(format!("the login item could not be changed: {e}"));
    }
    stays.put(on);
    Ok(Stays {
        supported: true,
        on,
    })
}

/// The shell testing the switch in the real app (`WASIFYAI_STAY_TEST=1` with `WASIFYAI_LOGIN_DIR`
/// naming a throwaway folder; it refuses to run against the real folder): on, the window closed
/// and the app still there, the window back, off. Prints one line and quits.
#[cfg(not(target_os = "macos"))]
pub fn self_test(_app: AppHandle) {}

/// (See above.)
#[cfg(target_os = "macos")]
pub fn self_test(app: AppHandle) {
    let which = std::env::var("WASIFYAI_STAY_TEST").unwrap_or_default();
    if which == "login" {
        // a start as the launch agent makes it (the switch on, `--hidden`): no window, and the
        // menu bar item to open it or quit
        tauri::async_runtime::spawn(async move {
            tokio::time::sleep(std::time::Duration::from_millis(2500)).await;
            let shown = app
                .get_webview_window("main")
                .and_then(|w| w.is_visible().ok())
                .unwrap_or(true);
            let ok = !shown && app.tray_by_id(TRAY).is_some() && app.state::<StayOpen>().is_on();
            println!(
                "STAY_TEST {} a start at login: window shown={shown}, menu bar item={}",
                if ok { "PASS" } else { "FAIL" },
                app.tray_by_id(TRAY).is_some()
            );
            app.exit(if ok { 0 } else { 1 });
        });
        return;
    }
    if which != "1" {
        return;
    }
    tauri::async_runtime::spawn(async move {
        let wait = |ms| tokio::time::sleep(std::time::Duration::from_millis(ms));
        wait(2500).await;
        let verdict = async {
            if std::env::var_os("WASIFYAI_LOGIN_DIR").is_none() {
                return Err("WASIFYAI_LOGIN_DIR must name a throwaway folder".to_string());
            }
            let dir = agents_dir().ok_or("not a Mac")?;
            let window = app.get_webview_window("main").ok_or("no window")?;
            // the switch is flipped where the window's own call flips it: on the main thread
            let flip = |on: bool| {
                let (tx, rx) = tokio::sync::oneshot::channel();
                let app2 = app.clone();
                let sent = app.run_on_main_thread(move || {
                    let _ = tx.send(stay_open_set(app2.clone(), app2.state::<StayOpen>(), on));
                });
                async move {
                    sent.map_err(|e| e.to_string())?;
                    rx.await.map_err(|e| e.to_string())?
                }
            };
            let on = flip(true).await?;
            if !(on.on && is_on(&dir) && app.tray_by_id(TRAY).is_some()) {
                return Err("switched on, but the file or the menu bar item is missing".to_string());
            }
            window.close().map_err(|e| e.to_string())?; // as the red button does
            wait(1500).await;
            let hidden = !window.is_visible().map_err(|e| e.to_string())?;
            if !hidden {
                return Err("the window was closed and is still shown".to_string());
            }
            show(&app); // "Open Wasify AI" in the menu bar item
            wait(800).await;
            if !window.is_visible().map_err(|e| e.to_string())? {
                return Err("the window did not come back".to_string());
            }
            let off = flip(false).await?;
            if off.on || is_on(&dir) || app.tray_by_id(TRAY).is_some() {
                return Err("switched off, but something of it is left".to_string());
            }
            Ok::<String, String>(
                "on: the file and the menu bar item; closed: hidden and alive; opened again; off: both gone"
                    .to_string(),
            )
        }
        .await;
        match &verdict {
            Ok(detail) => println!("STAY_TEST PASS {detail}"),
            Err(why) => println!("STAY_TEST FAIL {why}"),
        }
        app.exit(if verdict.is_ok() { 0 } else { 1 });
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    fn folder(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("wasify-stay-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        dir
    }

    #[test]
    fn the_switch_is_one_file_written_and_removed() {
        let dir = folder("switch");
        let program = Path::new("/Applications/Wasify AI.app/Contents/MacOS/wasifyai-desktop");
        assert!(!is_on(&dir));
        set(&dir, program, true).unwrap();
        assert!(is_on(&dir));
        let text = std::fs::read_to_string(dir.join(AGENT_FILE)).unwrap();
        assert!(text.contains(
            "<string>/Applications/Wasify AI.app/Contents/MacOS/wasifyai-desktop</string>"
        ));
        assert!(
            text.contains("<string>--hidden</string>") && text.contains("<key>RunAtLoad</key>")
        );
        assert!(!text.contains("KeepAlive")); // started once at login, never kept alive
        std::fs::write(dir.join("someone-elses.plist"), "x").unwrap();
        set(&dir, program, true).unwrap(); // twice is the same
        set(&dir, program, false).unwrap();
        assert!(!is_on(&dir));
        set(&dir, program, false).unwrap(); // removing what is not there is not an error
        assert!(dir.join("someone-elses.plist").is_file()); // only our own file is touched
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn a_program_with_odd_letters_in_its_path_stays_one_value() {
        let text = agent_text(Path::new("/Users/a&b/<Apps>/Wasify AI"));
        assert!(text.contains("<string>/Users/a&amp;b/&lt;Apps&gt;/Wasify AI</string>"));
        assert_eq!(text.matches("<string>").count(), 4);
    }

    #[test]
    fn a_program_whose_place_is_not_known_is_refused() {
        let dir = folder("unknown");
        assert!(set(&dir, Path::new("wasifyai-desktop"), true).is_err());
        assert!(!is_on(&dir));
    }
}
