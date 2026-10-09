//! A tiny client for the live layer's and VECTOR's control sockets.
//!
//! Both daemons speak the same one-shot protocol over a unix stream socket in
//! `$XDG_RUNTIME_DIR`: the client connects and writes one command as UTF-8 text (no
//! terminator); the daemon reads it with a single `recv`, runs it on its main loop and
//! writes the reply as text, then closes the connection.
//!
//! | Socket | Timeout | Example commands |
//! |---|---|---|
//! | `bromigos-live.sock` | 4 s | `ping`, `state`, `toggle`, `mute`, `codec DECK\|text` |
//! | `bromigos-holo.sock` | 6 s | `status` (a JSON object), `vector`, `ask …`, `stop` |
//!
//! The shell launchers read a single `recv` of 256 (live) or 65536 (VECTOR) bytes;
//! this client reads until the daemon closes, so long replies are not cut off.

use std::io::{self, Read, Write};
use std::net::Shutdown;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::time::Duration;

use thiserror::Error;

use crate::paths::Paths;

/// The live layer's timeout (as its launcher's `ctl`).
pub const LIVE_TIMEOUT: Duration = Duration::from_secs(4);
/// VECTOR's timeout (as its launcher's `send`).
pub const HOLO_TIMEOUT: Duration = Duration::from_secs(6);
/// Replies longer than this are cut (the daemons send a few KiB at most).
const MAX_REPLY: u64 = 1 << 20;

#[derive(Debug, Error)]
pub enum IpcError {
    /// Nothing listening (the daemon is not running).
    #[error("not running")]
    NotRunning(#[source] io::Error),
    #[error("{0}")]
    Io(#[from] io::Error),
}

/// Sends one command and returns the reply.
pub fn request(socket: &Path, command: &str, timeout: Duration) -> Result<String, IpcError> {
    let mut s = UnixStream::connect(socket).map_err(IpcError::NotRunning)?;
    s.set_read_timeout(Some(timeout))?;
    s.set_write_timeout(Some(timeout))?;
    s.write_all(command.as_bytes())?;
    // the daemons read one recv and never wait for EOF; closing our side is harmless
    let _ = s.shutdown(Shutdown::Write);
    let mut buf = Vec::new();
    s.take(MAX_REPLY).read_to_end(&mut buf)?;
    Ok(String::from_utf8_lossy(&buf).into_owned())
}

/// A command to the live layer (`bromigos-live ctl …`).
pub fn live(paths: &Paths, command: &str) -> Result<String, IpcError> {
    request(&paths.live_socket(), command, LIVE_TIMEOUT)
}

/// A command to VECTOR's daemon (`bromigos-holo`'s `send …`). Never starts it.
pub fn holo(paths: &Paths, command: &str) -> Result<String, IpcError> {
    request(&paths.holo_socket(), command, HOLO_TIMEOUT)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::net::UnixListener;

    #[test]
    fn one_shot_round_trip() {
        let dir = tempfile::tempdir().unwrap();
        let sock = dir.path().join("t.sock");
        let srv = UnixListener::bind(&sock).unwrap();
        let t = std::thread::spawn(move || {
            let (mut c, _) = srv.accept().unwrap();
            let mut b = [0u8; 256];
            let n = c.read(&mut b).unwrap();
            let cmd = String::from_utf8_lossy(&b[..n]).into_owned();
            // a reply longer than the shell clients' 256-byte recv
            c.write_all(format!("got {cmd} {}", "x".repeat(1000)).as_bytes())
                .unwrap();
        });
        let r = request(&sock, "state", Duration::from_secs(2)).unwrap();
        t.join().unwrap();
        assert!(r.starts_with("got state x"));
        assert_eq!(r.len(), "got state ".len() + 1000);
    }

    #[test]
    fn nothing_listening() {
        let dir = tempfile::tempdir().unwrap();
        let e = request(&dir.path().join("none.sock"), "ping", LIVE_TIMEOUT).unwrap_err();
        assert!(matches!(e, IpcError::NotRunning(_)));
    }
}
