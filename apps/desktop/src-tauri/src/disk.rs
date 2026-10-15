// SPDX-License-Identifier: AGPL-3.0-only
//! Free space on the volume that holds a folder, so an install can say "needs 2 GB, 600 MB free"
//! before it downloads anything.

use std::path::Path;

/// Bytes available to this user on the volume holding `path` (the nearest existing parent is used).
pub fn free_bytes(path: &Path) -> Result<u64, String> {
    let mut probe = path;
    while !probe.exists() {
        probe = probe
            .parent()
            .ok_or_else(|| format!("{} is not on any volume", path.display()))?;
    }
    imp(probe)
}

#[cfg(unix)]
fn imp(path: &Path) -> Result<u64, String> {
    use std::ffi::CString;
    use std::os::unix::ffi::OsStrExt;
    let c = CString::new(path.as_os_str().as_bytes()).map_err(|e| e.to_string())?;
    let mut stat: libc::statvfs = unsafe { std::mem::zeroed() };
    let rc = unsafe { libc::statvfs(c.as_ptr(), &mut stat) };
    if rc != 0 {
        return Err(format!(
            "could not read free space of {}: {}",
            path.display(),
            std::io::Error::last_os_error()
        ));
    }
    Ok((stat.f_bavail as u64).saturating_mul(stat.f_frsize as u64))
}

#[cfg(windows)]
fn imp(path: &Path) -> Result<u64, String> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Storage::FileSystem::GetDiskFreeSpaceExW;
    let wide: Vec<u16> = path
        .as_os_str()
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    let mut available: u64 = 0;
    let ok = unsafe {
        GetDiskFreeSpaceExW(
            wide.as_ptr(),
            &mut available,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
        )
    };
    if ok == 0 {
        return Err(format!(
            "could not read free space of {}: {}",
            path.display(),
            std::io::Error::last_os_error()
        ));
    }
    Ok(available)
}

/// "1.4 GB", "620 MB": for messages a person reads.
pub fn human(bytes: u64) -> String {
    const GB: f64 = 1_000_000_000.0;
    const MB: f64 = 1_000_000.0;
    let b = bytes as f64;
    if b >= GB {
        format!("{:.1} GB", b / GB)
    } else {
        format!("{:.0} MB", (b / MB).max(1.0))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn there_is_some_free_space_where_tests_run() {
        let dir = std::env::temp_dir();
        assert!(free_bytes(&dir).unwrap() > 0);
    }

    #[test]
    fn a_folder_that_does_not_exist_yet_uses_its_nearest_parent() {
        let dir = std::env::temp_dir().join("wasifyai-not-yet").join("deeper");
        assert_eq!(free_bytes(&dir).unwrap() > 0, true);
    }

    #[test]
    fn sizes_read_plainly() {
        assert_eq!(human(2_147_483_648), "2.1 GB");
        assert_eq!(human(620_000_000), "620 MB");
        assert_eq!(human(10), "1 MB");
    }
}
