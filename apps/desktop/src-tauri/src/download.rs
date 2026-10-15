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

/// Is `link` (a symbolic link's target, relative to the folder it sits in) safe? It must stay inside the
/// unpacked tree: no absolute path, no drive, and never above the top.
fn link_stays_inside(parent_rel: &Path, link: &Path) -> bool {
    use std::path::Component;
    if link.is_absolute() {
        return false;
    }
    let mut depth = parent_rel.components().count() as i64;
    for c in link.components() {
        match c {
            Component::Normal(_) => depth += 1,
            Component::CurDir => {}
            Component::ParentDir => {
                depth -= 1;
                if depth < 0 {
                    return false;
                }
            }
            _ => return false,
        }
    }
    true
}

/// Unpack a `.tar.gz` into `dest`, dropping the first `strip` path components (the archive's top folder).
/// Regular files, folders and symbolic links are written. An absolute path or a `..` in an entry's name is
/// an error, and so is a link that points outside the tree, so an archive cannot write or point outside
/// `dest`. Hard links and special files are errors. Returns the number of files written.
pub fn extract_tree(archive: &Path, strip: usize, dest: &Path) -> Result<u64, String> {
    use std::path::Component;
    let f = File::open(archive).map_err(|e| e.to_string())?;
    let mut tar = tar::Archive::new(flate2::read::GzDecoder::new(f));
    std::fs::create_dir_all(dest).map_err(|e| e.to_string())?;
    let mut files = 0u64;
    for entry in tar.entries().map_err(|e| e.to_string())? {
        let mut entry = entry.map_err(|e| e.to_string())?;
        let kind = entry.header().entry_type();
        let path = entry.path().map_err(|e| e.to_string())?.into_owned();
        if path.is_absolute() || path.components().any(|c| matches!(c, Component::ParentDir)) {
            return Err(format!(
                "the archive names a path outside itself: {}",
                path.display()
            ));
        }
        let rel: PathBuf = path.components().skip(strip).collect();
        if rel.as_os_str().is_empty() {
            continue; // the top folder itself
        }
        let target = dest.join(&rel);
        if kind.is_dir() {
            std::fs::create_dir_all(&target).map_err(|e| e.to_string())?;
        } else if kind.is_file() {
            if let Some(parent) = target.parent() {
                std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
            }
            let mut out = File::create(&target).map_err(|e| e.to_string())?;
            std::io::copy(&mut entry, &mut out).map_err(|e| e.to_string())?;
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                if let Ok(mode) = entry.header().mode() {
                    let _ = std::fs::set_permissions(
                        &target,
                        std::fs::Permissions::from_mode(mode & 0o755 | 0o600),
                    );
                }
            }
            files += 1;
        } else if kind.is_symlink() {
            let link = entry
                .link_name()
                .map_err(|e| e.to_string())?
                .map(|l| l.into_owned())
                .ok_or_else(|| format!("a link without a target: {}", path.display()))?;
            let parent_rel = rel.parent().map(Path::to_path_buf).unwrap_or_default();
            if !link_stays_inside(&parent_rel, &link) {
                return Err(format!(
                    "the archive holds a link that points outside itself: {}",
                    path.display()
                ));
            }
            if let Some(parent) = target.parent() {
                std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
            }
            #[cfg(unix)]
            {
                let _ = std::fs::remove_file(&target);
                std::os::unix::fs::symlink(&link, &target).map_err(|e| e.to_string())?;
            }
            #[cfg(not(unix))]
            {
                return Err(format!(
                    "the archive holds a link this system cannot make: {}",
                    path.display()
                ));
            }
        } else if kind.is_pax_global_extensions() || kind.is_pax_local_extensions() {
            continue; // archive metadata (GitHub writes one)
        } else {
            return Err(format!(
                "the archive holds a hard link or special file: {}",
                path.display()
            ));
        }
    }
    Ok(files)
}

/// Unpack a `.zip` into `dest`, dropping the first `strip` path components. Files and folders only;
/// a name that escapes the folder is an error. Returns the number of files written.
pub fn extract_zip_tree(archive: &Path, strip: usize, dest: &Path) -> Result<u64, String> {
    use std::path::Component;
    let f = File::open(archive).map_err(|e| e.to_string())?;
    let mut zip = zip::ZipArchive::new(f).map_err(|e| e.to_string())?;
    std::fs::create_dir_all(dest).map_err(|e| e.to_string())?;
    let mut files = 0u64;
    for i in 0..zip.len() {
        let mut entry = zip.by_index(i).map_err(|e| e.to_string())?;
        let name = entry
            .enclosed_name()
            .ok_or_else(|| format!("the archive names a path outside itself: {}", entry.name()))?;
        if name
            .components()
            .any(|c| !matches!(c, Component::Normal(_)))
        {
            return Err(format!(
                "the archive names a path outside itself: {}",
                name.display()
            ));
        }
        let rel: PathBuf = name.components().skip(strip).collect();
        if rel.as_os_str().is_empty() {
            continue;
        }
        let target = dest.join(&rel);
        if entry.is_dir() {
            std::fs::create_dir_all(&target).map_err(|e| e.to_string())?;
        } else if entry.is_file() {
            if let Some(parent) = target.parent() {
                std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
            }
            let mut out = File::create(&target).map_err(|e| e.to_string())?;
            std::io::copy(&mut entry, &mut out).map_err(|e| e.to_string())?;
            files += 1;
        } else {
            return Err(format!(
                "the archive holds a link or special file: {}",
                name.display()
            ));
        }
    }
    Ok(files)
}

/// Unpack an archive of either supported kind (`"tar.gz"` or `"zip"`) into `dest`.
pub fn extract_archive_tree(
    archive: &Path,
    kind: &str,
    strip: usize,
    dest: &Path,
) -> Result<u64, String> {
    match kind {
        "tar.gz" => extract_tree(archive, strip, dest),
        "zip" => extract_zip_tree(archive, strip, dest),
        other => Err(format!("unknown archive type {other}")),
    }
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
        let dir = temp("zip-tree");
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

    fn make_tree_archive(dir: &Path, entries: &[(&str, &[u8])]) -> PathBuf {
        let archive = dir.join("tree.tar.gz");
        let gz = flate2::write::GzEncoder::new(
            File::create(&archive).unwrap(),
            flate2::Compression::fast(),
        );
        let mut tar = tar::Builder::new(gz);
        for (name, data) in entries {
            let mut h = tar::Header::new_gnu();
            h.set_size(data.len() as u64);
            h.set_mode(0o644);
            h.set_cksum();
            tar.append_data(&mut h, name, *data).unwrap();
        }
        tar.into_inner().unwrap().finish().unwrap();
        archive
    }

    #[test]
    fn a_tree_is_unpacked_without_its_top_folder() {
        let dir = temp("tree");
        let archive = make_tree_archive(
            &dir,
            &[
                ("App-1.0/main.py", b"print(1)"),
                ("App-1.0/pkg/mod.py", b"x = 1"),
            ],
        );
        let dest = dir.join("out");
        assert_eq!(extract_tree(&archive, 1, &dest).unwrap(), 2);
        assert_eq!(std::fs::read(dest.join("main.py")).unwrap(), b"print(1)");
        assert_eq!(std::fs::read(dest.join("pkg/mod.py")).unwrap(), b"x = 1");
    }

    #[test]
    fn a_tree_that_climbs_out_is_refused() {
        let dir = temp("climb");
        // tar::Builder refuses `..` itself, so write the header bytes by hand
        let archive = dir.join("bad.tar.gz");
        {
            let gz = flate2::write::GzEncoder::new(
                File::create(&archive).unwrap(),
                flate2::Compression::fast(),
            );
            let mut tar = tar::Builder::new(gz);
            let mut h = tar::Header::new_gnu();
            h.set_size(1);
            h.set_mode(0o644);
            {
                let name = b"App-1.0/../../evil.txt";
                let raw = h.as_old_mut();
                raw.name[..name.len()].copy_from_slice(name);
            }
            h.set_cksum();
            tar.append(&h, &b"x"[..]).unwrap();
            tar.into_inner().unwrap().finish().unwrap();
        }
        let err = extract_tree(&archive, 1, &dir.join("out")).unwrap_err();
        assert!(err.contains("outside"), "{err}");
        assert!(!dir.join("evil.txt").exists());
    }

    fn archive_with_link(dir: &Path, link_target: &str) -> PathBuf {
        let archive = dir.join("links.tar.gz");
        let gz = flate2::write::GzEncoder::new(
            File::create(&archive).unwrap(),
            flate2::Compression::fast(),
        );
        let mut tar = tar::Builder::new(gz);
        let data = b"library";
        let mut h = tar::Header::new_gnu();
        h.set_size(data.len() as u64);
        h.set_mode(0o755);
        h.set_cksum();
        tar.append_data(&mut h, "bin-1/libx.1.0.dylib", &data[..])
            .unwrap();
        let mut l = tar::Header::new_gnu();
        l.set_entry_type(tar::EntryType::Symlink);
        l.set_size(0);
        l.set_mode(0o755);
        l.set_cksum();
        tar.append_link(&mut l, "bin-1/libx.dylib", link_target)
            .unwrap();
        tar.into_inner().unwrap().finish().unwrap();
        archive
    }

    #[cfg(unix)]
    #[test]
    fn a_link_inside_the_tree_is_kept_and_works() {
        let dir = temp("link-ok");
        let archive = archive_with_link(&dir, "libx.1.0.dylib");
        let dest = dir.join("out");
        assert_eq!(extract_tree(&archive, 1, &dest).unwrap(), 1);
        assert_eq!(std::fs::read(dest.join("libx.dylib")).unwrap(), b"library");
        assert!(std::fs::symlink_metadata(dest.join("libx.dylib"))
            .unwrap()
            .file_type()
            .is_symlink());
    }

    #[cfg(unix)]
    #[test]
    fn a_link_that_points_outside_the_tree_is_refused() {
        for target in ["/etc/passwd", "../../outside", "../x"] {
            let dir = temp("link-bad");
            let archive = archive_with_link(&dir, target);
            let err = extract_tree(&archive, 1, &dir.join("out")).unwrap_err();
            assert!(err.contains("points outside"), "{target}: {err}");
        }
    }

    #[test]
    fn links_are_judged_by_where_they_sit() {
        // a link in `sub/` may go up one folder, not two
        assert!(link_stays_inside(Path::new("sub"), Path::new("../a")));
        assert!(!link_stays_inside(Path::new("sub"), Path::new("../../a")));
        assert!(link_stays_inside(Path::new(""), Path::new("a/../b")));
        assert!(!link_stays_inside(Path::new(""), Path::new("../a")));
    }

    #[test]
    fn a_zip_is_unpacked_without_its_top_folder_and_cannot_climb() {
        use std::io::Write as _;
        let dir = temp("zip");
        let archive = dir.join("a.zip");
        {
            let mut z = zip::ZipWriter::new(File::create(&archive).unwrap());
            let opts = zip::write::SimpleFileOptions::default();
            z.start_file("llama-1/llama-server.exe", opts).unwrap();
            z.write_all(b"exe").unwrap();
            z.start_file("llama-1/ggml.dll", opts).unwrap();
            z.write_all(b"dll").unwrap();
            z.finish().unwrap();
        }
        let dest = dir.join("out");
        assert_eq!(extract_zip_tree(&archive, 1, &dest).unwrap(), 2);
        assert_eq!(
            std::fs::read(dest.join("llama-server.exe")).unwrap(),
            b"exe"
        );

        let bad = dir.join("bad.zip");
        {
            let mut z = zip::ZipWriter::new(File::create(&bad).unwrap());
            z.start_file("../evil.txt", zip::write::SimpleFileOptions::default())
                .unwrap();
            z.write_all(b"x").unwrap();
            z.finish().unwrap();
        }
        let err = extract_zip_tree(&bad, 0, &dir.join("out2")).unwrap_err();
        assert!(err.contains("outside"), "{err}");
        assert!(!dir.join("evil.txt").exists());
    }

    #[test]
    fn a_files_checksum_is_computed_in_chunks() {
        let dir = temp("hash");
        let p = dir.join("f");
        std::fs::write(&p, vec![1u8; 3 << 20]).unwrap();
        assert_eq!(sha256_file(&p).unwrap(), sha(&vec![1u8; 3 << 20]));
    }
}
