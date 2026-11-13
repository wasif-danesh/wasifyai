// SPDX-License-Identifier: AGPL-3.0-only
//! `wasify-mcp`: the stdio launcher MCP clients run to reach the engine (ADR-0069 decision 2;
//! spike S1, "The launcher: what it has to do").
//!
//! Claude Code, Codex and OpenCode start this program and speak JSON-RPC over its stdin and
//! stdout. It is not a byte pipe: on every request it reads `engine.json` (the engine's pid,
//! loopback port and the launcher connection's secret; checked on the open descriptor), derives
//! the headers the 2026-07-28 revision needs from the body, carries the session of a legacy
//! client, streams the engine's server-sent events back one line each, forwards a cancel by
//! closing the request, and, when the app is not running, answers the few methods a client
//! needs itself with one sentence.

use std::collections::HashMap;
use std::io::Read;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use serde_json::{json, Value};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::sync::Mutex;
use tokio::task::JoinHandle;

const DOWN: &str = "Open Wasify AI, then restart your agent so it reads the tools again.";
const PV: &str = "io.modelcontextprotocol/protocolVersion";
const APP_ID: &str = "ai.wasifyai.desktop";

/// Where the engine says how to reach it. `WASIFY_ENGINE_JSON` overrides the usual place.
fn runtime_path() -> PathBuf {
    if let Some(p) = std::env::var_os("WASIFY_ENGINE_JSON") {
        return PathBuf::from(p);
    }
    let home = std::env::var_os("HOME").map(PathBuf::from);
    #[cfg(target_os = "macos")]
    let base = home.map(|h| h.join("Library/Application Support").join(APP_ID));
    #[cfg(target_os = "linux")]
    let base = std::env::var_os("XDG_DATA_HOME")
        .map(PathBuf::from)
        .or_else(|| home.map(|h| h.join(".local/share")))
        .map(|d| d.join(APP_ID));
    #[cfg(target_os = "windows")]
    let base = std::env::var_os("APPDATA").map(|d| PathBuf::from(d).join(APP_ID));
    #[cfg(not(any(target_os = "macos", target_os = "linux", target_os = "windows")))]
    let base: Option<PathBuf> = home.map(|h| h.join(APP_ID));
    base.unwrap_or_else(|| PathBuf::from(APP_ID)).join("engine.json")
}

#[derive(Clone, Debug)]
struct Runtime {
    host: String,
    port: u16,
    secret: String,
}

/// Read and check the runtime file. Every check is on the open descriptor (unix), so the file
/// that was checked is the file that is read.
fn read_runtime() -> Result<Runtime, String> {
    let path = runtime_path();
    #[cfg(unix)]
    let file = {
        use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
        let file = std::fs::OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW)
            .open(&path)
            .map_err(|e| format!("no runtime file ({e})"))?;
        let meta = file.metadata().map_err(|e| e.to_string())?; // fstat: the open descriptor
        if !meta.is_file() {
            return Err("the runtime file is not a regular file".into());
        }
        // SAFETY: getuid has no preconditions
        let me = unsafe { libc::getuid() };
        if meta.uid() != me {
            return Err("the runtime file belongs to another user".into());
        }
        if meta.mode() & 0o077 != 0 {
            return Err("the runtime file is readable by others".into());
        }
        if let Some(dir) = path.parent() {
            let d = std::fs::symlink_metadata(dir).map_err(|e| e.to_string())?;
            if d.uid() != me || d.mode() & 0o022 != 0 {
                return Err("the runtime folder is writable by others".into());
            }
        }
        file
    };
    #[cfg(not(unix))]
    let file = std::fs::File::open(&path).map_err(|e| format!("no runtime file ({e})"))?;
    let mut text = String::new();
    { &file }.read_to_string(&mut text).map_err(|e| e.to_string())?;
    let v: Value = serde_json::from_str(&text).map_err(|e| format!("bad runtime file: {e}"))?;
    let host = v["host"].as_str().unwrap_or("").to_string();
    if !matches!(host.as_str(), "127.0.0.1" | "::1" | "localhost") {
        return Err("the runtime file names a non-loopback host".into());
    }
    let port = v["port"].as_u64().ok_or("no port")? as u16;
    let secret = v["secret"].as_str().ok_or("no secret")?.to_string();
    let pid = v["pid"].as_i64().ok_or("no pid")?;
    #[cfg(unix)]
    {
        // SAFETY: kill with signal 0 checks that the process exists; it sends nothing
        let alive = unsafe { libc::kill(pid as libc::pid_t, 0) } == 0
            || std::io::Error::last_os_error().raw_os_error() == Some(libc::EPERM);
        if !alive {
            return Err("the engine's pid is gone (a stale file)".into());
        }
    }
    let _ = pid;
    Ok(Runtime { host, port, secret })
}

struct Bridge {
    client: reqwest::Client,
    out: Mutex<tokio::io::Stdout>,
    init_msg: Mutex<Option<Value>>,
    session_id: Mutex<Option<String>>,
    version: Mutex<Option<String>>,
    inflight: Mutex<HashMap<String, JoinHandle<()>>>,
}

impl Bridge {
    fn new() -> Arc<Self> {
        Arc::new(Self {
            client: reqwest::Client::builder()
                .no_proxy()
                .redirect(reqwest::redirect::Policy::none())
                .connect_timeout(Duration::from_secs(5))
                .build()
                .expect("an HTTP client"),
            out: Mutex::new(tokio::io::stdout()),
            init_msg: Mutex::new(None),
            session_id: Mutex::new(None),
            version: Mutex::new(None),
            inflight: Mutex::new(HashMap::new()),
        })
    }

    async fn emit(&self, v: &Value) {
        let mut out = self.out.lock().await;
        let mut line = v.to_string();
        line.push('\n');
        let _ = out.write_all(line.as_bytes()).await;
        let _ = out.flush().await;
    }

    /// The app is not running: answer what a client needs to see the one sentence.
    async fn local_answer(&self, msg: &Value, why: &str) {
        log::info!("local answer for {:?}: {why}", msg["method"].as_str());
        let (Some(id), Some(method)) = (msg.get("id"), msg["method"].as_str()) else {
            return;
        };
        let modern = msg["params"]["_meta"].get(PV).is_some();
        let mut extra = serde_json::Map::new();
        if modern {
            extra.insert("resultType".into(), json!("complete"));
            extra.insert("cacheScope".into(), json!("private"));
            extra.insert("ttlMs".into(), json!(0));
        }
        let with = |mut v: serde_json::Map<String, Value>| {
            v.extend(extra.clone());
            Value::Object(v)
        };
        let answer = match method {
            "server/discover" => json!({"jsonrpc": "2.0", "id": id, "result": with(json!({
                "supportedVersions": ["2026-07-28"], "capabilities": {"tools": {}},
                "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "wasify-mcp (app closed)", "version": "0"}}
            }).as_object().unwrap().clone())}),
            "initialize" => {
                let v = msg["params"]["protocolVersion"].as_str().unwrap_or("2025-11-25");
                json!({"jsonrpc": "2.0", "id": id, "result": {
                    "protocolVersion": v, "capabilities": {"tools": {"listChanged": true}},
                    "serverInfo": {"name": "wasify-mcp (app closed)", "version": "0"}}})
            }
            "tools/list" => json!({"jsonrpc": "2.0", "id": id, "result": with(json!({"tools": [{
                "name": "app_status", "description": "Tells whether Wasify AI is running.",
                "inputSchema": {"type": "object", "properties": {}},
                "annotations": {"readOnlyHint": true}}]}).as_object().unwrap().clone())}),
            "tools/call" => json!({"jsonrpc": "2.0", "id": id, "result": with(json!({
                "content": [{"type": "text", "text": DOWN}], "isError": true}).as_object().unwrap().clone())}),
            "ping" => json!({"jsonrpc": "2.0", "id": id, "result": Value::Object(extra.clone())}),
            _ => json!({"jsonrpc": "2.0", "id": id, "error": {"code": -32601, "message": DOWN}}),
        };
        self.emit(&answer).await;
    }

    /// The headers the engine's HTTP layer needs, derived from the body (spike S1, launcher 1 and 2).
    async fn headers(&self, msg: &Value, secret: &str) -> reqwest::header::HeaderMap {
        use reqwest::header::{HeaderMap, HeaderValue, ACCEPT, AUTHORIZATION, CONTENT_TYPE};
        let mut h = HeaderMap::new();
        h.insert(AUTHORIZATION, HeaderValue::from_str(&format!("Bearer {secret}")).unwrap());
        h.insert(ACCEPT, HeaderValue::from_static("application/json, text/event-stream"));
        h.insert(CONTENT_TYPE, HeaderValue::from_static("application/json"));
        let params = &msg["params"];
        if let Some(pv) = params["_meta"][PV].as_str() {
            h.insert("MCP-Protocol-Version", HeaderValue::from_str(pv).unwrap());
            if let Some(m) = msg["method"].as_str() {
                h.insert("Mcp-Method", HeaderValue::from_str(m).unwrap());
                let key = match m {
                    "tools/call" | "prompts/get" => Some("name"),
                    "resources/read" => Some("uri"),
                    _ => None,
                };
                if let Some(name) = key.and_then(|k| params[k].as_str()) {
                    if let Ok(v) = HeaderValue::from_str(name) {
                        h.insert("Mcp-Name", v);
                    }
                }
            }
        } else {
            if let Some(v) = self.version.lock().await.as_deref() {
                if msg["method"].as_str() != Some("initialize") {
                    h.insert("MCP-Protocol-Version", HeaderValue::from_str(v).unwrap());
                }
            }
            if let Some(s) = self.session_id.lock().await.as_deref() {
                h.insert("Mcp-Session-Id", HeaderValue::from_str(s).unwrap());
            }
        }
        h
    }

    /// The engine restarted: a legacy client's session is gone. Replay its initialize quietly.
    async fn reinit(&self, rt: &Runtime) {
        let Some(init) = self.init_msg.lock().await.clone() else { return };
        *self.session_id.lock().await = None;
        let url = format!("http://{}:{}/mcp", rt.host, rt.port);
        let headers = self.headers(&init, &rt.secret).await;
        if let Ok(r) = self.client.post(&url).headers(headers).body(init.to_string()).send().await {
            if let Some(sid) = r.headers().get("mcp-session-id").and_then(|v| v.to_str().ok()) {
                *self.session_id.lock().await = Some(sid.to_string());
            }
        }
        let note = json!({"jsonrpc": "2.0", "method": "notifications/initialized"});
        let headers = self.headers(&note, &rt.secret).await;
        let _ = self.client.post(&url).headers(headers).body(note.to_string()).send().await;
        log::info!("re-initialized the session after an engine restart");
    }

    async fn forward(self: Arc<Self>, msg: Value, retried: bool) {
        if msg["method"].as_str() == Some("initialize") {
            *self.init_msg.lock().await = Some(msg.clone());
        }
        let rt = match read_runtime() {
            Ok(rt) => rt,
            Err(why) => return self.local_answer(&msg, &why).await,
        };
        let url = format!("http://{}:{}/mcp", rt.host, rt.port);
        let headers = self.headers(&msg, &rt.secret).await;
        let sent = self.client.post(&url).headers(headers).body(msg.to_string()).send().await;
        let mut resp = match sent {
            Ok(r) => r,
            Err(e) => return self.local_answer(&msg, &format!("connect error: {e}")).await,
        };
        if let Some(sid) = resp.headers().get("mcp-session-id").and_then(|v| v.to_str().ok()) {
            *self.session_id.lock().await = Some(sid.to_string());
        }
        let status = resp.status().as_u16();
        let legacy_session = self.session_id.lock().await.is_some();
        if status == 404 && legacy_session && !retried && msg["method"].as_str() != Some("initialize") {
            self.reinit(&rt).await;
            return Box::pin(self.forward(msg, true)).await;
        }
        if status == 202 {
            return;
        }
        let sse = resp
            .headers()
            .get(reqwest::header::CONTENT_TYPE)
            .and_then(|v| v.to_str().ok())
            .map(|v| v.contains("text/event-stream"))
            .unwrap_or(false);
        if sse {
            // each `data:` event goes to stdout as one line, as it arrives
            let mut buf = String::new();
            let mut data: Vec<String> = Vec::new();
            loop {
                let chunk = match resp.chunk().await {
                    Ok(Some(c)) => c,
                    _ => break,
                };
                buf.push_str(&String::from_utf8_lossy(&chunk));
                while let Some(nl) = buf.find('\n') {
                    let line = buf[..nl].trim_end_matches('\r').to_string();
                    buf = buf[nl + 1..].to_string();
                    if let Some(rest) = line.strip_prefix("data:") {
                        data.push(rest.trim_start().to_string());
                    } else if line.is_empty() && !data.is_empty() {
                        if let Ok(v) = serde_json::from_str::<Value>(&data.join("\n")) {
                            self.handle(&msg, &v).await;
                        }
                        data.clear();
                    }
                }
            }
            return;
        }
        let body = resp.bytes().await.unwrap_or_default();
        if status >= 400 {
            if let Some(id) = msg.get("id") {
                if let Ok(mut err) = serde_json::from_slice::<Value>(&body) {
                    if err.get("error").is_some() {
                        err["id"] = id.clone();
                        return self.emit(&err).await;
                    }
                }
                let err = json!({"jsonrpc": "2.0", "id": id, "error": {
                    "code": -32000, "message": format!("the engine answered HTTP {status}")}});
                return self.emit(&err).await;
            }
            return;
        }
        if !body.is_empty() {
            if let Ok(v) = serde_json::from_slice::<Value>(&body) {
                self.handle(&msg, &v).await;
            }
        }
    }

    async fn handle(&self, req: &Value, obj: &Value) {
        if req["method"].as_str() == Some("initialize") {
            if let Some(v) = obj["result"]["protocolVersion"].as_str() {
                *self.version.lock().await = Some(v.to_string());
            }
        }
        self.emit(obj).await;
    }
}

#[tokio::main(flavor = "multi_thread", worker_threads = 2)]
async fn main() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("warn")).init();
    let bridge = Bridge::new();
    let mut lines = BufReader::new(tokio::io::stdin()).lines();
    while let Ok(Some(line)) = lines.next_line().await {
        let Ok(msg) = serde_json::from_str::<Value>(&line) else { continue };
        if msg["method"].as_str() == Some("notifications/cancelled") {
            // closing the request is how a cancel reaches the engine
            let key = msg["params"]["requestId"].to_string();
            if let Some(task) = bridge.inflight.lock().await.remove(&key) {
                task.abort();
            }
            continue;
        }
        let b = bridge.clone();
        let task = tokio::spawn(b.forward(msg.clone(), false));
        if msg.get("id").is_some() && msg.get("method").is_some() {
            bridge.inflight.lock().await.insert(msg["id"].to_string(), task);
        }
    }
    // stdin closed: the client is gone; let what is in flight finish briefly
    let pending: Vec<JoinHandle<()>> = bridge.inflight.lock().await.drain().map(|(_, t)| t).collect();
    for t in pending {
        let _ = tokio::time::timeout(Duration::from_secs(2), t).await;
    }
}
