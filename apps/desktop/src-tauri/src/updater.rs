// SPDX-License-Identifier: AGPL-3.0-only
//! Updates of the app itself: a skeleton, switched off until the project has a signing key and a
//! release feed. Nothing is checked, downloaded or installed unless both are compiled in:
//!
//!   WASIFYAI_UPDATER_PUBKEY    the minisign public key the update archives are signed with
//!   WASIFYAI_UPDATER_ENDPOINT  the URL of the update feed (`latest.json`)
//!
//! With them set at build time `update_check` asks the feed and `update_install` downloads the
//! signed archive, verifies it against the key, installs it and restarts. Without them both answer
//! "not configured", so an unsigned development build never offers an update, and the updater
//! plugin is not even registered (it refuses to start without a key in `tauri.conf.json`). A release
//! build therefore passes `--config tauri.updater.conf.example.json` (filled in) as well.
//!
//! This is the same Tauri updater Unsloth Studio's shell uses; its staged-update and
//! installer-handover logic (`staged_update.rs`, `update.rs`) is not imported (see PROVENANCE.md).

use serde::Serialize;
use tauri::AppHandle;
use tauri_plugin_updater::UpdaterExt;

const PUBKEY: Option<&str> = option_env!("WASIFYAI_UPDATER_PUBKEY");
const ENDPOINT: Option<&str> = option_env!("WASIFYAI_UPDATER_ENDPOINT");

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum UpdateStatus {
    /// This build has no signing key or feed: updates are off.
    NotConfigured,
    UpToDate,
    Available {
        version: String,
        notes: Option<String>,
    },
    Failed {
        message: String,
    },
}

/// The key and feed, when this build has both.
pub fn configured() -> Option<(&'static str, &'static str)> {
    match (PUBKEY, ENDPOINT) {
        (Some(k), Some(e)) if !k.trim().is_empty() && !e.trim().is_empty() => Some((k, e)),
        _ => None,
    }
}

fn updater(app: &AppHandle) -> Result<tauri_plugin_updater::Updater, String> {
    let (key, endpoint) = configured().ok_or("updates are not configured in this build")?;
    let url = endpoint
        .parse()
        .map_err(|e| format!("the update feed address is not valid: {e}"))?;
    app.updater_builder()
        .pubkey(key)
        .endpoints(vec![url])
        .map_err(|e| e.to_string())?
        .build()
        .map_err(|e| e.to_string())
}

pub async fn check(app: &AppHandle) -> UpdateStatus {
    if configured().is_none() {
        return UpdateStatus::NotConfigured;
    }
    let result = match updater(app) {
        Ok(u) => u.check().await.map_err(|e| e.to_string()),
        Err(e) => Err(e),
    };
    match result {
        Ok(Some(update)) => UpdateStatus::Available {
            version: update.version.clone(),
            notes: update.body.clone(),
        },
        Ok(None) => UpdateStatus::UpToDate,
        Err(message) => UpdateStatus::Failed { message },
    }
}

/// Download, verify and install the available update, then restart the app.
pub async fn install(app: &AppHandle) -> Result<(), String> {
    let update = updater(app)?
        .check()
        .await
        .map_err(|e| e.to_string())?
        .ok_or("there is no update to install")?;
    update
        .download_and_install(|_chunk, _total| {}, || {})
        .await
        .map_err(|e| e.to_string())?;
    app.restart()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_build_without_a_key_and_feed_has_updates_off() {
        // the test build sets neither
        assert!(configured().is_none());
    }

    #[test]
    fn status_serialises_for_the_window() {
        let v = serde_json::to_value(UpdateStatus::Available {
            version: "0.2.0".into(),
            notes: None,
        })
        .unwrap();
        assert_eq!(v["state"], "available");
        assert_eq!(v["version"], "0.2.0");
        assert_eq!(
            serde_json::to_value(UpdateStatus::NotConfigured).unwrap()["state"],
            "not_configured"
        );
    }
}
