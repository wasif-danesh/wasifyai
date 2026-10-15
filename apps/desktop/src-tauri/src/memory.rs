// SPDX-License-Identifier: AGPL-3.0-only
//! Resident memory of a process, for the numbers in docs/spikes/desktop-phase1.md. Linux and macOS
//! report resident set size; Windows reports the working set. They are close, not identical, so the
//! documents say which system a number came from.

/// Bytes of memory the process holds in RAM, or None when it cannot be read (the process is gone).
pub fn rss_bytes(pid: u32) -> Option<u64> {
    imp(pid)
}

#[cfg(target_os = "linux")]
fn imp(pid: u32) -> Option<u64> {
    let statm = std::fs::read_to_string(format!("/proc/{pid}/statm")).ok()?;
    let pages: u64 = statm.split_whitespace().nth(1)?.parse().ok()?;
    let page = unsafe { libc::sysconf(libc::_SC_PAGESIZE) };
    if page <= 0 {
        return None;
    }
    Some(pages * page as u64)
}

#[cfg(target_os = "macos")]
fn imp(pid: u32) -> Option<u64> {
    let out = std::process::Command::new("ps")
        .args(["-o", "rss=", "-p", &pid.to_string()])
        .output()
        .ok()?;
    let kb: u64 = String::from_utf8_lossy(&out.stdout).trim().parse().ok()?;
    Some(kb * 1024)
}

#[cfg(windows)]
fn imp(pid: u32) -> Option<u64> {
    use std::os::windows::process::CommandExt;
    let out = std::process::Command::new("powershell.exe")
        .creation_flags(0x0800_0000)
        .args([
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            &format!("(Get-Process -Id {pid}).WorkingSet64"),
        ])
        .output()
        .ok()?;
    String::from_utf8_lossy(&out.stdout).trim().parse().ok()
}

#[cfg(not(any(target_os = "linux", target_os = "macos", windows)))]
fn imp(_pid: u32) -> Option<u64> {
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn this_process_holds_some_memory() {
        let bytes = rss_bytes(std::process::id()).expect("readable on a supported system");
        assert!(bytes > 1_000_000, "{bytes}");
    }

    #[test]
    fn a_pid_that_is_gone_is_none() {
        // pid 0 is never a user process on any of the three systems
        assert!(rss_bytes(4_000_000_000).is_none());
    }
}
