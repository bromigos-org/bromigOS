//! `bromigos bluetooth tui`: Bluetooth in the terminal, in bromigOS's DRIFTGLASS look
//! (docs/DRIFTGLASS.md, GLOW). It talks to `bromigos bluetooth session`, the desktop's one
//! bluez core (desktop/lib/bromigos_btsession.py), so pairing, the agent's questions, the
//! sound profiles and the controller test work the same as on the bar and in Settings.
//!
//! - `proto`: the session's line protocol
//! - `theme`: the theme in force (palette.json) and the motion setting
//! - `app`: the state, and what keys, the mouse and the session's messages do
//! - `view`: drawing it
pub mod app;
pub mod proto;
pub mod theme;
pub mod view;
