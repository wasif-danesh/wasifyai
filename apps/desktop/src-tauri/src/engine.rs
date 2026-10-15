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

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{AppHandle, Emitter};
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::{Child, ChildStdin, Command};
use tokio::sync::Notify;

use crate::logsink::LogSink;
use crate::manifest::{host_target, Manifest};
use crate::memory;
use crate::provision::{self, Mode, Progress, ProvisionConfig};
use crate::{loopback_http, session};

pub const STATUS_EVENT: &str = "engine://status";
const READY_EVENT: &str = "wasifyai.engine.ready";
const READY_TIMEOUT: Duration = Duration::from_secs(90);
const HEALTH_TRIES: u32 = 40;
const HEALTH_EVERY: Duration = Duration::from_millis(250);
const GRACE: Duration = Duration::from_secs(8);
const MAX_RESTARTS: usize = 5;
const RESTART_WINDOW: Duration = Duration::from_secs(60);

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// What the window is told about the engine.
#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum Status {
    /// First run, or a repair: the engine's environment is being installed.
    Installing {
        progress: Progress,
    },
    Starting {
        attempt: u32,
    },
    Ready {
        base_url: String,
        pid: u32,
    },
    /// `step` is the install step that failed, when the failure was an install.
    Failed {
        message: String,
        step: Option<String>,
    },
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

/// What the shell noticed about this run, for the evidence documents and the self-test's report.
#[derive(Default)]
struct Measure {
    installed: bool,
    ready_ms: Option<u64>,
    engine_pid: Option<u32>,
    engine_rss_ready: Option<u64>,
}

/// The numbers `smoke_report` prints.
#[derive(Debug, Serialize)]
pub struct Measurements {
    /// the first run installed the engine before it started
    pub installed: bool,
    /// from the shell's start to the engine answering, install included
    pub ready_ms: Option<u64>,
    pub engine_rss_mb_at_ready: Option<u64>,
    pub engine_rss_mb_now: Option<u64>,
    pub shell_rss_mb: Option<u64>,
}

struct Shared {
    started: Instant,
    measure: Mutex<Measure>,
    status: Mutex<Status>,
    secret: String,
    stopping: AtomicBool,
    repair_requested: AtomicBool,
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
                started: Instant::now(),
                measure: Mutex::new(Measure::default()),
                status: Mutex::new(Status::Stopped),
                secret: new_secret(),
                stopping: AtomicBool::new(false),
                // WASIFYAI_REPAIR=1: rebuild the environment at start (support, tests)
                repair_requested: AtomicBool::new(env_flag("WASIFYAI_REPAIR")),
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
            Status::Failed { message, .. } => Err(message),
            _ => Err("the engine is not ready yet".into()),
        }
    }

    /// Start the supervisor on the app's async runtime.
    pub fn start(&self, app: AppHandle, input: Input) {
        let shared = self.shared.clone();
        let handle = tauri::async_runtime::spawn(supervise(app, shared, input));
        *self.shared.task.lock().unwrap() = Some(handle);
    }

    pub fn measurements(&self) -> Measurements {
        let m = self.shared.measure.lock().unwrap();
        let mb = |b: u64| b / 1_000_000;
        Measurements {
            installed: m.installed,
            ready_ms: m.ready_ms,
            engine_rss_mb_at_ready: m.engine_rss_ready.map(mb),
            engine_rss_mb_now: m.engine_pid.and_then(memory::rss_bytes).map(mb),
            shell_rss_mb: memory::rss_bytes(std::process::id()).map(mb),
        }
    }

    /// Ask for a fresh start (the window's "restart engine" button).
    pub fn restart(&self) {
        self.shared.restart.notify_one();
    }

    /// Rebuild the engine's environment and start it again (the window's "Repair" button).
    pub fn repair(&self) {
        self.shared.repair_requested.store(true, Ordering::SeqCst);
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
    match &status {
        Status::Installing { .. } => shared.measure.lock().unwrap().installed = true,
        Status::Ready { pid, .. } => {
            let pid = *pid;
            {
                let mut m = shared.measure.lock().unwrap();
                m.ready_ms = Some(shared.started.elapsed().as_millis() as u64);
                m.engine_pid = Some(pid);
            }
            // memory at the moment it became ready: the engine has done nothing yet
            let rss = memory::rss_bytes(pid);
            shared.measure.lock().unwrap().engine_rss_ready = rss;
        }
        _ => {}
    }
    *shared.status.lock().unwrap() = status.clone();
    let _ = app.emit(STATUS_EVENT, &status);
}

// ---- where the engine is ---------------------------------------------------------------------

/// What the shell knows when it starts.
#[derive(Clone, Debug)]
pub struct Input {
    pub data_dir: PathBuf,
    /// Where the app's bundled files are (the engine bundle sits in `engine-bundle` under it).
    pub resource_dir: Option<PathBuf>,
}

/// What to do before the engine can start.
enum Plan {
    /// There is an engine to run now.
    Use(LaunchConfig),
    /// Install it first (or again).
    Provision(ProvisionConfig, LaunchConfig),
}

fn venv_python_in(root: &Path) -> PathBuf {
    if cfg!(windows) {
        root.join("Scripts").join("python.exe")
    } else {
        root.join("bin").join("python")
    }
}

fn dev_repo() -> Option<PathBuf> {
    std::env::var_os("WASIFYAI_REPO")
        .map(PathBuf::from)
        .or_else(|| {
            // apps/desktop/src-tauri -> the repository root, for a development build
            Path::new(env!("CARGO_MANIFEST_DIR"))
                .ancestors()
                .nth(3)
                .map(Path::to_path_buf)
        })
        .filter(|p| p.join("services/api").is_dir())
}

fn env_flag(name: &str) -> bool {
    std::env::var(name).map(|v| v == "1").unwrap_or(false)
}

/// The engine's Python, in order:
///
/// 1. `WASIFYAI_ENGINE_PYTHON`, an explicit path (development, tests);
/// 2. with `WASIFYAI_PROVISION=1`: the managed environment, installed from the bundle;
/// 3. a development checkout's own `.venv`;
/// 4. the managed environment, installed from the bundle when it is missing or out of date: this is
///    what an installed app does on its first run.
fn plan(input: &Input, repair: bool) -> Result<Plan, String> {
    let data_dir = &input.data_dir;
    let repo = dev_repo();
    let cwd = data_dir.clone(); // never the checkout: its `.env` must not reach the engine
    let image_engine = std::env::var("WASIFYAI_IMAGE_ENGINE").unwrap_or_else(|_| "stub".into());
    let products_env = std::env::var_os("WASIFYAI_PRODUCTS_DIR").map(PathBuf::from);

    let launch = |python: PathBuf, products_dir: PathBuf| LaunchConfig {
        python,
        cwd: cwd.clone(),
        products_dir,
        data_dir: data_dir.clone(),
        image_engine: image_engine.clone(),
    };

    if let Some(p) = std::env::var_os("WASIFYAI_ENGINE_PYTHON") {
        let python = PathBuf::from(p);
        if !python.is_file() {
            return Err(format!(
                "WASIFYAI_ENGINE_PYTHON points at {}, which is not a file",
                python.display()
            ));
        }
        let products = products_env
            .or_else(|| repo.as_ref().map(|r| r.join("products")))
            .unwrap_or_else(|| data_dir.join("engine").join("products"));
        return Ok(Plan::Use(launch(python, products)));
    }

    let manifest = Manifest::load()?;
    let layout = provision::Layout::new(data_dir, &manifest);
    let managed_python = venv_python_in(&layout.venv_dir());

    let bundle_dir = std::env::var_os("WASIFYAI_ENGINE_BUNDLE")
        .map(PathBuf::from)
        .or_else(|| input.resource_dir.as_ref().map(|r| r.join("engine-bundle")))
        .filter(|p| p.join("bundle.json").is_file())
        .or_else(|| {
            repo.as_ref()
                .map(|r| r.join("apps/desktop/engine-bundle"))
                .filter(|p| p.join("bundle.json").is_file())
        });

    let dev_python = repo.as_ref().map(|r| venv_python_in(&r.join(".venv")));
    if !env_flag("WASIFYAI_PROVISION") {
        if let (Some(py), Some(r)) = (&dev_python, &repo) {
            if py.is_file() {
                let products = products_env.unwrap_or_else(|| r.join("products"));
                return Ok(Plan::Use(launch(py.clone(), products)));
            }
        }
    }

    let Some(bundle_dir) = bundle_dir else {
        return Err(
            "The engine is not installed and this app has no engine files to install it from. \
             In a development checkout run `make setup`; to try the installer run \
             scripts/build-engine-bundle.sh."
                .into(),
        );
    };
    let products = products_env.unwrap_or_else(|| bundle_dir.join("products"));
    let launch_cfg = launch(managed_python, products);
    let (_, bundle_sha) = provision::load_bundle(&bundle_dir)?;
    // a repair rebuilds even an environment that looks complete
    if !repair && provision::is_provisioned(&layout, &manifest, &bundle_sha) {
        return Ok(Plan::Use(launch_cfg));
    }
    host_target().ok_or_else(|| {
        format!(
            "This computer ({} {}) is not supported yet.",
            std::env::consts::OS,
            std::env::consts::ARCH
        )
    })?;
    Ok(Plan::Provision(
        ProvisionConfig {
            data_dir: data_dir.clone(),
            bundle_dir,
            manifest,
            allow_http: false,
        },
        launch_cfg,
    ))
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

/// Make sure there is an engine to start: use the one that is there, or install it (or repair it).
async fn prepare(
    app: &AppHandle,
    shared: &Arc<Shared>,
    input: &Input,
    sink: &LogSink,
) -> Result<LaunchConfig, (String, Option<String>)> {
    let repair = shared.repair_requested.swap(false, Ordering::SeqCst);
    let (pcfg, launch) = match plan(input, repair) {
        Ok(Plan::Use(cfg)) => {
            if repair {
                sink.line(
                    "shell",
                    "repair asked for, but this engine is not managed by the app",
                );
            }
            return Ok(cfg);
        }
        Ok(Plan::Provision(p, l)) => (p, l),
        Err(message) => return Err((message, None)),
    };
    let mode = if repair { Mode::Repair } else { Mode::Install };
    sink.line("shell", &format!("installing the engine ({mode:?})"));

    let (app2, shared2) = (app.clone(), shared.clone());
    let on = Arc::new(move |progress: Progress| {
        set_status(&app2, &shared2, Status::Installing { progress });
    });
    let result = tokio::select! {
        r = provision::provision(&pcfg, mode, on) => r,
        _ = shared.stop.notified() => {
            return Err(("the app is closing".into(), None));
        }
    };
    match result {
        Ok(()) => {
            sink.line("shell", "the engine is installed");
            Ok(launch)
        }
        Err(e) => Err((e.message, Some(e.step))),
    }
}

async fn supervise(app: AppHandle, shared: Arc<Shared>, input: Input) {
    let sink = LogSink::open(&input.data_dir, "engine.log");
    let mut recent: Vec<Instant> = Vec::new();
    let mut attempt = 0u32;
    loop {
        if shared.stopping.load(Ordering::SeqCst) {
            break;
        }
        attempt += 1;
        set_status(&app, &shared, Status::Starting { attempt });
        let cfg = match prepare(&app, &shared, &input, &sink).await {
            Ok(cfg) => cfg,
            Err((message, step)) => {
                if shared.stopping.load(Ordering::SeqCst) {
                    break;
                }
                sink.line("shell", &format!("could not get an engine: {message}"));
                set_status(&app, &shared, Status::Failed { message, step });
                // an install does not fix itself: wait for Repair or Restart, or for the app to quit
                tokio::select! {
                    _ = shared.stop.notified() => break,
                    _ = shared.restart.notified() => {
                        recent.clear();
                        attempt = 0;
                        continue;
                    }
                }
            }
        };
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
                    set_status(
                        &app,
                        &shared,
                        Status::Failed {
                            message,
                            step: None,
                        },
                    );
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
        assert_eq!(
            parse_ready(r#"{"event": "other", "port": 1, "pid": 2}"#),
            None
        );
        assert_eq!(
            parse_ready(r#"{"event": "wasifyai.engine.ready", "port": 70000, "pid": 2}"#),
            None
        );
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
        assert_eq!(
            serde_json::to_value(Status::Stopped).unwrap()["state"],
            "stopped"
        );
    }
}
