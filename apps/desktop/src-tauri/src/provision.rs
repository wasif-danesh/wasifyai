// SPDX-License-Identifier: AGPL-3.0-only
//! Provisioning of the engine's Python environment (ADR-0056, decision 6).
//!
//! First run, and "Repair", do the same six steps under `<app data>/engine`:
//!
//!   1. check    the engine bundle is whole (every file against `bundle.json`) and the disk has room
//!   2. uv       download uv from its pinned release, check its SHA-256, unpack it
//!   3. python   `uv python install <pinned version>` (uv checks the Python build it downloads)
//!   4. env      `uv venv`
//!   5. packages `uv pip install --require-hashes` the locked third-party packages, then our wheels
//!   6. verify   import the engine in the new environment, then write `state.json`
//!
//! Each step reports progress as a typed value that the window shows. Nothing here needs Python or
//! network access beyond uv's own download and the package index; ComfyUI and models are a later
//! phase (ADR-0059).

use std::ffi::OsString;
use std::path::{Component, Path, PathBuf};
use std::process::Stdio;
use std::sync::Arc;

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::Command;

use crate::disk;
use crate::download::{self, DownloadError};
use crate::logsink::LogSink;
use crate::manifest::Manifest;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

pub const STEPS: [(&str, &str); 6] = [
    ("check", "Checking this computer"),
    ("uv", "Getting the installer"),
    ("python", "Installing Python"),
    ("environment", "Creating the engine's environment"),
    ("packages", "Installing the engine"),
    ("verify", "Checking the engine"),
];

/// What the window shows while the engine is being installed.
#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct Progress {
    /// "engine" (uv, Python, the engine) or an optional component such as "comfyui"
    pub component: String,
    pub step: String,
    pub label: String,
    /// 1-based position of this step, out of `count`.
    pub index: u32,
    pub count: u32,
    pub bytes_done: Option<u64>,
    pub bytes_total: Option<u64>,
    /// The latest line of output, for a person who wants to see it is alive.
    pub detail: Option<String>,
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct ProvisionError {
    pub step: String,
    pub message: String,
}

impl std::fmt::Display for ProvisionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.message)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Mode {
    /// Install what is missing or out of date.
    Install,
    /// Throw away the environment and build it again, checking the installer's checksum, and the
    /// whole of Python too if the new environment does not work.
    Repair,
}

#[derive(Clone)]
pub struct ProvisionConfig {
    pub data_dir: PathBuf,
    pub bundle_dir: PathBuf,
    pub manifest: Manifest,
    /// Tests serve the installer from a loopback address.
    pub allow_http: bool,
}

// ---- where things live -----------------------------------------------------------------------

#[derive(Clone, Debug)]
pub struct Layout {
    pub root: PathBuf,
    uv_version: String,
}

impl Layout {
    pub fn new(data_dir: &Path, manifest: &Manifest) -> Layout {
        Layout {
            root: data_dir.join("engine"),
            uv_version: manifest.uv.version.clone(),
        }
    }
    pub fn uv_dir(&self) -> PathBuf {
        self.root
            .join("tools")
            .join(format!("uv-{}", self.uv_version))
    }
    pub fn python_dir(&self) -> PathBuf {
        self.root.join("python")
    }
    pub fn venv_dir(&self) -> PathBuf {
        self.root.join("venv")
    }
    pub fn cache_dir(&self) -> PathBuf {
        self.root.join("cache")
    }
    pub fn state_file(&self) -> PathBuf {
        self.root.join("state.json")
    }
    pub fn venv_python(&self) -> PathBuf {
        if cfg!(windows) {
            self.venv_dir().join("Scripts").join("python.exe")
        } else {
            self.venv_dir().join("bin").join("python")
        }
    }
}

// ---- the engine bundle -----------------------------------------------------------------------

#[derive(Debug, Deserialize)]
pub struct FileEntry {
    pub file: String,
    pub sha256: String,
    #[serde(default)]
    pub size: u64,
}

/// The optional ComfyUI component's files in the bundle: a hashed lock per platform it supports.
#[derive(Debug, Deserialize)]
pub struct ComfyBundle {
    /// keyed by Rust target triple
    pub locks: std::collections::BTreeMap<String, FileEntry>,
}

#[derive(Debug, Deserialize)]
pub struct Bundle {
    pub schema: u32,
    pub requirements: FileEntry,
    pub wheels: Vec<FileEntry>,
    #[serde(default)]
    pub product_files: Vec<FileEntry>,
    #[serde(default)]
    pub comfyui: Option<ComfyBundle>,
}

/// Read `bundle.json`; returns it with the checksum of the file itself (the version of the bundle).
pub fn load_bundle(dir: &Path) -> Result<(Bundle, String), String> {
    let path = dir.join("bundle.json");
    let raw = std::fs::read(&path).map_err(|_| {
        format!(
            "the engine files are missing ({} not found). Build them with scripts/build-engine-bundle.sh",
            path.display()
        )
    })?;
    let bundle: Bundle =
        serde_json::from_slice(&raw).map_err(|e| format!("bundle.json is not valid: {e}"))?;
    if bundle.schema != 1 {
        return Err(format!("unknown engine bundle schema {}", bundle.schema));
    }
    let digest = Sha256::digest(&raw);
    Ok((bundle, digest.iter().map(|b| format!("{b:02x}")).collect()))
}

/// A path from `bundle.json` must stay inside the bundle.
pub(crate) fn inside(dir: &Path, rel: &str) -> Result<PathBuf, String> {
    let p = Path::new(rel);
    if p.is_absolute() || p.components().any(|c| matches!(c, Component::ParentDir)) {
        return Err(format!("{rel}: a path outside the bundle"));
    }
    Ok(dir.join(p))
}

/// Every file the bundle names exists and has its recorded checksum.
pub fn verify_bundle(dir: &Path, bundle: &Bundle) -> Result<(), String> {
    let files = std::iter::once(&bundle.requirements)
        .chain(bundle.wheels.iter())
        .chain(bundle.product_files.iter())
        .chain(bundle.comfyui.iter().flat_map(|c| c.locks.values()));
    for entry in files {
        let path = inside(dir, &entry.file)?;
        let wrong_size = entry.size != 0
            && std::fs::metadata(&path)
                .map(|m| m.len() != entry.size)
                .unwrap_or(false);
        if wrong_size {
            return Err(format!(
                "{} is damaged (its size does not match bundle.json)",
                entry.file
            ));
        }
        let got = download::sha256_file(&path)
            .map_err(|_| format!("{} is missing from the engine files", entry.file))?;
        if got != entry.sha256.to_ascii_lowercase() {
            return Err(format!(
                "{} is damaged (its checksum does not match bundle.json)",
                entry.file
            ));
        }
    }
    Ok(())
}

// ---- state -----------------------------------------------------------------------------------

#[derive(Debug, Serialize, Deserialize, PartialEq, Eq)]
struct State {
    schema: u32,
    uv: String,
    python: String,
    bundle_sha256: String,
}

/// Whether the environment on disk is the one the manifest and the bundle ask for.
pub fn is_provisioned(layout: &Layout, manifest: &Manifest, bundle_sha256: &str) -> bool {
    let Ok(raw) = std::fs::read_to_string(layout.state_file()) else {
        return false;
    };
    let Ok(state) = serde_json::from_str::<State>(&raw) else {
        return false;
    };
    state
        == State {
            schema: 1,
            uv: manifest.uv.version.clone(),
            python: manifest.python.version.clone(),
            bundle_sha256: bundle_sha256.to_string(),
        }
        && layout.venv_python().is_file()
}

// ---- running it ------------------------------------------------------------------------------

struct Reporter {
    on: Arc<dyn Fn(Progress) + Send + Sync>,
}

impl Reporter {
    fn at(&self, step: usize, detail: Option<String>, bytes: Option<(u64, u64)>) {
        let (id, label) = STEPS[step];
        (self.on)(Progress {
            component: "engine".to_string(),
            step: id.to_string(),
            label: label.to_string(),
            index: step as u32 + 1,
            count: STEPS.len() as u32,
            bytes_done: bytes.map(|b| b.0),
            bytes_total: bytes.map(|b| b.1),
            detail,
        });
    }
}

fn fail(step: usize, message: impl Into<String>) -> ProvisionError {
    ProvisionError {
        step: STEPS[step].0.to_string(),
        message: message.into(),
    }
}

/// Install, or repair, the engine environment. `on` is called with every progress marker.
pub async fn provision(
    cfg: &ProvisionConfig,
    mode: Mode,
    on: Arc<dyn Fn(Progress) + Send + Sync>,
) -> Result<(), ProvisionError> {
    let log = LogSink::open(&cfg.data_dir, "provision.log");
    log.line("install", &format!("starting ({mode:?})"));
    let reporter = Reporter { on };
    let layout = Layout::new(&cfg.data_dir, &cfg.manifest);

    // Repair gets a second go that also throws Python and uv's cache away.
    let passes = if mode == Mode::Repair { 2 } else { 1 };
    let mut last = None;
    for pass in 0..passes {
        if pass == 1 {
            log.line(
                "install",
                "the repaired environment did not work: starting over",
            );
            let _ = std::fs::remove_dir_all(layout.python_dir());
            let _ = std::fs::remove_dir_all(layout.cache_dir());
        }
        match run_steps(cfg, &layout, mode, &reporter, &log).await {
            Ok(()) => {
                log.line("install", "done");
                return Ok(());
            }
            Err(e) => {
                log.line("install", &format!("failed at {}: {}", e.step, e.message));
                // a damaged bundle or a full disk is not cured by a second pass
                if e.step == "check" || e.step == "uv" {
                    return Err(e);
                }
                last = Some(e);
            }
        }
    }
    Err(last.expect("at least one pass ran"))
}

async fn run_steps(
    cfg: &ProvisionConfig,
    layout: &Layout,
    mode: Mode,
    r: &Reporter,
    log: &LogSink,
) -> Result<(), ProvisionError> {
    // 1. check ---------------------------------------------------------------------------------
    r.at(0, None, None);
    let (bundle, bundle_sha) = load_bundle(&cfg.bundle_dir).map_err(|m| fail(0, m))?;
    verify_bundle(&cfg.bundle_dir, &bundle).map_err(|m| fail(0, m))?;
    std::fs::create_dir_all(&layout.root)
        .map_err(|e| fail(0, format!("cannot create {}: {e}", layout.root.display())))?;
    let needed = cfg.manifest.disk.min_free_bytes;
    let free = disk::free_bytes(&layout.root).map_err(|m| fail(0, m))?;
    // an environment that is being rebuilt already holds part of what it needs
    let held = if layout.venv_dir().exists() {
        dir_size(&layout.root)
    } else {
        0
    };
    if free.saturating_add(held) < needed {
        return Err(fail(
            0,
            format!(
                "The engine needs about {} of free space and this drive has {}. Free some space, or choose another drive, and try again.",
                disk::human(needed),
                disk::human(free)
            ),
        ));
    }

    // 2. uv ------------------------------------------------------------------------------------
    r.at(1, None, None);
    let uv = ensure_uv(cfg, layout, mode, &|d, t| r.at(1, None, Some((d, t))), log)
        .await
        .map_err(|m| fail(1, m))?;

    let env = uv_env(layout);
    // 3. python --------------------------------------------------------------------------------
    r.at(2, None, None);
    run(
        &uv,
        &["python", "install", &cfg.manifest.python.version],
        &env,
        &layout.root,
        log,
        |line| r.at(2, Some(line.to_string()), None),
    )
    .await
    .map_err(|m| fail(2, m))?;

    // 4. environment ---------------------------------------------------------------------------
    r.at(3, None, None);
    let _ = std::fs::remove_file(layout.state_file()); // not provisioned while it is being built
    if layout.venv_dir().exists() {
        std::fs::remove_dir_all(layout.venv_dir())
            .map_err(|e| fail(3, format!("cannot remove the old environment: {e}")))?;
    }
    run(
        &uv,
        &[
            "venv",
            &layout.venv_dir().to_string_lossy(),
            "--python",
            &cfg.manifest.python.version,
        ],
        &env,
        &layout.root,
        log,
        |line| r.at(3, Some(line.to_string()), None),
    )
    .await
    .map_err(|m| fail(3, m))?;

    // 5. packages ------------------------------------------------------------------------------
    r.at(4, None, None);
    let python = layout.venv_python();
    let requirements =
        inside(&cfg.bundle_dir, &bundle.requirements.file).map_err(|m| fail(4, m))?;
    run(
        &uv,
        &[
            "pip",
            "install",
            "--python",
            &python.to_string_lossy(),
            "--require-hashes",
            "--no-deps",
            "-r",
            &requirements.to_string_lossy(),
        ],
        &env,
        &layout.root,
        log,
        |line| r.at(4, Some(line.to_string()), None),
    )
    .await
    .map_err(|m| fail(4, m))?;

    let mut wheel_args: Vec<String> = vec![
        "pip".into(),
        "install".into(),
        "--python".into(),
        python.to_string_lossy().into_owned(),
        "--no-deps".into(),
    ];
    for w in &bundle.wheels {
        wheel_args.push(
            inside(&cfg.bundle_dir, &w.file)
                .map_err(|m| fail(4, m))?
                .to_string_lossy()
                .into_owned(),
        );
    }
    let wheel_refs: Vec<&str> = wheel_args.iter().map(String::as_str).collect();
    run(&uv, &wheel_refs, &env, &layout.root, log, |line| {
        r.at(4, Some(line.to_string()), None)
    })
    .await
    .map_err(|m| fail(4, m))?;

    // 6. verify --------------------------------------------------------------------------------
    r.at(5, None, None);
    run(
        &python,
        &[
            "-c",
            "import wasifyai_api.desktop, wasifyai_media_worker.local, wasifyai_image",
        ],
        &[("PYTHONNOUSERSITE".into(), "1".into())],
        &layout.root,
        log,
        |_| {},
    )
    .await
    .map_err(|m| {
        fail(
            5,
            format!("the engine did not start in its new environment: {m}"),
        )
    })?;

    let state = State {
        schema: 1,
        uv: cfg.manifest.uv.version.clone(),
        python: cfg.manifest.python.version.clone(),
        bundle_sha256: bundle_sha,
    };
    std::fs::write(
        layout.state_file(),
        serde_json::to_vec_pretty(&state).expect("state serialises"),
    )
    .map_err(|e| fail(5, format!("cannot record the install: {e}")))?;
    // uv's download cache holds a second copy of every package; the environment has its own. A repair
    // that needs a package again downloads it again.
    let _ = std::fs::remove_dir_all(layout.cache_dir());
    Ok(())
}

/// The path of a working uv: the one already unpacked (if its checksum still matches what was
/// recorded when it was unpacked), or a fresh verified download.
pub(crate) async fn ensure_uv(
    cfg: &ProvisionConfig,
    layout: &Layout,
    mode: Mode,
    on_bytes: &(dyn Fn(u64, u64) + Sync),
    log: &LogSink,
) -> Result<PathBuf, String> {
    let asset = cfg.manifest.uv_asset()?;
    let dir = layout.uv_dir();
    let bin = dir.join(cfg.manifest.uv_binary_name());
    let sidecar = dir.join("uv.sha256");

    if bin.is_file() {
        let recorded = std::fs::read_to_string(&sidecar).unwrap_or_default();
        let now = download::sha256_file(&bin).unwrap_or_default();
        if !recorded.trim().is_empty() && recorded.trim() == now {
            log.line(
                "install",
                "uv is already installed and its checksum matches",
            );
            return Ok(bin);
        }
        log.line(
            "install",
            "the installed uv does not match its record: downloading it again",
        );
        let _ = mode;
        std::fs::remove_dir_all(&dir).map_err(|e| e.to_string())?;
    }

    let archive = layout
        .root
        .join("downloads")
        .join(format!("uv-{}.{}", cfg.manifest.uv.version, asset.archive));
    log.line("install", &format!("downloading {}", asset.url));
    download::download_verified(
        &asset.url,
        &archive,
        &asset.sha256,
        asset.size,
        cfg.allow_http,
        |done, total| on_bytes(done, total),
    )
    .await
    .map_err(|e: DownloadError| e.to_string())?;
    download::extract_file(
        &archive,
        &asset.archive,
        cfg.manifest.uv_binary_name(),
        &bin,
    )?;
    let digest = download::sha256_file(&bin).map_err(|e| e.to_string())?;
    std::fs::write(&sidecar, digest).map_err(|e| e.to_string())?;
    let _ = std::fs::remove_file(&archive);
    Ok(bin)
}

/// The environment uv runs with: everything under the engine folder, no user configuration.
pub(crate) fn uv_env(layout: &Layout) -> Vec<(OsString, OsString)> {
    let pairs: [(&str, OsString); 7] = [
        (
            "UV_PYTHON_INSTALL_DIR",
            layout.python_dir().into_os_string(),
        ),
        ("UV_CACHE_DIR", layout.cache_dir().into_os_string()),
        ("UV_NO_CONFIG", "1".into()),
        ("UV_PYTHON_PREFERENCE", "only-managed".into()),
        ("UV_LINK_MODE", "copy".into()),
        ("UV_NO_PROGRESS", "1".into()),
        ("NO_COLOR", "1".into()),
    ];
    pairs.into_iter().map(|(k, v)| (k.into(), v)).collect()
}

/// Run a program, passing its output lines to `on_line`; on failure the error carries its last lines.
pub(crate) async fn run(
    program: &Path,
    args: &[&str],
    env: &[(OsString, OsString)],
    cwd: &Path,
    log: &LogSink,
    on_line: impl Fn(&str),
) -> Result<(), String> {
    log.line("run", &format!("{} {}", program.display(), args.join(" ")));
    let mut cmd = Command::new(program);
    cmd.args(args)
        .current_dir(cwd)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    for (k, v) in env {
        cmd.env(k, v);
    }
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);
    let mut child = cmd
        .spawn()
        .map_err(|e| format!("could not run {}: {e}", program.display()))?;
    let mut out = BufReader::new(child.stdout.take().expect("piped")).lines();
    let mut err = BufReader::new(child.stderr.take().expect("piped")).lines();

    let mut tail: std::collections::VecDeque<String> = std::collections::VecDeque::new();
    let (mut out_open, mut err_open) = (true, true);
    while out_open || err_open {
        let (source, line) = tokio::select! {
            l = out.next_line(), if out_open => match l {
                Ok(Some(line)) => ("out", line),
                _ => { out_open = false; continue; }
            },
            l = err.next_line(), if err_open => match l {
                Ok(Some(line)) => ("err", line),
                _ => { err_open = false; continue; }
            },
        };
        let text = line.trim();
        if text.is_empty() {
            continue;
        }
        log.line(source, text);
        on_line(text);
        tail.push_back(text.to_string());
        if tail.len() > 6 {
            tail.pop_front();
        }
    }
    let status = child
        .wait()
        .await
        .map_err(|e| format!("lost {}: {e}", program.display()))?;
    if status.success() {
        Ok(())
    } else {
        let name = program
            .file_name()
            .map(|n| n.to_string_lossy().into_owned())
            .unwrap_or_default();
        Err(format!(
            "{name} stopped with {status}: {}",
            tail.iter().cloned().collect::<Vec<_>>().join(" | ")
        ))
    }
}

pub(crate) fn dir_size(path: &Path) -> u64 {
    let mut total = 0;
    let mut stack = vec![path.to_path_buf()];
    while let Some(p) = stack.pop() {
        let Ok(rd) = std::fs::read_dir(&p) else {
            continue;
        };
        for e in rd.flatten() {
            let Ok(md) = e.metadata() else { continue };
            if md.is_dir() {
                stack.push(e.path());
            } else {
                total += md.len();
            }
        }
    }
    total
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;
    use std::sync::Mutex;

    fn temp(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("wasifyai-prov-{}-{name}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    fn write_bundle(dir: &Path) {
        std::fs::create_dir_all(dir.join("wheels")).unwrap();
        std::fs::create_dir_all(dir.join("products/wasifyai-image")).unwrap();
        std::fs::write(
            dir.join("requirements.lock"),
            "left-pad==1.0 \\\n    --hash=sha256:00\n",
        )
        .unwrap();
        std::fs::write(
            dir.join("wheels/wasifyai_api-0.0.0-py3-none-any.whl"),
            b"wheel one",
        )
        .unwrap();
        std::fs::write(
            dir.join("wheels/wasifyai_image-0.0.0-py3-none-any.whl"),
            b"wheel two",
        )
        .unwrap();
        std::fs::write(
            dir.join("products/wasifyai-image/product.yaml"),
            "id: wasifyai-image\n",
        )
        .unwrap();
        let entry = |rel: &str| {
            let p = dir.join(rel);
            serde_json::json!({
                "file": rel,
                "sha256": download::sha256_file(&p).unwrap(),
                "size": std::fs::metadata(&p).unwrap().len(),
            })
        };
        let bundle = serde_json::json!({
            "schema": 1,
            "requirements": entry("requirements.lock"),
            "wheels": [
                entry("wheels/wasifyai_api-0.0.0-py3-none-any.whl"),
                entry("wheels/wasifyai_image-0.0.0-py3-none-any.whl"),
            ],
            "products": ["wasifyai-image"],
            "product_files": [entry("products/wasifyai-image/product.yaml")],
        });
        std::fs::write(
            dir.join("bundle.json"),
            serde_json::to_vec_pretty(&bundle).unwrap(),
        )
        .unwrap();
    }

    /// A stand-in for uv that records what it was asked and makes the folders the real one would.
    fn put_fake_uv(layout: &Layout, manifest: &Manifest) {
        let dir = layout.uv_dir();
        std::fs::create_dir_all(&dir).unwrap();
        let bin = dir.join(manifest.uv_binary_name());
        std::fs::write(
            &bin,
            r#"#!/bin/sh
ROOT="$(dirname "$UV_CACHE_DIR")"
echo "$@" >> "$ROOT/fake-uv.log"
case "$1" in
  python)
    mkdir -p "$UV_PYTHON_INSTALL_DIR/cpython-fake"
    echo "Installed Python $3 in 1ms" >&2 ;;
  venv)
    mkdir -p "$2/bin"
    cat > "$2/bin/python" <<'PY'
#!/bin/sh
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
echo "python $@" >> "$ROOT/fake-uv.log"
if [ -f "$ROOT/fail-verify" ]; then rm "$ROOT/fail-verify"; echo "ImportError: no module named wasifyai_api" >&2; exit 1; fi
exit 0
PY
    chmod +x "$2/bin/python" ;;
  pip)
    echo "Installed packages" >&2 ;;
esac
exit 0
"#,
        )
        .unwrap();
        std::fs::set_permissions(&bin, std::fs::Permissions::from_mode(0o755)).unwrap();
        std::fs::write(dir.join("uv.sha256"), download::sha256_file(&bin).unwrap()).unwrap();
    }

    struct Setup {
        cfg: ProvisionConfig,
        layout: Layout,
        seen: Arc<Mutex<Vec<Progress>>>,
    }

    fn setup(name: &str) -> Setup {
        let root = temp(name);
        let bundle = root.join("bundle");
        write_bundle(&bundle);
        let manifest = Manifest::load().unwrap();
        let data = root.join("data");
        std::fs::create_dir_all(&data).unwrap();
        let layout = Layout::new(&data, &manifest);
        put_fake_uv(&layout, &manifest);
        let mut m = manifest;
        m.disk.min_free_bytes = 1024;
        Setup {
            cfg: ProvisionConfig {
                data_dir: data,
                bundle_dir: bundle,
                manifest: m,
                allow_http: false,
            },
            layout,
            seen: Arc::new(Mutex::new(Vec::new())),
        }
    }

    fn recorder(s: &Setup) -> Arc<dyn Fn(Progress) + Send + Sync> {
        let seen = s.seen.clone();
        Arc::new(move |p| seen.lock().unwrap().push(p))
    }

    fn fake_log(s: &Setup) -> String {
        std::fs::read_to_string(s.layout.root.join("fake-uv.log")).unwrap_or_default()
    }

    #[test]
    fn a_whole_bundle_verifies_and_a_changed_file_does_not() {
        let dir = temp("bundle");
        write_bundle(&dir);
        let (bundle, sha) = load_bundle(&dir).unwrap();
        assert_eq!(sha.len(), 64);
        verify_bundle(&dir, &bundle).unwrap();

        std::fs::write(
            dir.join("wheels/wasifyai_api-0.0.0-py3-none-any.whl"),
            b"WHEEL ONE",
        )
        .unwrap();
        let err = verify_bundle(&dir, &bundle).unwrap_err();
        assert!(
            err.contains("wasifyai_api") && err.contains("damaged"),
            "{err}"
        );

        std::fs::remove_file(dir.join("wheels/wasifyai_image-0.0.0-py3-none-any.whl")).unwrap();
        // the first problem found is reported; both would fail
        assert!(verify_bundle(&dir, &bundle).is_err());
    }

    #[test]
    fn a_bundle_cannot_name_a_file_outside_itself() {
        let dir = temp("escape");
        write_bundle(&dir);
        std::fs::write(
            dir.join("bundle.json"),
            r#"{"schema":1,"requirements":{"file":"../../etc/passwd","sha256":"00"},"wheels":[]}"#,
        )
        .unwrap();
        let (bundle, _) = load_bundle(&dir).unwrap();
        assert!(verify_bundle(&dir, &bundle)
            .unwrap_err()
            .contains("outside"));
        assert!(load_bundle(&temp("empty"))
            .unwrap_err()
            .contains("build-engine-bundle"));
    }

    #[tokio::test]
    async fn an_install_runs_the_six_steps_in_order_and_records_the_result() {
        let s = setup("install");
        provision(&s.cfg, Mode::Install, recorder(&s))
            .await
            .unwrap();

        let seen = s.seen.lock().unwrap();
        let mut steps: Vec<String> = seen.iter().map(|p| p.step.clone()).collect();
        steps.dedup();
        assert_eq!(
            steps,
            ["check", "uv", "python", "environment", "packages", "verify"]
        );
        assert!(seen
            .iter()
            .all(|p| p.count == 6 && p.index >= 1 && p.index <= 6));

        let log = fake_log(&s);
        let py = &s.cfg.manifest.python.version;
        assert!(log.contains(&format!("python install {py}")), "{log}");
        assert!(log.contains(&format!("--python {py}")), "{log}");
        assert!(log.contains("--require-hashes --no-deps -r"), "{log}");
        assert!(log.contains("requirements.lock"), "{log}");
        assert!(log.contains("wasifyai_api-0.0.0-py3-none-any.whl"), "{log}");
        assert!(
            log.contains("python -c import wasifyai_api.desktop"),
            "{log}"
        );

        let (_, sha) = load_bundle(&s.cfg.bundle_dir).unwrap();
        assert!(is_provisioned(&s.layout, &s.cfg.manifest, &sha));
        assert!(!is_provisioned(
            &s.layout,
            &s.cfg.manifest,
            "another bundle"
        ));
        assert!(s.layout.root.join("../logs/provision.log").exists());
    }

    #[tokio::test]
    async fn a_failed_verify_leaves_the_engine_not_installed() {
        let s = setup("noverify");
        std::fs::create_dir_all(&s.layout.root).unwrap();
        std::fs::write(s.layout.root.join("fail-verify"), "").unwrap();
        let err = provision(&s.cfg, Mode::Install, recorder(&s))
            .await
            .unwrap_err();
        assert_eq!(err.step, "verify");
        assert!(err.message.contains("did not start"), "{}", err.message);
        let (_, sha) = load_bundle(&s.cfg.bundle_dir).unwrap();
        assert!(!is_provisioned(&s.layout, &s.cfg.manifest, &sha));
        assert!(!s.layout.state_file().exists());
    }

    #[tokio::test]
    async fn repair_starts_over_once_when_the_first_try_does_not_work() {
        let s = setup("repair");
        provision(&s.cfg, Mode::Install, recorder(&s))
            .await
            .unwrap();
        std::fs::write(s.layout.root.join("fail-verify"), "").unwrap(); // the next verify fails once
        std::fs::create_dir_all(s.layout.python_dir().join("stale")).unwrap();

        provision(&s.cfg, Mode::Repair, recorder(&s)).await.unwrap();
        let (_, sha) = load_bundle(&s.cfg.bundle_dir).unwrap();
        assert!(is_provisioned(&s.layout, &s.cfg.manifest, &sha));
        // the second pass threw Python away and installed it again
        assert!(!s.layout.python_dir().join("stale").exists());
        assert!(fake_log(&s).matches("python install").count() >= 3);
    }

    #[tokio::test]
    async fn too_little_disk_is_said_before_anything_is_downloaded() {
        let mut s = setup("disk");
        s.cfg.manifest.disk.min_free_bytes = u64::MAX;
        let err = provision(&s.cfg, Mode::Install, recorder(&s))
            .await
            .unwrap_err();
        assert_eq!(err.step, "check");
        assert!(err.message.contains("free space"), "{}", err.message);
        assert_eq!(fake_log(&s), ""); // uv was never run
    }

    #[tokio::test]
    async fn a_damaged_bundle_stops_the_install_at_the_first_step() {
        let s = setup("damaged");
        std::fs::write(s.cfg.bundle_dir.join("requirements.lock"), "evil==1.0").unwrap();
        let err = provision(&s.cfg, Mode::Install, recorder(&s))
            .await
            .unwrap_err();
        assert_eq!(err.step, "check");
        assert!(err.message.contains("requirements.lock"));
        assert_eq!(fake_log(&s), "");
    }

    #[test]
    fn the_layout_keeps_everything_under_one_folder() {
        let m = Manifest::load().unwrap();
        let l = Layout::new(Path::new("/data"), &m);
        for p in [
            l.uv_dir(),
            l.python_dir(),
            l.venv_dir(),
            l.cache_dir(),
            l.state_file(),
        ] {
            assert!(p.starts_with("/data/engine"), "{}", p.display());
        }
        assert!(l.uv_dir().to_string_lossy().contains(&m.uv.version));
    }
}
