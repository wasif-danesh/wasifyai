// SPDX-License-Identifier: AGPL-3.0-only
//! A small append-only log file under `<app data>/logs`, rotated once when it passes a size. The
//! engine's output and the installer's output each get one.

use std::io::Write;
use std::path::Path;
use std::sync::{Arc, Mutex};

const ROTATE_BYTES: u64 = 5 * 1024 * 1024;

#[derive(Clone)]
pub struct LogSink(Arc<Mutex<Option<std::fs::File>>>);

impl LogSink {
    pub fn open(data_dir: &Path, name: &str) -> LogSink {
        let dir = data_dir.join("logs");
        let _ = std::fs::create_dir_all(&dir);
        let path = dir.join(name);
        if std::fs::metadata(&path).map(|m| m.len()).unwrap_or(0) > ROTATE_BYTES {
            let _ = std::fs::rename(&path, dir.join(format!("{name}.1")));
        }
        let file = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(path)
            .ok();
        LogSink(Arc::new(Mutex::new(file)))
    }

    pub fn line(&self, source: &str, text: &str) {
        log::debug!("[{source}] {text}");
        if let Some(f) = self.0.lock().unwrap().as_mut() {
            let _ = writeln!(f, "[{source}] {text}");
        }
    }
}
