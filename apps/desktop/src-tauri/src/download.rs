// SPDX-License-Identifier: AGPL-3.0-only
//! Download a file and check it against a pinned SHA-256 before anything uses it, and pull one file
//! out of a `.tar.gz` or `.zip`. Nothing is moved into place until the checksum matches.

use sha2::{Digest, Sha256};
use std::fs::File;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::time::Duration;

#[derive(Debug)]
pub enum DownloadError {
    /// Could not reach the server, or it answered with an error. Worth trying again.
    Network(String),
    /// The file arrived but is not the pinned one. Never retried: it would be the same file.
    Mismatch {
        expected: String,
        got: String,
    },
    Io(String),
}

impl std::fmt::Display for DownloadError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            DownloadError::Network(m) => write!(f, "the download failed: {m}"),
            DownloadError::Mismatch { expected, got } => write!(
                f,
                "the downloaded file is not the one this app expects (its checksum does not match), so it was not used (expected {}, got {})",
                &expected[..expected.len().min(12)],
                &got[..got.len().min(12)]
            ),
            DownloadError::Io(m) => write!(f, "could not write the file: {m}"),
        }
    }
}

pub fn sha256_file(path: &Path) -> std::io::Result<String> {
    let mut f = File::open(path)?;
    let mut hasher = Sha256::new();
    let mut buf = vec![0u8; 1 << 20];
    loop {
        let n = f.read(&mut buf)?;
        if n == 0 {
            break;
        }
        hasher.update(&buf[..n]);
    }
    Ok(hex(&hasher.finalize()))
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// Download `url` to `dest` and verify it. `allow_http` is for tests against a loopback server; the
/// manifest only has https URLs. Redirects are followed (GitHub release assets redirect to their CDN),
/// and the checksum, not the URL, is what is trusted.
pub async fn download_verified(
    url: &str,
    dest: &Path,
    expected_sha256: &str,
    expected_size: u64,
    allow_http: bool,
    mut on_bytes: impl FnMut(u64, u64),
) -> Result<(), DownloadError> {
    let client = reqwest::Client::builder()
        .https_only(!allow_http)
        .redirect(reqwest::redirect::Policy::limited(5))
        .connect_timeout(Duration::from_secs(20))
        .read_timeout(Duration::from_secs(60))
        .build()
        .map_err(|e| DownloadError::Network(e.to_string()))?;

    let mut last = DownloadError::Network("not tried".into());
    for attempt in 0..3u32 {
        if attempt > 0 {
            tokio::time::sleep(Duration::from_secs(2u64 << attempt)).await;
        }
        match attempt_once(
            &client,
            url,
            dest,
            expected_sha256,
            expected_size,
            &mut on_bytes,
        )
        .await
        {
            Ok(()) => return Ok(()),
            Err(e @ DownloadError::Network(_)) => last = e,
            Err(e) => return Err(e),
        }
    }
    Err(last)
}

async fn attempt_once(
    client: &reqwest::Client,
    url: &str,
    dest: &Path,
    expected_sha256: &str,
    expected_size: u64,
    on_bytes: &mut impl FnMut(u64, u64),
) -> Result<(), DownloadError> {
    let mut response = client.get(url).send().await.map_err(|e| {
        if e.is_builder() {
            // a URL this client may not use (plain http): trying again cannot help
            DownloadError::Io(e.to_string())
        } else {
            DownloadError::Network(e.to_string())
        }
    })?;
    if !response.status().is_success() {
        return Err(DownloadError::Network(format!(
            "the server answered {}",
            response.status().as_u16()
        )));
    }
    if let Some(parent) = dest.parent() {
        std::fs::create_dir_all(parent).map_err(|e| DownloadError::Io(e.to_string()))?;
    }
    let part: PathBuf = dest.with_extension("part");
    let mut file = File::create(&part).map_err(|e| DownloadError::Io(e.to_string()))?;
    let mut hasher = Sha256::new();
    let mut done = 0u64;
    loop {
        match response.chunk().await {
            Ok(Some(chunk)) => {
                hasher.update(&chunk);
                file.write_all(&chunk)
                    .map_err(|e| DownloadError::Io(e.to_string()))?;
                done += chunk.len() as u64;
                on_bytes(done, expected_size);
            }
            Ok(None) => break,
            Err(e) => {
                let _ = std::fs::remove_file(&part);
                return Err(DownloadError::Network(e.to_string()));
            }
        }
    }
    file.flush().map_err(|e| DownloadError::Io(e.to_string()))?;
    drop(file);
    let got = hex(&hasher.finalize());
    if got != expected_sha256.to_ascii_lowercase() || (expected_size != 0 && done != expected_size)
    {
        let _ = std::fs::remove_file(&part);
        return Err(DownloadError::Mismatch {
            expected: expected_sha256.to_string(),
            got,
        });
    }
    std::fs::rename(&part, dest).map_err(|e| DownloadError::Io(e.to_string()))?;
    Ok(())
}

/// Write the file called `wanted` (matched by its file name, wherever it sits in the archive) to
/// `dest`, executable on Unix. `kind` is "tar.gz" or "zip".
pub fn extract_file(archive: &Path, kind: &str, wanted: &str, dest: &Path) -> Result<(), String> {
    if let Some(parent) = dest.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let part = dest.with_extension("part");
    let found = match kind {
        "tar.gz" => extract_tar_gz(archive, wanted, &part)?,
        "zip" => extract_zip(archive, wanted, &part)?,
        other => return Err(format!("unknown archive type {other}")),
    };
    if !found {
        let _ = std::fs::remove_file(&part);
        return Err(format!("{wanted} is not in the archive"));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&part, std::fs::Permissions::from_mode(0o755))
            .map_err(|e| e.to_string())?;
    }
    std::fs::rename(&part, dest).map_err(|e| e.to_string())
}

fn file_name_is(path: &Path, wanted: &str) -> bool {
    path.file_name().map(|n| n == wanted).unwrap_or(false)
}

fn extract_tar_gz(archive: &Path, wanted: &str, out: &Path) -> Result<bool, String> {
    let f = File::open(archive).map_err(|e| e.to_string())?;
    let mut tar = tar::Archive::new(flate2::read::GzDecoder::new(f));
    for entry in tar.entries().map_err(|e| e.to_string())? {
        let mut entry = entry.map_err(|e| e.to_string())?;
        if !entry.header().entry_type().is_file() {
            continue;
        }
        let path = entry.path().map_err(|e| e.to_string())?.into_owned();
        if file_name_is(&path, wanted) {
            let mut o = File::create(out).map_err(|e| e.to_string())?;
            std::io::copy(&mut entry, &mut o).map_err(|e| e.to_string())?;
            return Ok(true);
        }
    }
    Ok(false)
}

fn extract_zip(archive: &Path, wanted: &str, out: &Path) -> Result<bool, String> {
    let f = File::open(archive).map_err(|e| e.to_string())?;
    let mut zip = zip::ZipArchive::new(f).map_err(|e| e.to_string())?;
    for i in 0..zip.len() {
        let mut entry = zip.by_index(i).map_err(|e| e.to_string())?;
        if !entry.is_file() {
            continue;
        }
        let name = entry.name().to_string();
        if file_name_is(Path::new(&name), wanted) {
            let mut o = File::create(out).map_err(|e| e.to_string())?;
            std::io::copy(&mut entry, &mut o).map_err(|e| e.to_string())?;
            return Ok(true);
        }
    }
    Ok(false)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;

    fn temp(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("wasifyai-dl-{}-{name}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    fn sha(bytes: &[u8]) -> String {
        hex(&Sha256::digest(bytes))
    }

    /// Serve `body` once on a loopback port.
    fn serve(body: Vec<u8>, status: &'static str) -> (String, std::thread::JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}/file.bin", listener.local_addr().unwrap());
        let h = std::thread::spawn(move || {
            let (mut s, _) = listener.accept().unwrap();
            let mut req = [0u8; 2048];
            let _ = s.read(&mut req);
            let head = format!(
                "HTTP/1.1 {status}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                body.len()
            );
            let _ = s.write_all(head.as_bytes());
            let _ = s.write_all(&body);
        });
        (url, h)
    }

    #[tokio::test]
    async fn a_file_with_the_pinned_checksum_is_kept_and_progress_is_reported() {
        let body = vec![7u8; 300_000];
        let (url, h) = serve(body.clone(), "200 OK");
        let dir = temp("ok");
        let dest = dir.join("a.bin");
        let mut last = 0;
        download_verified(&url, &dest, &sha(&body), body.len() as u64, true, |d, _| {
            last = d
        })
        .await
        .unwrap();
        h.join().unwrap();
        assert_eq!(std::fs::read(&dest).unwrap(), body);
        assert_eq!(last, body.len() as u64);
        assert!(!dir.join("a.part").exists());
    }

    #[tokio::test]
    async fn a_file_with_another_checksum_is_refused_and_removed() {
        let body = b"not the pinned file".to_vec();
        let (url, h) = serve(body, "200 OK");
        let dir = temp("bad");
        let dest = dir.join("a.bin");
        let err = download_verified(&url, &dest, &"0".repeat(64), 0, true, |_, _| {})
            .await
            .unwrap_err();
        h.join().unwrap();
        assert!(matches!(err, DownloadError::Mismatch { .. }), "{err}");
        assert!(!dest.exists());
        assert!(!dir.join("a.part").exists());
        assert!(err.to_string().contains("checksum"));
    }

    #[tokio::test]
    async fn a_wrong_size_is_refused_even_when_the_content_hashes_the_same() {
        let body = b"short".to_vec();
        let (url, h) = serve(body.clone(), "200 OK");
        let dir = temp("size");
        let err = download_verified(&url, &dir.join("a.bin"), &sha(&body), 999, true, |_, _| {})
            .await
            .unwrap_err();
        h.join().unwrap();
        assert!(matches!(err, DownloadError::Mismatch { .. }));
    }

    #[tokio::test]
    async fn plain_http_is_refused_unless_the_test_allows_it() {
        let dir = temp("https");
        let err = download_verified(
            "http://127.0.0.1:9/x",
            &dir.join("a.bin"),
            &"0".repeat(64),
            0,
            false,
            |_, _| {},
        )
        .await
        .unwrap_err();
        assert!(matches!(err, DownloadError::Io(_)), "{err}");
    }

    #[test]
    fn the_wanted_file_is_found_in_a_tar_gz_wherever_it_sits() {
        let dir = temp("tar");
        let archive = dir.join("a.tar.gz");
        {
            let gz = flate2::write::GzEncoder::new(
                File::create(&archive).unwrap(),
                flate2::Compression::fast(),
            );
            let mut tar = tar::Builder::new(gz);
            for (name, data) in [
                ("tool-1.0/README", &b"read me"[..]),
                ("tool-1.0/uv", &b"BINARY"[..]),
            ] {
                let mut h = tar::Header::new_gnu();
                h.set_size(data.len() as u64);
                h.set_mode(0o644);
                h.set_cksum();
                tar.append_data(&mut h, name, data).unwrap();
            }
            tar.into_inner().unwrap().finish().unwrap();
        }
        let dest = dir.join("out").join("uv");
        extract_file(&archive, "tar.gz", "uv", &dest).unwrap();
        assert_eq!(std::fs::read(&dest).unwrap(), b"BINARY");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                std::fs::metadata(&dest).unwrap().permissions().mode() & 0o111,
                0o111
            );
        }
        assert!(extract_file(&archive, "tar.gz", "missing", &dir.join("m")).is_err());
    }

    #[test]
    fn the_wanted_file_is_found_in_a_zip() {
        let dir = temp("zip");
        let archive = dir.join("a.zip");
        {
            let mut z = zip::ZipWriter::new(File::create(&archive).unwrap());
            let opts = zip::write::SimpleFileOptions::default();
            z.start_file("uvx.exe", opts).unwrap();
            z.write_all(b"OTHER").unwrap();
            z.start_file("uv.exe", opts).unwrap();
            z.write_all(b"BINARY").unwrap();
            z.finish().unwrap();
        }
        let dest = dir.join("uv.exe");
        extract_file(&archive, "zip", "uv.exe", &dest).unwrap();
        assert_eq!(std::fs::read(&dest).unwrap(), b"BINARY");
    }

    #[test]
    fn a_files_checksum_is_computed_in_chunks() {
        let dir = temp("hash");
        let p = dir.join("f");
        std::fs::write(&p, vec![1u8; 3 << 20]).unwrap();
        assert_eq!(sha256_file(&p).unwrap(), sha(&vec![1u8; 3 << 20]));
    }
}
