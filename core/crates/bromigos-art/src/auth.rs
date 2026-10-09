//! A nolgia client for the person running `bromigos art`, with their own
//! credentials. The token is passed to the SDK and nowhere else: never printed,
//! logged, or put on a command line.
//!
//! In order:
//!
//! 1. `NOLGIA_API_KEY`, else `NOLGIA_TOKEN`: a personal access token (`nol_…`,
//!    from nolgia.com/settings/api-tokens) or any token the API takes;
//! 2. the token file `bromigos setup` writes for an unattended setup
//!    (`$XDG_DATA_HOME/bromigos/nolgia-token`, mode 0600; `token_file()`);
//! 3. the nolgia CLI's own login (`nolgia auth login`): `nolgia auth status`
//!    renews it when it has expired, then `nolgia auth token` hands it over on
//!    a pipe. The CLI is `$NOLGIA_BIN`, else `nolgia` on `PATH`, else
//!    `~/.cargo/bin/nolgia`.
//!
//! The API is `NOLGIA_BASE_URL`, else the CLI's `NOLGIA_API_URL`, else
//! production.

use std::path::PathBuf;
use std::process::{Command, Stdio};

use nolgia::Client;

use crate::Error;

/// Where the credentials came from (never the credentials).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Source {
    ApiKeyEnv,
    TokenEnv,
    TokenFile,
    CliLogin,
}

impl Source {
    pub fn describe(self) -> &'static str {
        match self {
            Source::ApiKeyEnv => "NOLGIA_API_KEY",
            Source::TokenEnv => "NOLGIA_TOKEN",
            Source::TokenFile => "the token file bromigos setup stored",
            Source::CliLogin => "the nolgia CLI's login",
        }
    }
}

/// The token file an unattended `bromigos setup` stores a personal access token in.
pub fn token_file() -> PathBuf {
    let data = env("XDG_DATA_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(env("HOME").unwrap_or_default()).join(".local/share"));
    data.join("bromigos/nolgia-token")
}

/// The stored token, when the file holds one (one line, no spaces).
fn file_token() -> Option<String> {
    let t = std::fs::read_to_string(token_file()).ok()?;
    let t = t.trim();
    (!t.is_empty() && !t.contains(char::is_whitespace)).then(|| t.to_owned())
}

fn env(name: &str) -> Option<String> {
    std::env::var(name).ok().filter(|v| !v.trim().is_empty())
}

fn cli() -> Option<PathBuf> {
    if let Some(p) = env("NOLGIA_BIN") {
        return Some(PathBuf::from(p));
    }
    if let Some(path) = std::env::var_os("PATH") {
        for d in std::env::split_paths(&path) {
            let p = d.join("nolgia");
            if p.is_file() {
                return Some(p);
            }
        }
    }
    let home = std::env::var_os("HOME").map(PathBuf::from)?;
    let p = home.join(".cargo/bin/nolgia");
    p.is_file().then_some(p)
}

/// The CLI's current token: renewed by `auth status` when expired, read from
/// `auth token`'s stdout (a pipe, never a terminal).
fn cli_token() -> Result<String, Error> {
    let bin = cli().ok_or_else(no_credentials)?;
    // `auth status` refreshes an expired login and saves it; its output (who
    // you are) isn't needed.
    let _ = Command::new(&bin)
        .args(["--json", "auth", "status"])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
    let out = Command::new(&bin)
        .args(["auth", "token"])
        .stdin(Stdio::null())
        .stderr(Stdio::null())
        .output()
        .map_err(|_| no_credentials())?;
    let token = String::from_utf8(out.stdout)
        .unwrap_or_default()
        .trim()
        .to_owned();
    if !out.status.success() || token.is_empty() || token.contains(char::is_whitespace) {
        return Err(no_credentials());
    }
    Ok(token)
}

fn no_credentials() -> Error {
    Error::Auth(
        "no nolgia credentials: run `nolgia auth login`, or set NOLGIA_API_KEY to a personal \
         access token (nolgia.com/settings/api-tokens)"
            .into(),
    )
}

/// Where credentials would come from, without using them: no network, no
/// login refresh (`bromigos art status`). The CLI counts when it is installed.
pub fn source() -> Option<Source> {
    if env("NOLGIA_API_KEY").is_some() {
        Some(Source::ApiKeyEnv)
    } else if env("NOLGIA_TOKEN").is_some() {
        Some(Source::TokenEnv)
    } else if file_token().is_some() {
        Some(Source::TokenFile)
    } else {
        cli().map(|_| Source::CliLogin)
    }
}

/// The client, and where its credentials came from.
pub fn client() -> Result<(Client, Source), Error> {
    let (token, source) = if let Some(k) = env("NOLGIA_API_KEY") {
        (k, Source::ApiKeyEnv)
    } else if let Some(k) = env("NOLGIA_TOKEN") {
        (k, Source::TokenEnv)
    } else if let Some(k) = file_token() {
        (k, Source::TokenFile)
    } else {
        (cli_token()?, Source::CliLogin)
    };
    let mut b = Client::builder()
        .api_key(token)
        .user_agent(concat!("bromigos-art/", env!("CARGO_PKG_VERSION")))
        // Long enough for a 100 MB reference upload on a slow line.
        .timeout(std::time::Duration::from_secs(600));
    if let Some(url) = env("NOLGIA_BASE_URL").or_else(|| env("NOLGIA_API_URL")) {
        b = b.base_url(url);
    }
    let c = b
        .build()
        .map_err(|e| Error::Auth(crate::log::scrub(&e.to_string())))?;
    Ok((c, source))
}
