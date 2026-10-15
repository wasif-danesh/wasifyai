// SPDX-License-Identifier: AGPL-3.0-only
//! Supervision of the wasifyai engine process (ADR-0056).
//!
//! The shell starts `python -m wasifyai_api.desktop`, reads one JSON line from its stdout when the
//! engine is listening on its loopback port, checks `/health`, and keeps it running: a crash is
//! restarted with a backoff, up to a limit, then the window is told it has failed. The shell gives
//! the engine a per-launch secret (the window's token is signed with it) and keeps the engine's
//! stdin open: when the shell goes away, however it goes, the engine sees the pipe close and exits.
//!
//! The process-group and tree-kill handling follows the approach of Unsloth Studio's
//! `process.rs` (see PROVENANCE.md); the code is written for this engine.

use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{AppHandle, Emitter};
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::{Child, ChildStdin, Command};
use tokio::sync::Notify;

use crate::{loopback_http, session};

pub const STATUS_EVENT: &str = "engine://status";
const READY_EVENT: &str = "wasifyai.engine.ready";
const READY_TIMEOUT: Duration = Duration::from_secs(90);
const HEALTH_TRIES: u32 = 40;
const HEALTH_EVERY: Duration = Duration::from_millis(250);
const GRACE: Duration = Duration::from_secs(8);
const MAX_RESTARTS: usize = 5;
const RESTART_WINDOW: Duration = Duration::from_secs(60);
const LOG_ROTATE_BYTES: u64 = 5 * 1024 * 1024;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// What the window is told about the engine.
#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum Status {
    Starting { attempt: u32 },
    Ready { base_url: String, pid: u32 },
    Failed { message: String },
    Stopped,
}

#[derive(Clone, Debug, Serialize)]
pub struct Session {
    pub base_url: String,
    pub token: String,
    pub expires_at: u64,
}

/// Where and how to start the engine.
#[derive(Clone, Debug)]
pub struct LaunchConfig {
    pub python: PathBuf,
    pub cwd: PathBuf,
    pub products_dir: PathBuf,
    pub data_dir: PathBuf,
    pub image_engine: String,
}

struct Shared {
    status: Mutex<Status>,
    secret: String,
    stopping: AtomicBool,
    stop: Notify,
    restart: Notify,
    task: Mutex<Option<tauri::async_runtime::JoinHandle<()>>>,
}

#[derive(Clone)]
pub struct Engine {
    shared: Arc<Shared>,
}

impl Engine {
    pub fn new() -> Self {
        Engine {
            shared: Arc::new(Shared {
                status: Mutex::new(Status::Stopped),
                secret: new_secret(),
                stopping: AtomicBool::new(false),
                stop: Notify::new(),
                restart: Notify::new(),
                task: Mutex::new(None),
            }),
        }
    }

    pub fn status(&self) -> Status {
        self.shared.status.lock().unwrap().clone()
    }

    /// A fresh token for the window, when the engine is ready.
    pub fn session(&self) -> Result<Session, String> {
        match self.status() {
            Status::Ready { base_url, .. } => {
                let t = session::mint(&self.shared.secret);
                Ok(Session {
                    base_url,
                    token: t.value,
                    expires_at: t.expires_at,
                })
            }
            Status::Failed { message } => Err(message),
            _ => Err("the engine is not ready yet".into()),
        }
    }

    /// Start the supervisor on the app's async runtime.
    pub fn start(&self, app: AppHandle, data_dir: PathBuf) {
        let shared = self.shared.clone();
        let handle = tauri::async_runtime::spawn(async move {
            match resolve(&data_dir) {
                Ok(cfg) => supervise(app, shared, cfg).await,
                Err(message) => set_status(&app, &shared, Status::Failed { message }),
            }
        });
        *self.shared.task.lock().unwrap() = Some(handle);
    }

    /// Ask for a fresh start (the window's "restart engine" button).
    pub fn restart(&self) {
        self.shared.restart.notify_one();
    }

    /// Stop the engine and wait for it. Called when the app is quitting.
    pub async fn stop(&self) {
        self.shared.stopping.store(true, Ordering::SeqCst);
        self.shared.stop.notify_waiters();
        self.shared.stop.notify_one();
        let handle = self.shared.task.lock().unwrap().take();
        if let Some(h) = handle {
            let _ = tokio::time::timeout(GRACE + Duration::from_secs(8), h).await;
        }
    }
}

fn new_secret() -> String {
    let bytes: [u8; 32] = rand::random();
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn set_status(app: &AppHandle, shared: &Shared, status: Status) {
    *shared.status.lock().unwrap() = status.clone();
    let _ = app.emit(STATUS_EVENT, &status);
}

// ---- where the engine is ---------------------------------------------------------------------

/// The engine's Python, in order: an explicit path (development), the environment the provisioner
/// made under the app data folder, the repository's own `.venv` (a development checkout).
pub fn resolve(data_dir: &Path) -> Result<LaunchConfig, String> {
    let repo = std::env::var_os("WASIFYAI_REPO")
        .map(PathBuf::from)
        .or_else(|| {
            // apps/desktop/src-tauri -> the repository root, for a development build
            Path::new(env!("CARGO_MANIFEST_DIR"))
                .ancestors()
                .nth(3)
                .map(Path::to_path_buf)
        })
        .filter(|p| p.join("services/api").is_dir());

    let venv_python = |root: &Path| -> PathBuf {
        if cfg!(windows) {
            root.join("Scripts").join("python.exe")
        } else {
            root.join("bin").join("python")
        }
    };

    let python = if let Some(p) = std::env::var_os("WASIFYAI_ENGINE_PYTHON") {
        PathBuf::from(p)
    } else {
        let managed = venv_python(&data_dir.join("engine").join("venv"));
        if managed.is_file() {
            managed
        } else if let Some(r) = &repo {
            venv_python(&r.join(".venv"))
        } else {
            managed
        }
    };
    if !python.is_file() {
        return Err(format!(
            "The engine is not installed ({} is missing). Run `make setup` in a development checkout, \
             or set WASIFYAI_ENGINE_PYTHON.",
            python.display()
        ));
    }

    let products_dir = std::env::var_os("WASIFYAI_PRODUCTS_DIR")
        .map(PathBuf::from)
        .or_else(|| repo.as_ref().map(|r| r.join("products")))
        .unwrap_or_else(|| data_dir.join("engine").join("products"));
    // The data folder, never the checkout: the engine's settings reader would pick up a development
    // `.env` (database URLs, keys) from its working directory.
    let cwd = data_dir.to_path_buf();
    Ok(LaunchConfig {
        python,
        cwd,
        products_dir,
        data_dir: data_dir.to_path_buf(),
        image_engine: std::env::var("WASIFYAI_IMAGE_ENGINE").unwrap_or_else(|_| "stub".into()),
    })
}

// ---- the engine's own log --------------------------------------------------------------------

#[derive(Clone)]
struct LogSink(Arc<Mutex<Option<std::fs::File>>>);

impl LogSink {
    fn open(data_dir: &Path) -> LogSink {
        let dir = data_dir.join("logs");
        let _ = std::fs::create_dir_all(&dir);
        let path = dir.join("engine.log");
        if std::fs::metadata(&path).map(|m| m.len()).unwrap_or(0) > LOG_ROTATE_BYTES {
            let _ = std::fs::rename(&path, dir.join("engine.log.1"));
        }
        let file = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(path)
            .ok();
        LogSink(Arc::new(Mutex::new(file)))
    }

    fn line(&self, source: &str, text: &str) {
        log::debug!("[engine {source}] {text}");
        if let Some(f) = self.0.lock().unwrap().as_mut() {
            let _ = writeln!(f, "[{source}] {text}");
        }
    }
}

// ---- the supervisor --------------------------------------------------------------------------

enum Outcome {
    /// The shell asked it to stop.
    Stopped,
    /// The window asked for a fresh start.
    Restart,
    /// It exited or never became ready.
    Failed(String),
}

async fn supervise(app: AppHandle, shared: Arc<Shared>, cfg: LaunchConfig) {
    let sink = LogSink::open(&cfg.data_dir);
    let mut recent: Vec<Instant> = Vec::new();
    let mut attempt = 0u32;
    loop {
        if shared.stopping.load(Ordering::SeqCst) {
            break;
        }
        attempt += 1;
        set_status(&app, &shared, Status::Starting { attempt });
        match run_once(&app, &shared, &cfg, &sink).await {
            Outcome::Stopped => break,
            Outcome::Restart => {
                recent.clear();
                attempt = 0;
            }
            Outcome::Failed(message) => {
                sink.line("shell", &format!("engine failed: {message}"));
                let now = Instant::now();
                recent.retain(|t| now.duration_since(*t) < RESTART_WINDOW);
                recent.push(now);
                if recent.len() > MAX_RESTARTS {
                    set_status(&app, &shared, Status::Failed { message });
                    // wait for the person to ask again, or for the app to quit
                    tokio::select! {
                        _ = shared.stop.notified() => break,
                        _ = shared.restart.notified() => {
                            recent.clear();
                            attempt = 0;
                        }
                    }
                } else {
                    let wait = Duration::from_secs(1u64 << recent.len().min(4));
                    tokio::select! {
                        _ = shared.stop.notified() => break,
                        _ = tokio::time::sleep(wait) => {}
                    }
                }
            }
        }
    }
    sink.line("shell", "engine stopped");
    set_status(&app, &shared, Status::Stopped);
}

async fn run_once(
    app: &AppHandle,
    shared: &Arc<Shared>,
    cfg: &LaunchConfig,
    sink: &LogSink,
) -> Outcome {
    let mut cmd = Command::new(&cfg.python);
    cmd.args(["-m", "wasifyai_api.desktop"])
        .current_dir(&cfg.cwd)
        .env("DEPLOYMENT_PROFILE", "desktop")
        .env("DESKTOP_DATA_DIR", &cfg.data_dir)
        .env("DESKTOP_IMAGE_ENGINE", &cfg.image_engine)
        .env("API_AUTH_SECRET", &shared.secret)
        .env("AUTH_MODE", "jwt")
        .env("PRODUCTS_DIR", &cfg.products_dir)
        .env("WASIFYAI_PORT", "0")
        .env("WASIFYAI_EXIT_ON_STDIN_EOF", "1")
        .env("PYTHONUNBUFFERED", "1")
        .env("PYTHONUTF8", "1")
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .kill_on_drop(true);
    #[cfg(unix)]
    cmd.process_group(0); // its own group, so the whole tree can be signalled
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);

    let mut child = match cmd.spawn() {
        Ok(c) => c,
        Err(e) => return Outcome::Failed(format!("could not start the engine: {e}")),
    };
    let pid = child.id().unwrap_or(0);
    let stdin = child.stdin.take();
    let stdout = child.stdout.take().expect("stdout is piped");
    let stderr = child.stderr.take().expect("stderr is piped");

    let err_sink = sink.clone();
    tauri::async_runtime::spawn(async move {
        let mut lines = BufReader::new(stderr).lines();
        while let Ok(Some(l)) = lines.next_line().await {
            err_sink.line("stderr", &l);
        }
    });

    // The ready line: one JSON object when the engine is listening.
    let mut lines = BufReader::new(stdout).lines();
    let ready = tokio::time::timeout(READY_TIMEOUT, async {
        loop {
            match lines.next_line().await {
                Ok(Some(l)) => match parse_ready(&l) {
                    Some(r) => return Ok(r),
                    None => sink.line("stdout", &l),
                },
                Ok(None) => return Err("the engine exited before it was ready".to_string()),
                Err(e) => return Err(format!("could not read the engine's output: {e}")),
            }
        }
    })
    .await;
    let port = match ready {
        Ok(Ok((port, _pid))) => port,
        Ok(Err(message)) => {
            stop_child(&mut child, stdin).await;
            return Outcome::Failed(message);
        }
        Err(_) => {
            stop_child(&mut child, stdin).await;
            return Outcome::Failed("the engine did not become ready in time".into());
        }
    };
    let out_sink = sink.clone();
    tauri::async_runtime::spawn(async move {
        while let Ok(Some(l)) = lines.next_line().await {
            out_sink.line("stdout", &l);
        }
    });

    let base_url = format!("http://127.0.0.1:{port}");
    if !healthy(&base_url).await {
        stop_child(&mut child, stdin).await;
        return Outcome::Failed("the engine did not answer its health check".into());
    }
    // The handoff worked only if the engine accepts a token signed with the secret we gave it.
    if let Err(message) = session_accepted(&base_url, &shared.secret).await {
        stop_child(&mut child, stdin).await;
        return Outcome::Failed(message);
    }
    set_status(app, shared, Status::Ready { base_url, pid });
    sink.line("shell", &format!("engine ready on port {port} (pid {pid})"));

    tokio::select! {
        status = child.wait() => {
            let how = match status {
                Ok(s) => format!("the engine exited ({s})"),
                Err(e) => format!("lost the engine: {e}"),
            };
            Outcome::Failed(how)
        }
        _ = shared.stop.notified() => {
            stop_child(&mut child, stdin).await;
            Outcome::Stopped
        }
        _ = shared.restart.notified() => {
            stop_child(&mut child, stdin).await;
            Outcome::Restart
        }
    }
}

fn parse_ready(line: &str) -> Option<(u16, u32)> {
    let v: serde_json::Value = serde_json::from_str(line.trim()).ok()?;
    if v.get("event")?.as_str()? != READY_EVENT {
        return None;
    }
    let port = u16::try_from(v.get("port")?.as_u64()?).ok()?;
    let pid = u32::try_from(v.get("pid")?.as_u64()?).ok()?;
    Some((port, pid))
}

async fn healthy(base_url: &str) -> bool {
    let Ok(client) = loopback_http::client(Duration::from_secs(2)) else {
        return false;
    };
    for _ in 0..HEALTH_TRIES {
        if let Ok(r) = client.get(format!("{base_url}/health")).send().await {
            if r.status().is_success() {
                return true;
            }
        }
        tokio::time::sleep(HEALTH_EVERY).await;
    }
    false
}

/// Ask who we are with a fresh token: 200 means the engine and the shell agree on the secret.
async fn session_accepted(base_url: &str, secret: &str) -> Result<(), String> {
    let client = loopback_http::client(Duration::from_secs(5))
        .map_err(|e| format!("could not make an HTTP client: {e}"))?;
    let token = session::mint(secret);
    let response = client
        .get(format!("{base_url}/me"))
        .bearer_auth(token.value)
        .send()
        .await
        .map_err(|e| format!("the engine did not answer: {e}"))?;
    if response.status().is_success() {
        Ok(())
    } else {
        Err(format!(
            "the engine rejected the shell's token (HTTP {})",
            response.status().as_u16()
        ))
    }
}

// ---- stopping --------------------------------------------------------------------------------

/// Close its stdin (the engine exits when it sees that), wait a grace period, then end the tree.
async fn stop_child(child: &mut Child, stdin: Option<ChildStdin>) {
    drop(stdin);
    if tokio::time::timeout(GRACE, child.wait()).await.is_ok() {
        return;
    }
    if let Some(pid) = child.id() {
        end_tree(pid, false);
        if tokio::time::timeout(Duration::from_secs(3), child.wait())
            .await
            .is_ok()
        {
            return;
        }
        end_tree(pid, true);
    }
    let _ = child.kill().await;
    let _ = child.wait().await;
}

#[cfg(unix)]
fn end_tree(pid: u32, force: bool) {
    let signal = if force { libc::SIGKILL } else { libc::SIGTERM };
    // the engine leads its own process group (`process_group(0)`)
    unsafe {
        libc::killpg(pid as libc::pid_t, signal);
    }
}

#[cfg(windows)]
fn end_tree(pid: u32, _force: bool) {
    use std::os::windows::process::CommandExt;
    let _ = std::process::Command::new("taskkill.exe")
        .creation_flags(CREATE_NO_WINDOW)
        .args(["/PID", &pid.to_string(), "/T", "/F"])
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_ready_line_is_recognised() {
        let line = r#"{"event": "wasifyai.engine.ready", "port": 49152, "pid": 4242}"#;
        assert_eq!(parse_ready(line), Some((49152, 4242)));
        assert_eq!(parse_ready(&format!("  {line}\n")), Some((49152, 4242)));
    }

    #[test]
    fn other_output_is_not_a_ready_line() {
        assert_eq!(parse_ready("INFO uvicorn started"), None);
        assert_eq!(parse_ready(r#"{"event": "other", "port": 1, "pid": 2}"#), None);
        assert_eq!(parse_ready(r#"{"event": "wasifyai.engine.ready", "port": 70000, "pid": 2}"#), None);
    }

    #[test]
    fn a_secret_is_long_and_different_each_time() {
        let a = new_secret();
        let b = new_secret();
        assert_eq!(a.len(), 64);
        assert!(a.len() >= 32); // the engine requires at least 32 bytes
        assert_ne!(a, b);
    }

    #[test]
    fn status_serialises_for_the_window() {
        let s = serde_json::to_value(Status::Ready {
            base_url: "http://127.0.0.1:1".into(),
            pid: 7,
        })
        .unwrap();
        assert_eq!(s["state"], "ready");
        assert_eq!(s["base_url"], "http://127.0.0.1:1");
        assert_eq!(serde_json::to_value(Status::Stopped).unwrap()["state"], "stopped");
    }
}
