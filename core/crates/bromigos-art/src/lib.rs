//! `bromigos art`: a world's art as data. `themes/<world>/art.toml` lists every
//! asset (images, edits, video loops, cutouts, upscales, 3D models, local steps such as the layer
//! split) with its recipe; `plan` prices what isn't produced yet from nolgia's
//! live catalog, `run` makes it through the official nolgia SDK and appends
//! each job to `themes/<world>/art.log.jsonl`, and `status` says what's
//! produced and what's stale. An asset whose model is `homelab:<name>` is made
//! by the user's own ComfyUI instead (`comfy`), for no credits. The format is
//! in docs/art.md.

pub mod auth;
pub mod comfy;
pub mod create;
pub mod glb;
pub mod log;
pub mod price;
pub mod run;
pub mod spec;
pub mod state;
pub mod targets;
pub mod video;

use std::path::{Path, PathBuf};

pub use run::{Plan, Planned, Ran, Report, RunOptions, find_world, mark, plan, run};
pub use spec::{Asset, Input, Kind, World};
pub use state::{State, Status, status};

/// Everything that can go wrong.
#[derive(Debug, thiserror::Error)]
pub enum Error {
    /// A bad `art.toml`, log, input or command.
    #[error("{0}")]
    Spec(String),
    #[error("{}: {source}", path.display())]
    Io {
        path: PathBuf,
        source: std::io::Error,
    },
    /// nolgia refused or failed (URLs scrubbed).
    #[error("nolgia: {0}")]
    Api(String),
    /// A ComfyUI refused or failed (its address never included).
    #[error("ComfyUI: {0}")]
    Homelab(String),
    /// No credentials.
    #[error("{0}")]
    Auth(String),
    /// The plan, or the run so far plus the next job, costs more than allowed.
    #[error("refused: {planned} credits is over --max-credits {max}")]
    OverBudget { planned: u64, max: u64 },
}

impl Error {
    pub fn io(path: &Path, source: std::io::Error) -> Self {
        Error::Io {
            path: path.to_path_buf(),
            source,
        }
    }
}

impl From<nolgia::Error> for Error {
    fn from(e: nolgia::Error) -> Self {
        Error::Api(log::scrub(&e.to_string()))
    }
}
