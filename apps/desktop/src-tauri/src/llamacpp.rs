// SPDX-License-Identifier: AGPL-3.0-only
//! The optional local language engine (stage D of phase 2): llama.cpp's prebuilt `llama-server`,
//! installed on demand like the image engine (comfyui.rs), but without Python: it is a native
//! release archive, pinned and checksum checked.
//!
//!   1 check    platform supported, disk room
//!   2 download the pinned release archive for this platform, SHA-256 and size checked
//!   3 unpack   into `<app data>/engine/llamacpp/<release>/` (symbolic links inside the tree are kept)
//!   4 verify   run `llama-server --version`, then write `state.json`
//!
//! The engine finds the server through `state.json` (wasifyai_api/llama_server.py). Models are not part
//! of this component: they are found (ADR-0063) or downloaded (ADR-0064) and chosen separately.

use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter};

use crate::comfyui::ComponentStatus;
use crate::disk;
use crate::download;
use crate::engine::Input;
use crate::logsink::LogSink;
use crate::manifest::{host_target, LlamaAsset, Manifest};
use crate::provision::{dir_size, run, Layout, Mode, Progress, ProvisionError};

pub const COMPONENT: &str = "llamacpp";
pub const STATUS_EVENT: &str = "component://status";

pub const STEPS: [(&str, &str); 4] = [
    ("check", "Checking this computer"),
    ("download", "Getting the language engine"),
    ("unpack", "Unpacking it"),
    ("verify", "Checking it"),
];

#[derive(Clone, Debug)]
pub struct LlamaLayout {
    pub root: PathBuf,
    version: String,
}

impl LlamaLayout {
    pub fn new(core: &Layout, version: &str) -> LlamaLayout {
        LlamaLayout {
            root: core.root.join("llamacpp"),
            version: version.to_string(),
        }
    }
    pub fn dir(&self) -> PathBuf {
        self.root.join(&self.version)
    }
    pub fn server(&self) -> PathBuf {
        self.dir().join(if cfg!(windows) {
            "llama-server.exe"
        } else {
            "llama-server"
        })
    }
    pub fn state_file(&self) -> PathBuf {
        self.root.join("state.json")
    }
}

/// What the engine reads (`llama_server.py`): which release, where its server is, what it runs on.
#[derive(Debug, Serialize, Deserialize, PartialEq, Eq)]
struct State {
    schema: u32,
    version: String,
    asset_sha256: String,
    backend: String,
    /// relative to the state file's folder
    server: String,
}

fn asset_for(manifest: &Manifest) -> Result<(&str, &LlamaAsset), String> {
    if let Some(reason) = manifest.llamacpp_unsupported() {
        return Err(reason);
    }
    let l = manifest.llamacpp.as_ref().expect("checked above");
    let target = host_target().expect("supported implies a known target");
    let asset = l.assets.get(target).expect("supported implies an asset");
    Ok((l.version.as_str(), asset))
}

/// The status the files on disk say.
pub fn on_disk_status(data_dir: &Path, manifest: &Manifest) -> ComponentStatus {
    let (version, asset) = match asset_for(manifest) {
        Ok(v) => v,
        Err(reason) => return ComponentStatus::Unsupported { reason },
    };
    let layout = LlamaLayout::new(&Layout::new(data_dir, manifest), version);
    let l = manifest.llamacpp.as_ref().expect("checked above");
    let not_installed = ComponentStatus::NotInstalled {
        needs_bytes: l.disk.min_free_bytes,
    };
    let Ok(raw) = std::fs::read_to_string(layout.state_file()) else {
        return not_installed;
    };
    let Ok(state) = serde_json::from_str::<State>(&raw) else {
        return not_installed;
    };
    if state.schema == 1
        && state.version == version
        && state.asset_sha256 == asset.asset.sha256
        && layout.server().is_file()
    {
        ComponentStatus::Installed {
            version: state.version,
            accelerator: state.backend,
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

pub struct LlamaConfig {
    pub data_dir: PathBuf,
    pub manifest: Manifest,
    /// Tests serve the archive from a loopback address.
    pub allow_http: bool,
}

/// Install (or repair) the component. `on` receives every progress marker.
pub async fn install(
    cfg: &LlamaConfig,
    mode: Mode,
    on: Arc<dyn Fn(Progress) + Send + Sync>,
) -> Result<(), ProvisionError> {
    let log = LogSink::open(&cfg.data_dir, "provision.log");
    log.line("llamacpp", &format!("starting ({mode:?})"));
    let res = steps(cfg, mode, &on, &log).await;
    match &res {
        Ok(()) => log.line("llamacpp", "done"),
        Err(e) => log.line("llamacpp", &format!("failed at {}: {}", e.step, e.message)),
    }
    res
}

async fn steps(
    cfg: &LlamaConfig,
    mode: Mode,
    on: &Arc<dyn Fn(Progress) + Send + Sync>,
    log: &LogSink,
) -> Result<(), ProvisionError> {
    // 1. check ---------------------------------------------------------------------------------
    report(on, 0, None, None);
    let (version, asset) = asset_for(&cfg.manifest).map_err(|m| fail(0, m))?;
    let (version, asset) = (version.to_string(), asset.clone());
    let min_free = cfg
        .manifest
        .llamacpp
        .as_ref()
        .expect("checked above")
        .disk
        .min_free_bytes;
    let core = Layout::new(&cfg.data_dir, &cfg.manifest);
    let layout = LlamaLayout::new(&core, &version);
    std::fs::create_dir_all(&layout.root)
        .map_err(|e| fail(0, format!("cannot create {}: {e}", layout.root.display())))?;
    let free = disk::free_bytes(&layout.root).map_err(|m| fail(0, m))?;
    if free.saturating_add(dir_size(&layout.root)) < min_free {
        return Err(fail(
            0,
            format!(
                "The language engine needs about {} of free space and this drive has {}. Free some space and try again.",
                disk::human(min_free),
                disk::human(free)
            ),
        ));
    }
    let _ = std::fs::remove_file(layout.state_file());
    if mode == Mode::Repair {
        let _ = std::fs::remove_dir_all(layout.dir());
    }

    // 2. download ------------------------------------------------------------------------------
    report(on, 1, None, None);
    let archive = core.root.join("downloads").join(format!(
        "llama-{}-{}",
        version,
        asset
            .asset
            .url
            .rsplit('/')
            .next()
            .unwrap_or("llama-server.archive")
    ));
    log.line("llamacpp", &format!("downloading {}", asset.asset.url));
    download::download_verified(
        &asset.asset.url,
        &archive,
        &asset.asset.sha256,
        asset.asset.size,
        cfg.allow_http,
        |d, t| report(on, 1, None, Some((d, t))),
    )
    .await
    .map_err(|e| fail(1, e.to_string()))?;

    // 3. unpack --------------------------------------------------------------------------------
    report(on, 2, None, None);
    let dir = layout.dir();
    let part = dir.with_extension("part");
    let _ = std::fs::remove_dir_all(&part);
    let files = download::extract_archive_tree(&archive, &asset.asset.archive, asset.strip, &part)
        .map_err(|m| fail(2, m))?;
    log.line("llamacpp", &format!("unpacked {files} files"));
    let server_name = if cfg!(windows) {
        "llama-server.exe"
    } else {
        "llama-server"
    };
    if !part.join(server_name).is_file() {
        let _ = std::fs::remove_dir_all(&part);
        return Err(fail(
            2,
            format!("the archive does not contain {server_name}"),
        ));
    }
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::rename(&part, &dir).map_err(|e| fail(2, e.to_string()))?;
    let _ = std::fs::remove_file(&archive);

    // 4. verify --------------------------------------------------------------------------------
    report(on, 3, None, None);
    let server = layout.server();
    #[cfg_attr(not(target_os = "linux"), allow(unused_mut))]
    let mut env: Vec<(OsString, OsString)> = Vec::new();
    #[cfg(target_os = "linux")]
    env.push(("LD_LIBRARY_PATH".into(), dir.clone().into_os_string()));
    let seen = Arc::new(Mutex::new(String::new()));
    let s2 = seen.clone();
    run(&server, &["--version"], &env, &dir, log, move |line| {
        if line.starts_with("version:") {
            *s2.lock().unwrap() = line.to_string();
        }
    })
    .await
    .map_err(|m| fail(3, format!("the language engine does not start: {m}")))?;
    let line = seen.lock().unwrap().clone();
    if line.is_empty() {
        return Err(fail(3, "the language engine did not say its version"));
    }
    log.line("llamacpp", &line);
    let state = State {
        schema: 1,
        version: version.clone(),
        asset_sha256: asset.asset.sha256.clone(),
        backend: asset.backend.clone(),
        server: format!("{version}/{server_name}"),
    };
    std::fs::write(
        layout.state_file(),
        serde_json::to_vec_pretty(&state).expect("state serialises"),
    )
    .map_err(|e| fail(3, format!("cannot record the install: {e}")))?;
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
            Ok(m) => on_disk_status(&self.input.data_dir, &m),
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
        let cfg = LlamaConfig {
            data_dir: self.input.data_dir.clone(),
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
        let d = std::env::temp_dir().join(format!("wasifyai-llama-{}-{name}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    /// A release-shaped tar.gz: a top folder, a `llama-server` script that prints its version, a library
    /// and a link to it.
    fn archive(dir: &Path, server_body: &str, with_server: bool) -> (PathBuf, String, u64) {
        let archive = dir.join("llama.tar.gz");
        let gz = flate2::write::GzEncoder::new(
            std::fs::File::create(&archive).unwrap(),
            flate2::Compression::fast(),
        );
        let mut tar = tar::Builder::new(gz);
        let mut add = |name: &str, data: &[u8], mode: u32| {
            let mut h = tar::Header::new_gnu();
            h.set_size(data.len() as u64);
            h.set_mode(mode);
            h.set_cksum();
            tar.append_data(&mut h, name, data).unwrap();
        };
        if with_server {
            add("llama-b1/llama-server", server_body.as_bytes(), 0o755);
        }
        add("llama-b1/libllama.0.1.dylib", b"lib", 0o755);
        let mut l = tar::Header::new_gnu();
        l.set_entry_type(tar::EntryType::Symlink);
        l.set_size(0);
        l.set_mode(0o755);
        l.set_cksum();
        tar.append_link(&mut l, "llama-b1/libllama.dylib", "libllama.0.1.dylib")
            .unwrap();
        tar.into_inner().unwrap().finish().unwrap();
        let sha = download::sha256_file(&archive).unwrap();
        let size = std::fs::metadata(&archive).unwrap().len();
        (archive, sha, size)
    }

    fn serve_file(path: PathBuf) -> String {
        use std::io::{Read, Write};
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}/llama.tar.gz", listener.local_addr().unwrap());
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

    fn manifest_for(url: String, sha: String, size: u64) -> (Manifest, &'static str) {
        let target = host_target().expect("tests run on a supported machine");
        let mut m = Manifest::load().unwrap();
        let l = m.llamacpp.as_mut().unwrap();
        let a = l.assets.get_mut(target).unwrap();
        a.asset.url = url;
        a.asset.sha256 = sha;
        a.asset.size = size;
        a.asset.archive = "tar.gz".into();
        a.strip = 1;
        l.disk.min_free_bytes = 1024;
        (m, target)
    }

    type Seen = Arc<Mutex<Vec<Progress>>>;
    type OnProgress = Arc<dyn Fn(Progress) + Send + Sync>;

    fn collect() -> (Seen, OnProgress) {
        let seen = Arc::new(Mutex::new(Vec::new()));
        let s2 = seen.clone();
        (seen, Arc::new(move |p| s2.lock().unwrap().push(p)))
    }

    #[tokio::test]
    async fn the_engine_installs_in_four_steps_and_the_state_names_the_server() {
        let root = temp("install");
        let (arch, sha, size) = archive(
            &root,
            "#!/bin/sh\necho 'version: 0.6.0-dev (build 1, commit abc)'\n",
            true,
        );
        let (m, _) = manifest_for(serve_file(arch), sha, size);
        let data = root.join("data");
        std::fs::create_dir_all(&data).unwrap();
        let cfg = LlamaConfig {
            data_dir: data.clone(),
            manifest: m.clone(),
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
        assert_eq!(steps, ["check", "download", "unpack", "verify"]);
        assert!(seen
            .lock()
            .unwrap()
            .iter()
            .all(|p| p.component == "llamacpp" && p.count == 4));

        let core = Layout::new(&data, &m);
        let layout = LlamaLayout::new(&core, "b11655");
        assert!(layout.server().is_file());
        // the library link was kept and works
        let link = layout.dir().join("libllama.dylib");
        assert!(std::fs::symlink_metadata(&link)
            .unwrap()
            .file_type()
            .is_symlink());
        assert_eq!(std::fs::read(&link).unwrap(), b"lib");
        assert!(!core
            .root
            .join("downloads")
            .join("llama-b11655-llama.tar.gz")
            .exists());

        let state: serde_json::Value =
            serde_json::from_slice(&std::fs::read(layout.state_file()).unwrap()).unwrap();
        assert_eq!(state["server"], "b11655/llama-server");
        assert_eq!(state["version"], "b11655");
        match on_disk_status(&data, &m) {
            ComponentStatus::Installed {
                version,
                accelerator,
            } => {
                assert_eq!(version, "b11655");
                assert!(accelerator == "metal" || accelerator == "cpu");
            }
            other => panic!("expected installed, got {other:?}"),
        }
        // a different pin means the install is out of date
        let mut newer = m.clone();
        let t = host_target().unwrap();
        newer
            .llamacpp
            .as_mut()
            .unwrap()
            .assets
            .get_mut(t)
            .unwrap()
            .asset
            .sha256 = "1".repeat(64);
        assert!(matches!(
            on_disk_status(&data, &newer),
            ComponentStatus::NotInstalled { .. }
        ));
    }

    #[tokio::test]
    async fn a_wrong_checksum_stops_at_the_download_and_leaves_nothing() {
        let root = temp("badsum");
        let (arch, _sha, size) = archive(&root, "#!/bin/sh\necho 'version: x'\n", true);
        let (m, _) = manifest_for(serve_file(arch), "0".repeat(64), size);
        let data = root.join("data");
        std::fs::create_dir_all(&data).unwrap();
        let cfg = LlamaConfig {
            data_dir: data.clone(),
            manifest: m.clone(),
            allow_http: true,
        };
        let (_seen, on) = collect();
        let err = install(&cfg, Mode::Install, on).await.unwrap_err();
        assert_eq!(err.step, "download");
        assert!(err.message.contains("checksum"), "{}", err.message);
        let layout = LlamaLayout::new(&Layout::new(&data, &m), "b11655");
        assert!(!layout.dir().exists());
        assert!(!layout.state_file().exists());
    }

    #[tokio::test]
    async fn an_archive_without_the_server_stops_at_unpack() {
        let root = temp("noserver");
        let (arch, sha, size) = archive(&root, "", false);
        let (m, _) = manifest_for(serve_file(arch), sha, size);
        let data = root.join("data");
        std::fs::create_dir_all(&data).unwrap();
        let cfg = LlamaConfig {
            data_dir: data.clone(),
            manifest: m.clone(),
            allow_http: true,
        };
        let (_seen, on) = collect();
        let err = install(&cfg, Mode::Install, on).await.unwrap_err();
        assert_eq!(err.step, "unpack");
        let layout = LlamaLayout::new(&Layout::new(&data, &m), "b11655");
        assert!(!layout.dir().exists());
    }

    #[tokio::test]
    async fn a_server_that_does_not_start_stops_at_verify_and_is_not_recorded() {
        let root = temp("broken");
        let (arch, sha, size) = archive(&root, "#!/bin/sh\nexit 3\n", true);
        let (m, _) = manifest_for(serve_file(arch), sha, size);
        let data = root.join("data");
        std::fs::create_dir_all(&data).unwrap();
        let cfg = LlamaConfig {
            data_dir: data.clone(),
            manifest: m.clone(),
            allow_http: true,
        };
        let (_seen, on) = collect();
        let err = install(&cfg, Mode::Install, on).await.unwrap_err();
        assert_eq!(err.step, "verify");
        assert!(matches!(
            on_disk_status(&data, &m),
            ComponentStatus::NotInstalled { .. }
        ));
    }

    #[test]
    fn an_unsupported_platform_says_so() {
        let mut m = Manifest::load().unwrap();
        m.llamacpp.as_mut().unwrap().assets.clear();
        assert!(matches!(
            on_disk_status(Path::new("/nonexistent"), &m),
            ComponentStatus::Unsupported { .. }
        ));
        let _ = std::fs::Permissions::from_mode(0o644); // (keeps the import used on every unix)
    }
}
