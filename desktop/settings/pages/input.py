"""Keyboard & input: the keyboard layout (and a second one), key repeat, Caps Lock and Num
Lock, the mouse and the touchpad (docs/settings.md, "Keyboard and input").

Everything goes through `bromigos setup input … --json`: kept in ~/.config/bromigos/input.toml,
written as a marked block in your hyprland.lua (bromigos.config.input) and taken by Hyprland
the safe way (auto-reload held, the config verified, one reload). A change applies at once
and toasts Undo; sliders save once they rest, since each save is a verified reload."""
from gi.repository import GLib, Gtk

from bromigos_settings import Entry, Page

CMD = ["bromigos", "setup", "input"]
FILE = "~/.config/bromigos/input.toml"
CAPS_LABEL = {"": "Caps Lock", "caps:escape": "Escape", "caps:escape_shifted_capslock": "Escape (Shift+Caps: Caps Lock)",
              "ctrl:nocaps": "Ctrl", "caps:swapescape": "Swapped with Escape", "caps:none": "Off"}
FOCUS = [("1", "Follows the pointer"), ("2", "On a click (the keyboard stays)"), ("0", "Never moves with the pointer")]


def _adv(key, target):
    return {"file": FILE, "key": key, "runs": f"bromigos setup input --set {key} VALUE",
            "note": f"then a marked block in ~/.config/hypr/hyprland.lua ({target.replace('input.', 'bromigos.config.input.')}) "
                    "and one verified reload"}


def _lit(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".") if v != int(v) else f"{v:.1f}"
    return str(v)


class InputPage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.doc = None
        self.lay = None
        self.page = ctx.page()
        self.page.set_reset(self.reset, what="The keyboard, the mouse and the touchpad go back to bromigOS's "
                                             "defaults (US layout, repeat 50/s after 240 ms, tap to click, natural "
                                             "scrolling on the touchpad). Your settings' block leaves hyprland.lua.")
        self._build()
        self.refresh()
        self.ctx.json(CMD + ["--layouts", "--json"], self._layouts)

    # ------------------------------------------------------------------ building
    def _build(self):
        ctx = self.ctx
        g = ctx.group(self.page, "Keyboard", "The layout you type with, how keys repeat, and what Caps Lock does.")
        self.kb_group = g
        self.problem = None
        self.layout = ctx.combo_row(g, "Layout", "", options=[], key="layout", enable_search=True,
                                    on_select=lambda c: self._layout(0, c),
                                    hint="The keyboard layout (xkb): what each key types. Type to search",
                                    advanced=_adv("kb_layout", "input.kb_layout"))
        self.variant = ctx.combo_row(g, "Variant", "", options=[("", "Standard")], key="variant",
                                     on_select=lambda v: self._variant(0, v),
                                     hint="A variant of the layout: Dvorak, no dead keys, international …",
                                     advanced=_adv("kb_variant", "input.kb_variant"))
        self.layout2 = ctx.combo_row(g, "Second layout", "Switch between two layouts with a key", options=[("", "None")],
                                     key="layout2", enable_search=True, on_select=lambda c: self._layout(1, c),
                                     hint="Another layout to switch to (none: one layout)",
                                     advanced=_adv("kb_layout", "input.kb_layout"))
        self.switch = ctx.combo_row(g, "Switch layouts with", "", options=[], key="switch-key",
                                    on_select=self._switch_key,
                                    hint="The keys that move between the two layouts (Win+Space is also the menu's: "
                                         "pick another)", advanced=_adv("kb_options", "input.kb_options"))
        self.rate = ctx.scale_row(g, "Repeat rate", "Characters a second while a key is held", lo=10, hi=80, step=1,
                                  value=50, fmt=lambda v: f"{int(v)}/s", key="repeat-rate", debounce=700,
                                  on_change=lambda v: self._set([("repeat_rate", int(v))], f"Key repeat: {int(v)}/s"),
                                  hint="Drag: how fast a held key repeats (applies as you let go)",
                                  advanced=_adv("repeat_rate", "input.repeat_rate"))
        self.delay = ctx.scale_row(g, "Repeat delay", "How long a key is held before it repeats", lo=150, hi=1000,
                                   step=10, value=240, fmt=lambda v: f"{int(v)} ms", key="repeat-delay", debounce=700,
                                   on_change=lambda v: self._set([("repeat_delay", int(v))], f"Repeat after {int(v)} ms"),
                                   hint="Drag: the wait before a held key starts repeating (applies as you let go)",
                                   advanced=_adv("repeat_delay", "input.repeat_delay"))
        tryit = Gtk.Entry(placeholder_text="Type here to try it", hexpand=True)
        ctx.hint(tryit, "A place to hold a key down and feel the repeat (nothing typed here is kept)")
        ctx.row(g, "Try it", "", control=tryit, key="try", hint="Hold a key here to feel the repeat rate and delay")
        self.caps = ctx.combo_row(g, "Caps Lock key", "", options=list(CAPS_LABEL.items()), key="caps",
                                  on_select=self._caps,
                                  hint="What the Caps Lock key does: Caps Lock, Escape, Ctrl, swapped with Escape or "
                                       "nothing", advanced=_adv("kb_options", "input.kb_options"))
        self.numlock = ctx.switch_row(g, "Num Lock on at start", "The number pad types numbers from login",
                                      key="numlock", on_toggle=lambda on: self._set([("numlock_by_default", on)],
                                                                                    f"Num Lock at start: {'on' if on else 'off'}"),
                                      hint="Turns Num Lock on when the session starts",
                                      advanced=_adv("numlock_by_default", "input.numlock_by_default"))

        g = ctx.group(self.page, "Mouse", "Every pointer: a mouse, a trackball (and a touchpad's speed).")
        self.sens = ctx.scale_row(g, "Speed", "How far the pointer moves for a movement of the mouse", lo=-1, hi=1,
                                  step=0.05, value=1, fmt=lambda v: f"{v:+.2f}", key="sensitivity", debounce=700,
                                  marks=(0,), on_change=lambda v: self._set([("sensitivity", round(v, 2))],
                                                                            f"Pointer speed {v:+.2f}"),
                                  hint="Drag: the pointer's speed, -1 (slow) to 1 (fast); bromigOS starts at 1",
                                  advanced=_adv("sensitivity", "input.sensitivity"))
        self.accel = ctx.combo_row(g, "Acceleration", "Adaptive: a quick flick goes further; flat: the same at every speed", options=[("adaptive", "Adaptive"), ("flat", "Flat")],
                                   key="acceleration", on_select=lambda v: self._set([("accel_profile", v)],
                                                                                     f"Acceleration: {v}"),
                                   hint="Adaptive (a quick flick goes further) or flat (for games and drawing)",
                                   advanced=_adv("accel_profile", "input.accel_profile"))
        self.mnat = ctx.switch_row(g, "Natural scrolling", "The page follows the wheel, like a touchscreen",
                                   key="mouse-natural-scroll",
                                   on_toggle=lambda on: self._set([("mouse_natural_scroll", on)],
                                                                  f"Mouse natural scrolling: {'on' if on else 'off'}"),
                                   hint="Reverses the mouse wheel's direction", advanced=_adv("mouse_natural_scroll",
                                                                                              "input.natural_scroll"))
        self.lefty = ctx.switch_row(g, "Left-handed", "The primary button on the right", key="left-handed",
                                    on_toggle=lambda on: self._set([("left_handed", on)],
                                                                   f"Left-handed: {'on' if on else 'off'}"),
                                    hint="Swaps the left and right buttons", advanced=_adv("left_handed", "input.left_handed"))
        self.scroll = ctx.scale_row(g, "Scroll speed", "How far one notch of the wheel scrolls", lo=0.2, hi=3,
                                    step=0.1, value=1, fmt=lambda v: f"{v:.1f}×", key="scroll-speed", debounce=700,
                                    marks=(1,), on_change=lambda v: self._set([("scroll_factor", round(v, 1))],
                                                                              f"Scroll speed {v:.1f}×"),
                                    hint="Drag: the mouse wheel's speed (1×: as the mouse says)",
                                    advanced=_adv("scroll_factor", "input.scroll_factor"))
        self.focus = ctx.combo_row(g, "Window focus", "", options=FOCUS, key="focus",
                                   on_select=lambda v: self._set([("follow_mouse", int(v))],
                                                                 "Window focus: " + dict(FOCUS)[v].lower()),
                                   hint="Which window gets the keyboard: the one under the pointer, or the one you "
                                        "click", advanced=_adv("follow_mouse", "input.follow_mouse"))

        g = ctx.group(self.page, "Touchpad", key="touchpad")
        self.tp_group = g
        self.tp_note = None

        def sw(title, sub, key, field, hint):
            return ctx.switch_row(g, title, sub, key=key, hint=hint,
                                  on_toggle=lambda on: self._set([(field, on)], f"{title}: {'on' if on else 'off'}"),
                                  advanced=_adv(field, "input.touchpad." + field))
        self.tap = sw("Tap to click", "One finger: click, two: right-click, three: middle", "tap-to-click",
                      "tap_to_click", "A tap clicks, without pressing the pad down")
        self.tnat = sw("Natural scrolling", "The page follows your fingers", "touchpad-natural-scroll",
                       "natural_scroll", "Two-finger scrolling moves the content the way your fingers go")
        self.dwt = sw("Off while typing", "Ignores the pad for a moment after a key", "disable-while-typing",
                      "disable_while_typing", "Stops a palm on the pad from moving the pointer while you type")
        self.click = ctx.combo_row(g, "Clicking", "Pressing the pad: one, two or three fingers; or its corners", options=[("true", "Finger count"), ("false", "Where you press")],
                                   key="click-method",
                                   on_select=lambda v: self._set([("clickfinger_behavior", v == "true")],
                                                                 "Clicking: " + ("by fingers" if v == "true" else "by area")),
                                   hint="Pressing the pad: one finger left, two right, three middle; or the pad's "
                                        "bottom corners as buttons",
                                   advanced=_adv("clickfinger_behavior", "input.touchpad.clickfinger_behavior"))
        self.middle = sw("Both buttons: middle click", "Pressing left and right together", "middle-button",
                         "middle_button_emulation", "Left and right pressed together act as the middle button")
        self.dlock = sw("Drag lock", "A drag carries on when the finger lifts for a moment", "drag-lock", "drag_lock",
                        "Lift a finger mid-drag and the drag holds until the next tap")
        self.tscroll = ctx.scale_row(g, "Scroll speed", "How far two fingers scroll", lo=0.2, hi=3, step=0.1, value=1,
                                     fmt=lambda v: f"{v:.1f}×", key="touchpad-scroll-speed", debounce=700, marks=(1,),
                                     on_change=lambda v: self._set([("touchpad_scroll_factor", round(v, 1))],
                                                                   f"Touchpad scroll speed {v:.1f}×"),
                                     hint="Drag: the touchpad's scrolling speed",
                                     advanced=_adv("touchpad_scroll_factor", "input.touchpad.scroll_factor"))

        g = ctx.group(self.page, "More")
        ctx.row(g, "Shortcuts", "Every key the desktop has, and changing one", key="shortcuts-link",
                activate=lambda: ctx.open_page("shortcuts"), hint="Opens Shortcuts")
        ctx.row(g, "Peripherals", "A keyboard's macro keys, its dial, its lighting", key="peripherals-link",
                activate=lambda: ctx.open_page("peripherals"), hint="Opens Peripherals")

    # ------------------------------------------------------------------ state
    def refresh(self):
        self.ctx.json(CMD + ["--json"], self._got)

    def _got(self, doc, err):
        if not doc or doc.get("ok") is False:
            if self.problem is None:
                self.problem = self.ctx.failed(self.kb_group, CMD + ["--json"], (doc or {}).get("error") or err)
            return
        if self.problem is not None:
            self.kb_group.remove(self.problem)
            self.problem = None
        self.sync(doc)

    def _layouts(self, doc, err):
        if not doc or doc.get("ok") is False:
            return
        self.lay = doc
        opts = [(x["code"], f"{x['name']} ({x['code']})") for x in doc["layouts"]]
        self.layout.set_options(opts)
        self.layout2.set_options([("", "None")] + opts)
        self.switch.set_options([(x["code"], x["name"]) for x in doc["switch_keys"]])
        caps = [("", "Caps Lock")] + [(x["code"], CAPS_LABEL.get(x["code"], x["name"])) for x in doc["caps"]]
        self.caps.set_options(caps)
        if self.doc:
            self.sync(self.doc)

    def _parts(self, v=None):
        v = v or (self.doc or {}).get("values") or {}
        lays = (v.get("kb_layout") or "us").split(",")
        vars_ = (v.get("kb_variant") or "").split(",")
        vars_ += [""] * (len(lays) - len(vars_))
        opts = [o for o in (v.get("kb_options") or "").split(",") if o]
        return lays, vars_, opts

    def sync(self, d):
        self.doc = d
        v = d["values"]
        lays, vars_, opts = self._parts(v)
        if self.lay:
            self.layout.set_quiet(lays[0])
            lay = next((x for x in self.lay["layouts"] if x["code"] == lays[0]), None)
            self.variant.set_options([("", "Standard")] + [(x["code"], x["name"]) for x in (lay or {}).get("variants", [])],
                                     vars_[0])
            self.layout2.set_quiet(lays[1] if len(lays) > 1 else "")
            grp = next((o for o in opts if o.startswith("grp:")), None)
            self.switch.set_quiet(grp)
            caps = next((o for o in opts if o.startswith("caps:") or o in ("ctrl:nocaps", "ctrl:swapcaps")), "")
            self.caps.set_quiet(caps)
        self.layout.set_subtitle(GLib.markup_escape_text("In force: " + ", ".join(lays)) if len(lays) > 1 else "")
        self.switch.set_sensitive(len(lays) > 1)
        self.switch.set_subtitle("" if len(lays) > 1 else "Pick a second layout first")
        self.rate.set_quiet(v["repeat_rate"])
        self.delay.set_quiet(v["repeat_delay"])
        self.numlock.set_quiet(v["numlock_by_default"])
        self.sens.set_quiet(v["sensitivity"])
        self.accel.set_quiet(v["accel_profile"])
        self.mnat.set_quiet(v["mouse_natural_scroll"])
        self.lefty.set_quiet(v["left_handed"])
        self.scroll.set_quiet(v["scroll_factor"])
        self.focus.set_quiet(str(v["follow_mouse"]))
        self.tap.set_quiet(v["tap_to_click"])
        self.tnat.set_quiet(v["natural_scroll"])
        self.dwt.set_quiet(v["disable_while_typing"])
        self.click.set_quiet("true" if v["clickfinger_behavior"] else "false")
        self.middle.set_quiet(v["middle_button_emulation"])
        self.dlock.set_quiet(v["drag_lock"])
        self.tscroll.set_quiet(v["touchpad_scroll_factor"])
        tps = d.get("touchpads") or []
        self.tp_group.set_description("Connected: " + ", ".join(tps) if tps else
                                      "No touchpad is connected now: these apply to one when it is.")

    # ------------------------------------------------------------------ changes
    def _set(self, pairs, said):
        yours = (self.doc or {}).get("yours") or {}
        argv, undo = list(CMD), list(CMD)
        for k, val in pairs:
            argv += ["--unset", k] if val is None else ["--set", k, _lit(val)]
            undo += ["--set", k, _lit(yours[k])] if k in yours else ["--unset", k]
        self.ctx.change(argv + ["--json"], said, undo=undo + ["--json"], done=self.sync,
                        failed=lambda *_: self.refresh())

    def _layout(self, i, code):
        lays, vars_, opts = self._parts()
        if i == 0:
            if code == lays[0]:
                return
            lays[0], vars_[0] = code, ""
        else:
            cur = lays[1] if len(lays) > 1 else ""
            if code == cur:
                return
            lays, vars_ = (lays[:1] + [code], vars_[:1] + [""]) if code else (lays[:1], vars_[:1])
            if code and not any(o.startswith("grp:") for o in opts):
                opts.append("grp:alt_shift_toggle")
            if not code:
                opts = [o for o in opts if not o.startswith("grp:")]
        pairs = [("kb_layout", ",".join(lays)), ("kb_variant", ",".join(vars_) if any(vars_) else None),
                 ("kb_options", ",".join(opts) if opts else None)]
        self._set(pairs, "Layout: " + ",".join(lays) + (" (Alt+Shift switches)" if i == 1 and code
                                                         and "grp:alt_shift_toggle" in opts else ""))

    def _variant(self, i, code):
        lays, vars_, _ = self._parts()
        if vars_[i] == code:
            return
        vars_[i] = code
        self._set([("kb_variant", ",".join(vars_) if any(vars_) else None)], f"Variant: {code or 'standard'}")

    def _options(self, keep, new, said):
        _, _, opts = self._parts()
        opts = [o for o in opts if keep(o)] + ([new] if new else [])
        self._set([("kb_options", ",".join(opts) if opts else None)], said)

    def _switch_key(self, code):
        self._options(lambda o: not o.startswith("grp:"), code, "Layouts switch with " + code.split(":")[-1])

    def _caps(self, code):
        self._options(lambda o: not (o.startswith("caps:") or o in ("ctrl:nocaps", "ctrl:swapcaps")), code,
                      "Caps Lock key: " + CAPS_LABEL.get(code, code))

    def reset(self):
        yours = (self.doc or {}).get("yours") or {}
        undo = list(CMD)
        for k, val in yours.items():
            undo += ["--set", k, _lit(val)]
        self.ctx.change(CMD + ["--reset", "--json"], lambda d: d.get("said"),
                        undo=(undo + ["--json"]) if yours else None, done=self.sync)
        return None


def build(ctx):
    p = InputPage(ctx)
    p.page._input = p
    return p.page


def refresh(widget):
    widget._input.refresh()


PAGE = Page(
    id="input", title="Keyboard & input", group="system", order=60, build=build, refresh=refresh,
    docs="settings.md#keyboard-and-input", icon="input-keyboard-symbolic input-mouse-symbolic",
    summary="layout, repeat, mouse, touchpad",
    intro="The keyboard layout, key repeat and what Caps Lock does; the mouse and the touchpad. Saved into your "
          "hyprland.lua and taken by Hyprland at once.",
    keywords=["keyboard", "mouse", "touchpad", "trackpad", "pointer", "xkb", "hyprland input"],
    entries=[
        Entry("layout", "Keyboard layout", ["keymap", "language", "xkb", "qwerty", "azerty"], "Keyboard"),
        Entry("variant", "Keyboard variant", ["dvorak", "colemak", "dead keys", "international"], "Keyboard"),
        Entry("layout2", "Second keyboard layout", ["another language", "two layouts", "switch layout"], "Keyboard"),
        Entry("switch-key", "Switch layouts with", ["layout switch", "alt shift", "grp"], "Keyboard"),
        Entry("repeat-rate", "Key repeat rate", ["repeat", "typematic", "key speed"], "Keyboard"),
        Entry("repeat-delay", "Key repeat delay", ["repeat", "delay", "hold"], "Keyboard"),
        Entry("try", "Try the key repeat", ["test typing"], "Keyboard"),
        Entry("caps", "Caps Lock key", ["capslock", "caps", "escape", "ctrl", "remap"], "Keyboard"),
        Entry("numlock", "Num Lock on at start", ["numpad", "number pad"], "Keyboard"),
        Entry("sensitivity", "Pointer speed", ["mouse speed", "sensitivity", "dpi", "cursor speed"], "Mouse"),
        Entry("acceleration", "Pointer acceleration", ["accel", "flat", "adaptive", "mouse acceleration"], "Mouse"),
        Entry("mouse-natural-scroll", "Mouse natural scrolling", ["reverse scroll", "wheel direction"], "Mouse"),
        Entry("left-handed", "Left-handed mouse", ["swap buttons", "lefty"], "Mouse"),
        Entry("scroll-speed", "Mouse scroll speed", ["wheel speed", "scroll factor"], "Mouse"),
        Entry("focus", "Which window gets the keys", ["focus follows mouse", "click to focus", "window focus"], "Mouse"),
        Entry("touchpad", "Touchpad", ["trackpad"], "Touchpad"),
        Entry("tap-to-click", "Tap to click", ["tap", "touchpad click"], "Touchpad"),
        Entry("touchpad-natural-scroll", "Touchpad natural scrolling", ["reverse scroll", "two finger scroll"],
              "Touchpad"),
        Entry("disable-while-typing", "Touchpad off while typing", ["palm rejection", "dwt"], "Touchpad"),
        Entry("click-method", "Touchpad clicking", ["clickfinger", "button areas", "right click"], "Touchpad"),
        Entry("middle-button", "Middle click on the touchpad", ["middle button emulation", "paste"], "Touchpad"),
        Entry("drag-lock", "Touchpad drag lock", ["drag", "lift"], "Touchpad"),
        Entry("touchpad-scroll-speed", "Touchpad scroll speed", ["scroll factor"], "Touchpad"),
    ])
