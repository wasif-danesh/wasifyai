// SPDX-License-Identifier: AGPL-3.0-only
//! The component manifest (`engine-manifest.json`): exact pins and checksums for what the app installs
//! the engine's Python environment from. It is compiled in, so an installed app cannot be pointed at
//! another download by editing a file next to it.

use serde::Deserialize;
use std::collections::BTreeMap;

pub const MANIFEST_JSON: &str = include_str!("../engine-manifest.json");

#[derive(Debug, Clone, Deserialize)]
pub struct Manifest {
    pub schema: u32,
    pub uv: Uv,
    pub python: Python,
    pub disk: Disk,
    /// The optional image-engine component (ADR-0059). Absent: no component on this build.
    #[serde(default)]
    pub comfyui: Option<ComfyUi>,
    /// The optional local language-engine component (ADR-0062, stage D). Absent: none on this build.
    #[serde(default)]
    pub llamacpp: Option<LlamaCpp>,
}

/// llama.cpp's prebuilt `llama-server`, one release archive per platform.
#[derive(Debug, Clone, Deserialize)]
pub struct LlamaCpp {
    /// the release tag, for example "b11655"
    pub version: String,
    /// Keyed by Rust target triple.
    pub assets: BTreeMap<String, LlamaAsset>,
    pub disk: Disk,
}

#[derive(Debug, Clone, Deserialize)]
pub struct LlamaAsset {
    #[serde(flatten)]
    pub asset: Asset,
    /// path components of the archive's top folder to drop (the Mac and Linux archives have one)
    pub strip: usize,
    /// what the engine uses on this platform: "metal" (Apple GPU) or "cpu"
    pub backend: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct ComfyUi {
    pub version: String,
    /// the source archive of the tagged release
    pub source: Asset,
    /// target triples the component is installed on
    pub platforms: Vec<String>,
    pub disk: Disk,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Uv {
    pub version: String,
    pub binary: BinaryNames,
    /// Keyed by Rust target triple.
    pub assets: BTreeMap<String, Asset>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct BinaryNames {
    pub unix: String,
    pub windows: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Asset {
    pub url: String,
    pub sha256: String,
    pub size: u64,
    /// "tar.gz" or "zip"
    pub archive: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Python {
    pub version: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Disk {
    pub min_free_bytes: u64,
}

impl Manifest {
    pub fn load() -> Result<Manifest, String> {
        let m: Manifest = serde_json::from_str(MANIFEST_JSON)
            .map_err(|e| format!("the component manifest is not valid: {e}"))?;
        if m.schema != 1 {
            return Err(format!("unknown manifest schema {}", m.schema));
        }
        Ok(m)
    }

    /// The uv download for this machine.
    pub fn uv_asset(&self) -> Result<&Asset, String> {
        let target = host_target().ok_or_else(|| {
            format!(
                "this computer ({} {}) is not supported yet",
                std::env::consts::OS,
                std::env::consts::ARCH
            )
        })?;
        self.uv
            .assets
            .get(target)
            .ok_or_else(|| format!("the manifest has no uv build for {target}"))
    }

    /// Why the ComfyUI component cannot be installed here, or None when it can.
    pub fn comfyui_unsupported(&self) -> Option<String> {
        let Some(c) = &self.comfyui else {
            return Some("This build has no image engine.".into());
        };
        match host_target() {
            Some(t) if c.platforms.iter().any(|p| p == t) => None,
            _ => Some(
                "Real images need an Apple-silicon Mac in this version. The placeholder engine still works."
                    .into(),
            ),
        }
    }

    /// Why the language engine cannot be installed here, or None when it can.
    pub fn llamacpp_unsupported(&self) -> Option<String> {
        let Some(l) = &self.llamacpp else {
            return Some("This build has no local language engine.".into());
        };
        match host_target() {
            Some(t) if l.assets.contains_key(t) => None,
            _ => Some("The local language engine is not available for this computer yet.".into()),
        }
    }

    pub fn uv_binary_name(&self) -> &str {
        if cfg!(windows) {
            &self.uv.binary.windows
        } else {
            &self.uv.binary.unix
        }
    }
}

/// The Rust target triple of this machine, for the platforms the engine is built for.
pub fn host_target() -> Option<&'static str> {
    match (std::env::consts::OS, std::env::consts::ARCH) {
        ("macos", "aarch64") => Some("aarch64-apple-darwin"),
        ("macos", "x86_64") => Some("x86_64-apple-darwin"),
        ("windows", "x86_64") => Some("x86_64-pc-windows-msvc"),
        ("linux", "x86_64") => Some("x86_64-unknown-linux-gnu"),
        ("linux", "aarch64") => Some("aarch64-unknown-linux-gnu"),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn is_sha256(s: &str) -> bool {
        s.len() == 64
            && s.chars()
                .all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase())
    }

    #[test]
    fn the_manifest_parses_and_pins_every_platform() {
        let m = Manifest::load().unwrap();
        for target in [
            "aarch64-apple-darwin",
            "x86_64-apple-darwin",
            "x86_64-pc-windows-msvc",
            "x86_64-unknown-linux-gnu",
            "aarch64-unknown-linux-gnu",
        ] {
            let a =
                m.uv.assets
                    .get(target)
                    .unwrap_or_else(|| panic!("no uv for {target}"));
            assert!(
                is_sha256(&a.sha256),
                "{target}: sha256 must be 64 lowercase hex"
            );
            assert!(a.size > 1_000_000, "{target}: size looks wrong");
            assert!(a
                .url
                .starts_with("https://github.com/astral-sh/uv/releases/download/"));
            assert!(
                a.url.contains(&m.uv.version),
                "{target}: url is not for the pinned version"
            );
            assert!(a.archive == "tar.gz" || a.archive == "zip");
            assert_eq!(a.archive == "zip", target.contains("windows"));
        }
    }

    #[test]
    fn versions_are_exact() {
        let m = Manifest::load().unwrap();
        // x.y.z, no ranges
        for v in [&m.uv.version, &m.python.version] {
            let parts: Vec<&str> = v.split('.').collect();
            assert_eq!(parts.len(), 3, "{v} is not an exact version");
            assert!(parts.iter().all(|p| p.chars().all(|c| c.is_ascii_digit())));
        }
    }

    #[test]
    fn comfyui_is_pinned_exactly_and_only_where_it_is_supported() {
        let m = Manifest::load().unwrap();
        let c = m
            .comfyui
            .as_ref()
            .expect("the manifest carries the component");
        assert!(is_sha256(&c.source.sha256));
        assert_eq!(c.source.archive, "tar.gz");
        assert!(
            c.source.url.contains(&format!("v{}", c.version)),
            "url is for another version"
        );
        assert!(c
            .source
            .url
            .starts_with("https://github.com/comfyanonymous/ComfyUI/"));
        assert_eq!(c.version.split('.').count(), 3);
        assert_eq!(c.platforms, ["aarch64-apple-darwin"]);
        assert!(c.disk.min_free_bytes > 1_000_000_000);
        // the reason is a sentence for a person, and is given exactly when this machine is outside the list
        assert_eq!(
            m.comfyui_unsupported().is_none(),
            host_target() == Some("aarch64-apple-darwin")
        );
    }

    #[test]
    fn llamacpp_is_pinned_exactly_for_every_platform() {
        let m = Manifest::load().unwrap();
        let l = m
            .llamacpp
            .as_ref()
            .expect("the manifest carries the engine");
        assert!(l.version.starts_with('b') && l.version[1..].chars().all(|c| c.is_ascii_digit()));
        for target in [
            "aarch64-apple-darwin",
            "x86_64-apple-darwin",
            "x86_64-pc-windows-msvc",
            "x86_64-unknown-linux-gnu",
            "aarch64-unknown-linux-gnu",
        ] {
            let a = l
                .assets
                .get(target)
                .unwrap_or_else(|| panic!("no llama.cpp for {target}"));
            assert!(is_sha256(&a.asset.sha256), "{target}: sha256");
            assert!(a.asset.size > 1_000_000, "{target}: size looks wrong");
            assert!(a
                .asset
                .url
                .starts_with("https://github.com/ggml-org/llama.cpp/releases/download/"));
            assert!(
                a.asset.url.contains(&format!("/{}/", l.version)),
                "{target}: url is not for the pinned release"
            );
            assert_eq!(a.asset.archive == "zip", target.contains("windows"));
            assert!(a.backend == "metal" || a.backend == "cpu");
            assert_eq!(a.backend == "metal", target == "aarch64-apple-darwin");
        }
        assert!(l.disk.min_free_bytes > 100_000_000);
        // supported exactly where this machine has an entry
        assert_eq!(
            m.llamacpp_unsupported().is_none(),
            host_target().is_some_and(|t| l.assets.contains_key(t))
        );
    }

    #[test]
    fn this_machine_has_a_uv_build() {
        // CI runs on supported machines; on another one the app says so instead of failing oddly.
        if host_target().is_some() {
            assert!(Manifest::load().unwrap().uv_asset().is_ok());
        }
    }
}
