// SPDX-License-Identifier: AGPL-3.0-only
//! The optional image-engine component (ADR-0059): ComfyUI's pinned source and its own Python
//! environment, installed on demand ("Set up image generation"), separate from the engine's.
//!
//! The same machinery as the engine's installer (provision.rs): the pinned uv and Python, hash-checked
//! downloads, `uv pip install --require-hashes` from a lock file in the engine bundle, step-by-step
//! progress, repair. Steps:
//!
//!   1 check        platform supported, bundle whole (the lock for this platform included), disk room
//!   2 uv           as for the engine (already there after the first run)
//!   3 python       `uv python install` (already there after the first run)
//!   4 source       the pinned ComfyUI release archive, checksum checked, unpacked
//!   5 environment  `uv venv` for ComfyUI alone: its torch must not touch the engine's packages
//!   6 packages     the hashed lock for this platform
//!   7 verify       import torch, note the accelerator, `main.py --quick-test-for-ci`
//!
//! Models are not part of this component; they are downloaded separately, on a click (stage A3).

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter};

use crate::disk;
use crate::download;
use crate::engine::{find_bundle_dir, Input};
use crate::logsink::LogSink;
use crate::manifest::{host_target, Manifest};
use crate::provision::{
    dir_size, ensure_uv, inside, load_bundle, run, uv_env, verify_bundle, Layout, Mode, Progress,
    ProvisionConfig, ProvisionError,
};

pub const COMPONENT: &str = "comfyui";
pub const STATUS_EVENT: &str = "component://status";

pub const STEPS: [(&str, &str); 7] = [
    ("check", "Checking this computer"),
    ("uv", "Getting the installer"),
    ("python", "Installing Python"),
    ("source", "Getting ComfyUI"),
    ("environment", "Creating ComfyUI's environment"),
    ("packages", "Installing ComfyUI's packages"),
    ("verify", "Checking ComfyUI"),
];

/// What the window is told about the component.
#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum ComponentStatus {
    /// Cannot be installed on this computer; `reason` is a sentence for a person.
    Unsupported {
        reason: String,
    },
    NotInstalled {
        needs_bytes: u64,
    },
    Installing {
        progress: Progress,
    },
    /// `accelerator` is what torch found: "mps" (Apple GPU), "cuda" or "cpu".
    Installed {
        version: String,
        accelerator: String,
    },
    Failed {
        message: String,
        step: Option<String>,
    },
}

#[derive(Clone, Debug)]
pub struct ComfyLayout {
    pub root: PathBuf,
    version: String,
}

impl ComfyLayout {
    pub fn new(core: &Layout, version: &str) -> ComfyLayout {
        ComfyLayout {
            root: core.root.join("comfyui"),
            version: version.to_string(),
        }
    }
    pub fn src_dir(&self) -> PathBuf {
        self.root.join(&self.version)
    }
    pub fn venv_dir(&self) -> PathBuf {
        self.root.join("venv")
    }
    pub fn venv_python(&self) -> PathBuf {
        if cfg!(windows) {
            self.venv_dir().join("Scripts").join("python.exe")
        } else {
            self.venv_dir().join("bin").join("python")
        }
    }
    pub fn state_file(&self) -> PathBuf {
        self.root.join("state.json")
    }
}

#[derive(Debug, Serialize, Deserialize, PartialEq, Eq)]
struct State {
    schema: u32,
    comfyui: String,
    python: String,
    lock_sha256: String,
    accelerator: String,
}

/// The status the files on disk say: installed, or not, or not possible here.
pub fn on_disk_status(
    data_dir: &Path,
    manifest: &Manifest,
    bundle_dir: Option<&Path>,
) -> ComponentStatus {
    if let Some(reason) = manifest.comfyui_unsupported() {
        return ComponentStatus::Unsupported { reason };
    }
    let c = manifest.comfyui.as_ref().expect("checked above");
    let layout = ComfyLayout::new(&Layout::new(data_dir, manifest), &c.version);
    let not_installed = ComponentStatus::NotInstalled {
        needs_bytes: c.disk.min_free_bytes,
    };
    let Ok(raw) = std::fs::read_to_string(layout.state_file()) else {
        return not_installed;
    };
    let Ok(state) = serde_json::from_str::<State>(&raw) else {
        return not_installed;
    };
    // the lock this install was made from must be the one the bundle carries now
    let current_lock = bundle_dir
        .and_then(|d| load_bundle(d).ok())
        .and_then(|(b, _)| b.comfyui)
        .and_then(|c| host_target().and_then(|t| c.locks.get(t).map(|f| f.sha256.clone())));
    let lock_ok = current_lock.map(|l| l == state.lock_sha256).unwrap_or(true);
    if state.schema == 1
        && state.comfyui == c.version
        && state.python == manifest.python.version
        && lock_ok
        && layout.venv_python().is_file()
        && layout.src_dir().join("main.py").is_file()
    {
        ComponentStatus::Installed {
            version: state.comfyui,
            accelerator: state.accelerator,
        }
    } else {
        not_installed
    }
}

fn report(
    on: &Arc<dyn Fn(Progress) + Send + Sync>,
    step: usize,
    detail: Option<String>,
    bytes: Option<(u64, u64)>,
) {
    let (id, label) = STEPS[step];
    on(Progress {
        component: COMPONENT.to_string(),
        step: id.to_string(),
        label: label.to_string(),
        index: step as u32 + 1,
        count: STEPS.len() as u32,
        bytes_done: bytes.map(|b| b.0),
        bytes_total: bytes.map(|b| b.1),
        detail,
    });
}

fn fail(step: usize, message: impl Into<String>) -> ProvisionError {
    ProvisionError {
        step: STEPS[step].0.to_string(),
        message: message.into(),
    }
}

/// Install (or repair) the component. `on` receives every progress marker.
pub async fn install(
    cfg: &ProvisionConfig,
    mode: Mode,
    on: Arc<dyn Fn(Progress) + Send + Sync>,
) -> Result<(), ProvisionError> {
    let log = LogSink::open(&cfg.data_dir, "provision.log");
    log.line("comfyui", &format!("starting ({mode:?})"));
    let res = steps(cfg, mode, &on, &log).await;
    match &res {
        Ok(()) => log.line("comfyui", "done"),
        Err(e) => log.line("comfyui", &format!("failed at {}: {}", e.step, e.message)),
    }
    res
}

async fn steps(
    cfg: &ProvisionConfig,
    mode: Mode,
    on: &Arc<dyn Fn(Progress) + Send + Sync>,
    log: &LogSink,
) -> Result<(), ProvisionError> {
    // 1. check ---------------------------------------------------------------------------------
    report(on, 0, None, None);
    if let Some(reason) = cfg.manifest.comfyui_unsupported() {
        return Err(fail(0, reason));
    }
    let c = cfg
        .manifest
        .comfyui
        .as_ref()
        .expect("checked above")
        .clone();
    let target = host_target().expect("supported implies a known target");
    let (bundle, _) = load_bundle(&cfg.bundle_dir).map_err(|m| fail(0, m))?;
    verify_bundle(&cfg.bundle_dir, &bundle).map_err(|m| fail(0, m))?;
    if let Some(b) = &bundle.comfyui {
        if b.version != c.version {
            return Err(fail(
                0,
                format!(
                    "the engine files are for ComfyUI {} but this app installs {}. Build them again with scripts/build-engine-bundle.sh",
                    b.version, c.version
                ),
            ));
        }
    }
    let lock = bundle
        .comfyui
        .as_ref()
        .and_then(|b| b.locks.get(target))
        .ok_or_else(|| {
            fail(
                0,
                format!(
                    "the engine files carry no package list for ComfyUI on this computer ({target}). \
                     Build them with scripts/build-engine-bundle.sh"
                ),
            )
        })?;
    let core = Layout::new(&cfg.data_dir, &cfg.manifest);
    let layout = ComfyLayout::new(&core, &c.version);
    std::fs::create_dir_all(&layout.root)
        .map_err(|e| fail(0, format!("cannot create {}: {e}", layout.root.display())))?;
    let free = disk::free_bytes(&layout.root).map_err(|m| fail(0, m))?;
    let held = dir_size(&layout.root);
    if free.saturating_add(held) < c.disk.min_free_bytes {
        return Err(fail(
            0,
            format!(
                "Image generation needs about {} of free space and this drive has {}. Free some space, or choose another drive, and try again.",
                disk::human(c.disk.min_free_bytes),
                disk::human(free)
            ),
        ));
    }
    if mode == Mode::Repair {
        let _ = std::fs::remove_file(layout.state_file());
        let _ = std::fs::remove_dir_all(layout.venv_dir());
        let _ = std::fs::remove_dir_all(layout.src_dir());
    }

    // 2. uv and 3. python: the engine's own, already there after the first run --------------------
    report(on, 1, None, None);
    let uv = ensure_uv(
        cfg,
        &core,
        mode,
        &|d, t| report(on, 1, None, Some((d, t))),
        log,
    )
    .await
    .map_err(|m| fail(1, m))?;
    let env = uv_env(&core);
    report(on, 2, None, None);
    run(
        &uv,
        &["python", "install", &cfg.manifest.python.version],
        &env,
        &core.root,
        log,
        |line| report(on, 2, Some(line.to_string()), None),
    )
    .await
    .map_err(|m| fail(2, m))?;

    // 4. source --------------------------------------------------------------------------------
    report(on, 3, None, None);
    let src = layout.src_dir();
    if !src.join("main.py").is_file() {
        let archive = core
            .root
            .join("downloads")
            .join(format!("comfyui-{}.{}", c.version, c.source.archive));
        log.line("comfyui", &format!("downloading {}", c.source.url));
        download::download_verified(
            &c.source.url,
            &archive,
            &c.source.sha256,
            c.source.size,
            cfg.allow_http,
            |d, t| report(on, 3, None, Some((d, t))),
        )
        .await
        .map_err(|e| fail(3, e.to_string()))?;
        let part = src.with_extension("part");
        let _ = std::fs::remove_dir_all(&part);
        let files = download::extract_tree(&archive, 1, &part).map_err(|m| fail(3, m))?;
        log.line("comfyui", &format!("unpacked {files} files"));
        if !part.join("main.py").is_file() {
            let _ = std::fs::remove_dir_all(&part);
            return Err(fail(3, "the ComfyUI archive does not contain main.py"));
        }
        let _ = std::fs::remove_dir_all(&src);
        std::fs::rename(&part, &src).map_err(|e| fail(3, e.to_string()))?;
        let _ = std::fs::remove_file(&archive);
    }

    // 5. environment ---------------------------------------------------------------------------
    report(on, 4, None, None);
    let _ = std::fs::remove_file(layout.state_file());
    if layout.venv_dir().exists() {
        std::fs::remove_dir_all(layout.venv_dir())
            .map_err(|e| fail(4, format!("cannot remove the old environment: {e}")))?;
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
        &core.root,
        log,
        |line| report(on, 4, Some(line.to_string()), None),
    )
    .await
    .map_err(|m| fail(4, m))?;

    // 6. packages ------------------------------------------------------------------------------
    report(on, 5, None, None);
    let python = layout.venv_python();
    let lock_path = inside(&cfg.bundle_dir, &lock.file).map_err(|m| fail(5, m))?;
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
            &lock_path.to_string_lossy(),
        ],
        &env,
        &core.root,
        log,
        |line| report(on, 5, Some(line.to_string()), None),
    )
    .await
    .map_err(|m| fail(5, m))?;

    // 7. verify --------------------------------------------------------------------------------
    report(on, 6, None, None);
    let accelerator = Arc::new(Mutex::new(String::from("cpu")));
    let seen = accelerator.clone();
    let py_env = [("PYTHONNOUSERSITE".into(), "1".into())];
    run(
        &python,
        &[
            "-c",
            "import torch; print('ACCEL', 'mps' if torch.backends.mps.is_available() \
             else 'cuda' if torch.cuda.is_available() else 'cpu')",
        ],
        &py_env,
        &src,
        log,
        move |line| {
            if let Some(a) = line.strip_prefix("ACCEL ") {
                *seen.lock().unwrap() = a.trim().to_string();
            }
        },
    )
    .await
    .map_err(|m| {
        fail(
            6,
            format!("torch does not start in its new environment: {m}"),
        )
    })?;
    run(
        &python,
        &["main.py", "--quick-test-for-ci"],
        &py_env,
        &src,
        log,
        |line| report(on, 6, Some(line.to_string()), None),
    )
    .await
    .map_err(|m| fail(6, format!("ComfyUI does not start: {m}")))?;

    let accelerator = accelerator.lock().unwrap().clone();
    log.line("comfyui", &format!("accelerator: {accelerator}"));
    let state = State {
        schema: 1,
        comfyui: c.version.clone(),
        python: cfg.manifest.python.version.clone(),
        lock_sha256: lock.sha256.clone(),
        accelerator,
    };
    std::fs::write(
        layout.state_file(),
        serde_json::to_vec_pretty(&state).expect("state serialises"),
    )
    .map_err(|e| fail(6, format!("cannot record the install: {e}")))?;
    let _ = std::fs::remove_dir_all(core.cache_dir());
    Ok(())
}

// ---- the window's side -----------------------------------------------------------------------

#[derive(Serialize, Clone)]
struct StatusEvent {
    id: &'static str,
    status: ComponentStatus,
}

/// Holds what is happening to the component right now (an install, or the last failure); when
/// nothing is, the status comes from the files on disk.
#[derive(Clone)]
pub struct Components {
    input: Input,
    current: Arc<Mutex<Option<ComponentStatus>>>,
    busy: Arc<AtomicBool>,
}

impl Components {
    pub fn new(input: Input) -> Components {
        Components {
            input,
            current: Arc::new(Mutex::new(None)),
            busy: Arc::new(AtomicBool::new(false)),
        }
    }

    pub fn status(&self) -> ComponentStatus {
        if let Some(s) = self.current.lock().unwrap().clone() {
            return s;
        }
        match Manifest::load() {
            Ok(m) => on_disk_status(
                &self.input.data_dir,
                &m,
                find_bundle_dir(&self.input).as_deref(),
            ),
            Err(message) => ComponentStatus::Failed {
                message,
                step: None,
            },
        }
    }

    fn set(&self, app: &AppHandle, status: Option<ComponentStatus>) {
        *self.current.lock().unwrap() = status;
        let _ = app.emit(
            STATUS_EVENT,
            StatusEvent {
                id: COMPONENT,
                status: self.status(),
            },
        );
    }

    /// Start installing (or repairing) in the background. Errors when one is already running.
    pub fn start(&self, app: AppHandle, repair: bool) -> Result<(), String> {
        if self.busy.swap(true, Ordering::SeqCst) {
            return Err("an install is already running".into());
        }
        let this = self.clone();
        tauri::async_runtime::spawn(async move {
            let outcome = this.run(&app, repair).await;
            this.busy.store(false, Ordering::SeqCst);
            match outcome {
                Ok(()) => this.set(&app, None),
                Err(e) => this.set(
                    &app,
                    Some(ComponentStatus::Failed {
                        message: e.message,
                        step: Some(e.step),
                    }),
                ),
            }
        });
        Ok(())
    }

    async fn run(&self, app: &AppHandle, repair: bool) -> Result<(), ProvisionError> {
        let manifest = Manifest::load().map_err(|message| ProvisionError {
            step: "check".into(),
            message,
        })?;
        let bundle_dir = find_bundle_dir(&self.input).ok_or_else(|| ProvisionError {
            step: "check".into(),
            message: "This app has no engine files to install from. In a development checkout run \
                      scripts/build-engine-bundle.sh."
                .into(),
        })?;
        let cfg = ProvisionConfig {
            data_dir: self.input.data_dir.clone(),
            bundle_dir,
            manifest,
            allow_http: false,
        };
        let (this, app2) = (self.clone(), app.clone());
        let on = Arc::new(move |progress: Progress| {
            this.set(&app2, Some(ComponentStatus::Installing { progress }));
        });
        let mode = if repair { Mode::Repair } else { Mode::Install };
        install(&cfg, mode, on).await
    }
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    fn temp(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("wasifyai-cui-{}-{name}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    fn bundle_with_lock(dir: &Path, target: &str) {
        std::fs::create_dir_all(dir.join("wheels")).unwrap();
        std::fs::create_dir_all(dir.join("comfyui")).unwrap();
        std::fs::write(dir.join("requirements.lock"), "x==1 --hash=sha256:00\n").unwrap();
        std::fs::write(
            dir.join(format!("comfyui/requirements-{target}.lock")),
            "torch==2 \\\n",
        )
        .unwrap();
        let entry = |rel: &str| {
            serde_json::json!({
                "file": rel,
                "sha256": download::sha256_file(&dir.join(rel)).unwrap(),
                "size": std::fs::metadata(dir.join(rel)).unwrap().len(),
            })
        };
        let lock_rel = format!("comfyui/requirements-{target}.lock");
        let bundle = serde_json::json!({
            "schema": 1,
            "requirements": entry("requirements.lock"),
            "wheels": [],
            "comfyui": { "version": "0.40.0", "locks": { target: entry(&lock_rel) } },
        });
        std::fs::write(
            dir.join("bundle.json"),
            serde_json::to_vec(&bundle).unwrap(),
        )
        .unwrap();
    }

    /// A tar.gz with the file layout of a ComfyUI release, served once on loopback.
    fn comfy_archive(dir: &Path) -> (PathBuf, String, u64) {
        let archive = dir.join("comfy.tar.gz");
        let gz = flate2::write::GzEncoder::new(
            std::fs::File::create(&archive).unwrap(),
            flate2::Compression::fast(),
        );
        let mut tar = tar::Builder::new(gz);
        for (name, data) in [
            ("ComfyUI-0.40.0/main.py", &b"print('comfy')"[..]),
            ("ComfyUI-0.40.0/comfy/__init__.py", &b""[..]),
        ] {
            let mut h = tar::Header::new_gnu();
            h.set_size(data.len() as u64);
            h.set_mode(0o644);
            h.set_cksum();
            tar.append_data(&mut h, name, data).unwrap();
        }
        tar.into_inner().unwrap().finish().unwrap();
        let sha = download::sha256_file(&archive).unwrap();
        let size = std::fs::metadata(&archive).unwrap().len();
        (archive, sha, size)
    }

    fn serve_file(path: PathBuf) -> String {
        use std::io::{Read, Write};
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}/comfy.tar.gz", listener.local_addr().unwrap());
        std::thread::spawn(move || {
            let body = std::fs::read(path).unwrap();
            let (mut s, _) = listener.accept().unwrap();
            let mut req = [0u8; 1024];
            let _ = s.read(&mut req);
            let _ = s.write_all(
                format!(
                    "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                    body.len()
                )
                .as_bytes(),
            );
            let _ = s.write_all(&body);
        });
        url
    }

    /// A stand-in uv that records its arguments and makes the folders the real one would.
    fn put_fake_uv(core: &Layout, manifest: &Manifest) {
        let dir = core.uv_dir();
        std::fs::create_dir_all(&dir).unwrap();
        let bin = dir.join(manifest.uv_binary_name());
        std::fs::write(
            &bin,
            r#"#!/bin/sh
ROOT="$(dirname "$UV_CACHE_DIR")"
echo "$@" >> "$ROOT/fake-uv.log"
case "$1" in
  python) mkdir -p "$UV_PYTHON_INSTALL_DIR/cpython-fake" ;;
  venv)
    mkdir -p "$2/bin"
    cat > "$2/bin/python" <<'PY'
#!/bin/sh
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
echo "python $@" >> "$ROOT/fake-uv.log"
case "$*" in *ACCEL*) echo "ACCEL mps" ;; esac
exit 0
PY
    chmod +x "$2/bin/python" ;;
esac
exit 0
"#,
        )
        .unwrap();
        std::fs::set_permissions(&bin, std::fs::Permissions::from_mode(0o755)).unwrap();
        std::fs::write(dir.join("uv.sha256"), download::sha256_file(&bin).unwrap()).unwrap();
    }

    fn collect() -> (
        Arc<Mutex<Vec<Progress>>>,
        Arc<dyn Fn(Progress) + Send + Sync>,
    ) {
        let seen = Arc::new(Mutex::new(Vec::new()));
        let s2 = seen.clone();
        (seen, Arc::new(move |p| s2.lock().unwrap().push(p)))
    }

    /// Only meaningful on the platform the component supports; elsewhere the test checks the refusal.
    #[tokio::test]
    async fn the_component_installs_in_seven_steps_and_records_the_accelerator() {
        let Some(target) = host_target() else { return };
        let root = temp("install");
        let bundle = root.join("bundle");
        bundle_with_lock(&bundle, target);
        let (archive, sha, size) = comfy_archive(&root);
        let url = serve_file(archive);
        let mut manifest = Manifest::load().unwrap();
        {
            let c = manifest.comfyui.as_mut().unwrap();
            c.source.url = url;
            c.source.sha256 = sha;
            c.source.size = size;
            c.platforms = vec![target.to_string()];
            c.disk.min_free_bytes = 1024;
        }
        let data = root.join("data");
        std::fs::create_dir_all(&data).unwrap();
        let core = Layout::new(&data, &manifest);
        put_fake_uv(&core, &manifest);
        let cfg = ProvisionConfig {
            data_dir: data.clone(),
            bundle_dir: bundle,
            manifest: manifest.clone(),
            allow_http: true,
        };
        let (seen, on) = collect();
        install(&cfg, Mode::Install, on).await.unwrap();

        let mut steps: Vec<String> = seen
            .lock()
            .unwrap()
            .iter()
            .map(|p| p.step.clone())
            .collect();
        steps.dedup();
        assert_eq!(
            steps,
            [
                "check",
                "uv",
                "python",
                "source",
                "environment",
                "packages",
                "verify"
            ]
        );
        assert!(seen
            .lock()
            .unwrap()
            .iter()
            .all(|p| p.component == "comfyui" && p.count == 7));

        let layout = ComfyLayout::new(&core, "0.40.0");
        assert!(layout.src_dir().join("main.py").is_file());
        assert!(layout.venv_python().is_file());
        let log = std::fs::read_to_string(core.root.join("fake-uv.log")).unwrap();
        assert!(log.contains("--require-hashes --no-deps -r"), "{log}");
        assert!(
            log.contains(&format!("requirements-{target}.lock")),
            "{log}"
        );
        assert!(log.contains("main.py --quick-test-for-ci"), "{log}");

        match on_disk_status(&data, &manifest, Some(&cfg.bundle_dir)) {
            ComponentStatus::Installed {
                version,
                accelerator,
            } => {
                assert_eq!((version.as_str(), accelerator.as_str()), ("0.40.0", "mps"));
            }
            other => panic!("expected installed, got {other:?}"),
        }
        // a changed lock file in the bundle means the install is out of date
        std::fs::write(
            cfg.bundle_dir
                .join(format!("comfyui/requirements-{target}.lock")),
            "torch==3",
        )
        .unwrap();
        let lock_rel = format!("comfyui/requirements-{target}.lock");
        let bj = serde_json::json!({
            "schema": 1,
            "requirements": {"file": "requirements.lock", "sha256": download::sha256_file(&cfg.bundle_dir.join("requirements.lock")).unwrap()},
            "wheels": [],
            "comfyui": {"version": "0.40.0", "locks": {target: {"file": lock_rel, "sha256": download::sha256_file(&cfg.bundle_dir.join(&lock_rel)).unwrap()}}},
        });
        std::fs::write(
            cfg.bundle_dir.join("bundle.json"),
            serde_json::to_vec(&bj).unwrap(),
        )
        .unwrap();
        assert!(matches!(
            on_disk_status(&data, &manifest, Some(&cfg.bundle_dir)),
            ComponentStatus::NotInstalled { .. }
        ));
    }

    #[tokio::test]
    async fn a_wrong_archive_checksum_stops_at_the_source_step() {
        let Some(target) = host_target() else { return };
        let root = temp("badsum");
        let bundle = root.join("bundle");
        bundle_with_lock(&bundle, target);
        let (archive, _sha, size) = comfy_archive(&root);
        let url = serve_file(archive);
        let mut manifest = Manifest::load().unwrap();
        {
            let c = manifest.comfyui.as_mut().unwrap();
            c.source.url = url;
            c.source.sha256 = "0".repeat(64);
            c.source.size = size;
            c.platforms = vec![target.to_string()];
            c.disk.min_free_bytes = 1024;
        }
        let data = root.join("data");
        std::fs::create_dir_all(&data).unwrap();
        let core = Layout::new(&data, &manifest);
        put_fake_uv(&core, &manifest);
        let cfg = ProvisionConfig {
            data_dir: data.clone(),
            bundle_dir: bundle,
            manifest,
            allow_http: true,
        };
        let (_seen, on) = collect();
        let err = install(&cfg, Mode::Install, on).await.unwrap_err();
        assert_eq!(err.step, "source");
        assert!(err.message.contains("checksum"), "{}", err.message);
        let layout = ComfyLayout::new(&core, "0.40.0");
        assert!(!layout.src_dir().exists());
        assert!(!layout.venv_dir().exists());
    }

    #[tokio::test]
    async fn an_unsupported_platform_is_refused_before_anything_runs() {
        let root = temp("unsupported");
        let bundle = root.join("bundle");
        bundle_with_lock(&bundle, "aarch64-apple-darwin");
        let mut manifest = Manifest::load().unwrap();
        manifest.comfyui.as_mut().unwrap().platforms = vec!["riscv64-unknown-linux-gnu".into()];
        let data = root.join("data");
        std::fs::create_dir_all(&data).unwrap();
        let cfg = ProvisionConfig {
            data_dir: data.clone(),
            bundle_dir: bundle,
            manifest: manifest.clone(),
            allow_http: false,
        };
        let (_seen, on) = collect();
        let err = install(&cfg, Mode::Install, on).await.unwrap_err();
        assert_eq!(err.step, "check");
        assert!(err.message.contains("Apple-silicon"), "{}", err.message);
        assert!(matches!(
            on_disk_status(&data, &manifest, None),
            ComponentStatus::Unsupported { .. }
        ));
    }

    #[test]
    fn status_serialises_for_the_window() {
        let v = serde_json::to_value(ComponentStatus::Installed {
            version: "0.40.0".into(),
            accelerator: "mps".into(),
        })
        .unwrap();
        assert_eq!(v["state"], "installed");
        assert_eq!(v["accelerator"], "mps");
        assert_eq!(
            serde_json::to_value(ComponentStatus::NotInstalled { needs_bytes: 5 }).unwrap()
                ["state"],
            "not_installed"
        );
    }
}
