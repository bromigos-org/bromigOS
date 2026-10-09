#!/usr/bin/env python3
"""Waybar VECTOR pip: what VECTOR is doing and how many replies wait unread. Fed by the
bromigos-holo daemon ($XDG_RUNTIME_DIR/bromigos-vector.json), refreshed on SIGRTMIN+9.
Empty (hidden) when the daemon isn't running."""
import json
import os
import sys

sys.path.insert(0, "/usr/lib/bromigos/lib")   # bromigos-core: the theme
import bromigos_theme as T  # noqa: E402  (spans are written in the Wick's colours; T.retint -> the theme's)

path = os.path.join(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"), "bromigos-vector.json")
try:
    with open(path) as f:
        st = json.load(f)
except (OSError, ValueError):
    print(json.dumps({"text": "", "class": "off"}))
    raise SystemExit
state, unread = st.get("state", "idle"), int(st.get("unread") or 0)
word = {"idle": "VECTOR", "thinking": "CONSULTING", "speaking": "SPEAKING", "listening": "LISTENING",
        "error": "ANOMALY"}.get(state, "VECTOR")
text = word + (f" <span color='#d4af37'>{unread}</span>" if unread else "")
tip = {
    "idle": "VECTOR is at his post, line open",
    "thinking": "VECTOR is consulting the records",
    "speaking": "VECTOR is answering",
    "listening": "VECTOR is listening (mic open while SUPER+V is held)",
    "error": "VECTOR logged an anomaly: open the line to see what",
}.get(state, "VECTOR")
if unread:
    tip += f"\n{unread} repl{'y' if unread == 1 else 'ies'} waiting"
VOICES = {"main": "Governor Voss", "robot": "Sigil (readouts)", "scientist": "Professor Arc (tech)",
          "floor": "Revolver Lynx (the Floor)", "notify": "Lin Yao (notices)"}
mode = st.get("voice_mode") or "auto"
mood = st.get("mood") or "calm"
tip += "\nvoice: " + ("auto, now " + VOICES.get(st.get("voice") or "main", "main") if mode == "auto"
                     else "pinned to " + VOICES.get(mode, mode))
# the desktop mute (bromigos mute) keeps his voice and the theme's sounds together; say
# which are muted, the same words the mute's own notice uses
_theme_muted = os.path.exists(os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                                           "bromigos-live", "muted"))
_mute = ("\nall sound muted (SUPER+SHIFT+M)" if st.get("muted") and _theme_muted
         else "\nvoice muted (theme sounds on)" if st.get("muted")
         else "\ntheme sounds muted (VECTOR's voice on)" if _theme_muted else "")
tip += f"\nmood: {mood}" + (f"\nmodel: {st.get('model')}" if st.get("model") else "") + _mute
tip += ("\nclick: show or minimize (SUPER+E)\nright-click: cycle the voice (auto, main, robot, scientist, floor)"
        "\nmiddle-click: mute VECTOR only · SUPER+SHIFT+M or SUPER+SHIFT+V: mute all sound")
if st.get("conversation"):
    text = "CONVERSATION" + (f" <span color='#d4af37'>{unread}</span>" if unread else "")
    tip = "Conversation mode: VECTOR is listening hands-free (mic open)\n" + tip.split("\n", 1)[-1]
    tip += "\nSUPER+SHIFT+E ends conversation mode"
if mode != "auto":
    text += f" <span color='#7e927e'>·{mode.upper()}</span>"
sup = st.get("suppressed")
if sup:                              # speech held back: say so on the bar, never look broken
    short = sup.split(" · ")[0]
    if short == "VOICE MUTED" and _theme_muted:     # the desktop mute: more than his voice is off
        text += " <span color='#d4af37'>· MUTED</span>"
        tip = ("All sound muted: the theme's sounds and VECTOR's voice. SUPER+SHIFT+M or SUPER+SHIFT+V "
               "unmutes everything; middle-click here unmutes VECTOR only.\n" + tip)
    else:
        text += f" <span color='#d4af37'>· {short}</span>"
        tip = f"{short}: VECTOR's speech is held back. " + {
            "VOICE MUTED": "Middle-click to unmute him (SUPER+SHIFT+M or SUPER+SHIFT+V: all sound).",
        }.get(short, "Click VECTOR's panel button to undo it.") + "\n" + tip
w = st.get("watching") or {}
if w.get("on"):                      # watch mode: say so for as long as it's on
    text = f"<span color='#ff766f'>◉ WATCHING</span> " + text
    left = int(w.get("seconds_left") or 0)
    tip = (f"VECTOR is watching the focused window (a glance every {w.get('every_s')} s, words only, no images kept); "
           f"off in {left // 60} min {left % 60} s, or say 'stop watching'"
           + (f"\npaused: {w['paused']}" if w.get("paused") else "") + "\n" + tip)
if st.get("switch") == "off":       # the emergency switch: the red VECTOR OFF beside this pip says so too
    tip = ("Emergency switch OFF: his terminal runs nothing and his tools change nothing until you switch "
           "him back on (the red VECTOR OFF on the bar, SUPER+CTRL+ESCAPE, Settings › VECTOR)\n" + tip)
cls = [state] + (["unread"] if unread else []) + ([] if st.get("shown") else ["minimized"])
cls += ["listening", "conversation"] if st.get("conversation") else []
cls += [f"voice-{st.get('voice') or 'main'}"] if state == "speaking" else []
cls += [f"mood-{mood}"] if mood != "calm" else []
cls += ["watching"] if w.get("on") else []
print(T.retint(json.dumps({"text": text, "tooltip": tip, "class": cls})))
