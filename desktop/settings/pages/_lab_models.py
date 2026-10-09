"""Lab models: the configuration planner, the upgrade policy and the catalog (docs/lab-models.md).

A section the Lab page (lab.py) embeds with build_section(ctx, page) (a leading underscore:
the registry doesn't take it for a page of its own). Every control saves to ~/.config/bromigos/lab.toml at once (through a
symlink, if it is one) and re-plans: `bromigos lab models plan --json` with the same inputs.
Nothing here installs or changes a model: provisioning and upgrades go through the homelab
repo (Phase 2 and 3).
"""
import json
import os
import sys

from gi.repository import Adw, GLib, Gtk

_CHECKOUT = os.path.normpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "..", "homelab", "lib"))
if os.path.isdir(_CHECKOUT) and _CHECKOUT not in sys.path:
    sys.path.insert(0, _CHECKOUT)                                  # a checkout: its own bromigos_homelab first
if os.path.isdir("/usr/lib/bromigos/lib") and "/usr/lib/bromigos/lib" not in sys.path:
    sys.path.append("/usr/lib/bromigos/lib")
try:
    from bromigos_homelab import catalog as C                     # noqa: E402
except Exception:                                                  # noqa: BLE001 - shown as a note
    C = None

TITLES = {"llm": "VECTOR's brain (LLM)", "code": "Coding LLM", "embed": "Embeddings (memory)",
          "image": "Images", "image-edit": "Image edits", "cutout": "Cutouts", "upscale": "Upscaling",
          "video": "Video", "3d": "3D models", "tts": "Voice (TTS)", "stt": "Hearing (STT)",
          "ocr": "OCR and documents", "vision": "Screen understanding"}
# what each capability is for, in the hover hints of its switches
JOBS = {"llm": "VECTOR's brain, the LLM he and your other agents think with",
        "code": "a coding LLM for your coding tools", "embed": "the embeddings VECTOR's memory searches with",
        "image": "image generation", "image-edit": "image editing", "cutout": "background removal (cutouts)",
        "upscale": "upscaling", "video": "video (loops, image and text to video)",
        "3d": "image to 3D (the holograms' meshes)", "tts": "VECTOR's voice (text to speech)",
        "stt": "hearing (speech to text)", "ocr": "OCR and document parsing",
        "vision": "screen understanding (reading what's on screen)"}
GOAL_NAMES = [("quality", "Best quality"), ("balanced", "Balanced"), ("speed", "Fastest")]
LLM_GOALS = GOAL_NAMES + [("throughput", "Many agents")]
PRIORITIES = [("balanced", "Balanced"), ("brain", "Brain first"), ("media", "Media first"),
              ("voice", "Voice first"), ("resident", "Everything resident")]
LICENCES = [("any", "Any licence (research and non-commercial too)"), ("commercial", "Commercial use allowed"),
            ("permissive", "Permissive only (Apache, MIT, CC-BY)")]
REGIONS = [("", "From the time zone"), ("US", "United States"), ("EU", "European Union"), ("UK", "United Kingdom"),
           ("KR", "South Korea"), ("CN", "China"), ("JP", "Japan"), ("CA", "Canada"), ("AU", "Australia")]
CLIENTS = [1, 2, 4, 8, 16, 32, 64]
CONTEXTS = [("8k", "8k"), ("32k", "32k"), ("64k", "64k"), ("128k", "128k"), ("256k", "256k")]
POLICIES = [("off", "Off"), ("safe", "Safe: newer or better-quantised, same family"),
            ("any", "Any better pick")]


def _cmd(*args):
    """`bromigos lab models …`, or the module itself before the console's command exists."""
    return ["bromigos", "lab", "models", *args]


def _fallback(*args):
    return ["env", "PYTHONPATH=/usr/lib/bromigos/lib", sys.executable or "python3", "-m", "bromigos_homelab.catalog",
            *args]


def _enable_switch(row):
    """The Gtk.Switch an Adw.ExpanderRow shows with set_show_enable_switch (it has no getter)."""
    stack = [row.get_first_child()]
    while stack:
        w = stack.pop()
        while w is not None:
            if isinstance(w, Gtk.Switch):
                return w
            stack.append(w.get_first_child())
            w = w.get_next_sibling()
    return None


def _dropdown(ctx, items, current, hint, on_change):
    dd = Gtk.DropDown.new_from_strings([label for _, label in items])
    keys = [k for k, _ in items]
    dd.set_selected(keys.index(current) if current in keys else 0)
    dd.set_valign(Gtk.Align.CENTER)
    ctx.hint(dd, hint)
    dd.connect("notify::selected", lambda d, _p: on_change(keys[d.get_selected()]))
    return dd


class Section:
    def __init__(self, ctx, page):
        self.ctx, self.page = ctx, page
        s = C.read_settings() if C else {}
        self.plan_s = dict(s.get("plan") or {})
        self.up_s = dict(s.get("upgrade") or {})
        self.bench_s = dict(s.get("bench") or {})
        self.hardware = []
        self.pending_plan = None
        self.result_rows = []
        self.use_fallback = not ctx.has_command("lab")

    # ------------------------------------------------------------------ running
    def json(self, args, done):
        argv = _fallback(*args) if self.use_fallback else _cmd(*args)
        self.ctx.json(argv, done)

    def save(self, section, values):
        if not C:
            return
        try:
            C.save_settings(section, values)
        except Exception as e:                                     # noqa: BLE001
            self.ctx.toast(f"couldn't save lab.toml: {e}")

    # ------------------------------------------------------------------ build
    def build(self):
        if C is None:
            g = self.ctx.group(self.page, "Lab models")
            self.ctx.note(g, "bromigos-homelab isn't installed: the model catalog and planner come with it", "warn")
            return
        self._plan_inputs()
        self._results()
        self._upgrades()
        self._catalog()
        self.replan()

    def _plan_inputs(self):
        g = self.ctx.group(self.page, "Plan", "What runs where: give each GPU a budget, choose what stays loaded, "
                                              "and how to trade quality for speed. The configurations below update "
                                              "as you change anything.",
                           hint="bromigos lab models plan, with these inputs (saved in ~/.config/bromigos/lab.toml)")
        self.gpu_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.gpu_box.add_css_class("boxed-list")
        wait = Adw.ActionRow(title="Finding the lab's GPUs and this machine's…")
        self.gpu_box.append(wait)
        self.ctx.hint(self.gpu_box, "Each GPU's budget: the most VRAM the lab may use on it")
        g.add(self.gpu_box)
        pri = Adw.ActionRow(title="Priority", subtitle="Which configuration comes first")
        pri.add_suffix(_dropdown(self.ctx, PRIORITIES, self.plan_s.get("priority", "balanced"),
                                 "Balanced weighs everything; the others give their part the best models",
                                 lambda v: self.set_plan("priority", v)))
        self.ctx.hint(pri, "The planner always shows two to four configurations; this one is listed first")
        g.add(pri)
        lic = Adw.ActionRow(title="Licences", subtitle="Which model licences the planner may pick")
        lic.add_suffix(_dropdown(self.ctx, LICENCES, self.plan_s.get("licence", "any"),
                                 "A setting, not a judgement: research licences are fine for a personal lab, "
                                 "not for work you sell", lambda v: self.set_plan("licence", v)))
        self.ctx.hint(lic, "Commercial: the licence allows commercial use (maybe with conditions). Permissive: "
                           "Apache, MIT, CC-BY class, no conditions")
        g.add(lic)
        reg = Adw.ActionRow(title="Where you are", subtitle="Some licences exclude regions (the EU, UK, South Korea, "
                                                            "the US)")
        reg.add_suffix(_dropdown(self.ctx, REGIONS, self.plan_s.get("region") or "",
                                 "Models whose licence doesn't cover your region are left out",
                                 lambda v: self.set_plan("region", v or None)))
        self.ctx.hint(reg, "Tencent's Hunyuan licence excludes the EU, UK and South Korea; MiniMax H3's also the US")
        g.add(reg)
        g2 = self.ctx.group(self.page, "Capabilities", "On: plan it. Always on: it stays loaded (voice, the brain); "
                                                       "otherwise it loads when a job needs it and unloads when idle.")
        wants = set(self.plan_s.get("wants") or C.DEFAULT_WANTS)
        always = self.plan_s.get("always")
        cat = C.load()
        always = set(always if always is not None else [c for c in wants if cat.caps[c].residency == "always"])
        goals = dict(self.plan_s.get("goals") or {})
        self.wants, self.always, self.goals = wants, always, goals
        for cap in C.CAPABILITIES:
            row = Adw.ExpanderRow(title=TITLES.get(cap, cap), subtitle=cat.caps[cap].title)
            row.set_show_enable_switch(True)
            row.set_enable_expansion(cap in wants)
            row.connect("notify::enable-expansion", lambda r, _p, c=cap: self.toggle_want(c, r.get_enable_expansion()))
            job = JOBS.get(cap, TITLES.get(cap, cap))
            self.ctx.hint(row, f"Plan {TITLES.get(cap, cap).lower()}: the switch includes it; open it for its goal "
                               "and whether it stays loaded")
            sw = _enable_switch(row)
            if sw is not None:
                self.ctx.hint(sw, f"Give {job} a model and a GPU in the plan; off, the planner leaves it out "
                                  "(nothing on the lab changes)")
            res = Adw.SwitchRow(title="Always on", subtitle="Stays loaded: no cold start, but its VRAM is never free")
            res.set_active(cap in always)
            res.connect("notify::active", lambda r, _p, c=cap: self.toggle_always(c, r.get_active()))
            self.ctx.hint(res, f"Keep {job} loaded all the time (no cold start, its VRAM never free), or load it "
                               "only when a job needs it and unload it when idle")
            row.add_row(res)
            gr = Adw.ActionRow(title="Goal", subtitle="Best quality, balanced, or fastest")
            items = LLM_GOALS if cap in ("llm", "code") else GOAL_NAMES
            gr.add_suffix(_dropdown(self.ctx, items, goals.get(cap, self.plan_s.get("goal", "balanced")),
                                    "Best quality: the strongest model and least compression that fits. Fastest: "
                                    "smaller, distilled, kept loaded. Many agents: throughput for many clients",
                                    lambda v, c=cap: self.set_goal(c, v)))
            self.ctx.hint(gr, "How this capability trades quality for speed")
            row.add_row(gr)
            if cap == "llm":
                ag = Adw.ActionRow(title="Agents at once", subtitle="How many clients hit the LLM together")
                scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, len(CLIENTS) - 1, 1)
                scale.set_draw_value(False)
                scale.set_size_request(220, -1)
                scale.set_valign(Gtk.Align.CENTER)
                cur = int(self.plan_s.get("clients") or 1)
                scale.set_value(min(range(len(CLIENTS)), key=lambda i: abs(CLIENTS[i] - cur)))
                lab = Gtk.Label(label=str(cur), xalign=1)
                lab.add_css_class("bromigos-value")
                self.ctx.hint(scale, "VECTOR, other agents, coding tools, batch jobs: the KV cache grows with each, "
                                     "and a batching server (vLLM) serves many far better than llama.cpp")
                self.ctx.hint(lab, "Clients at once")

                def slid(s, lab=lab):
                    n = CLIENTS[int(round(s.get_value()))]
                    lab.set_label(str(n))
                    self.set_plan("clients", n)
                scale.connect("value-changed", slid)
                box = Gtk.Box(spacing=12)
                box.append(scale)
                box.append(lab)
                ag.add_suffix(box)
                self.ctx.hint(ag, "The plan sizes the LLM's KV cache for this many and shows tokens/s each and in all")
                row.add_row(ag)
                cx = Adw.ActionRow(title="Context", subtitle="The longest prompt an agent sends (VECTOR's tools want "
                                                             "long context)")
                cx.add_suffix(_dropdown(self.ctx, CONTEXTS, self.plan_s.get("context") or "32k",
                                        "Longer context: more KV cache per client",
                                        lambda v: self.set_plan("context", v)))
                self.ctx.hint(cx, "Each client may need up to this many tokens of context")
                row.add_row(cx)
            g2.add(row)

    def _results(self):
        self.res_group = self.ctx.group(self.page, "Configurations",
                                        "Ranked; each says what goes on which GPU, what stays loaded and what swaps, "
                                        "peak VRAM against each budget, and what it gives up.")
        self.res_note = Adw.ActionRow(title="Planning…")
        self.res_group.add(self.res_note)

    def _upgrades(self):
        g = self.ctx.group(self.page, "Upgrades", "Opt in, per capability. Until you choose Apply, a better model is "
                                                  "only announced. Applying lands with the homelab repo's GitOps "
                                                  "(Phase 2): deployed beside the old one, tested, then switched.")
        on = Adw.SwitchRow(title="Model upgrades", subtitle="Off: nothing is proposed or applied")
        on.set_active(bool(self.up_s.get("enabled", False)))
        on.connect("notify::active", lambda r, _p: self.set_up("enabled", r.get_active()))
        self.ctx.hint(on, "The global switch for the upgrade policy below")
        g.add(on)
        act = Adw.ActionRow(title="When one is better", subtitle="Tell me (default), or apply it in quiet hours")
        act.add_suffix(_dropdown(self.ctx, [("notify", "Tell me"), ("apply", "Apply (Phase 2)")],
                                 self.up_s.get("action", "notify"),
                                 "Apply goes through a pull request to your homelab repo, never a hand edit",
                                 lambda v: self.set_up("action", v)))
        self.ctx.hint(act, "Notify: a quiet notification and the preview below. Apply: Phase 2's lab models replace")
        g.add(act)
        q = Adw.EntryRow(title="Quiet hours (HH:MM-HH:MM)")
        q.set_text(self.up_s.get("quiet_hours", "01:00-06:00"))
        q.set_show_apply_button(True)
        q.connect("apply", lambda r: self.set_up("quiet_hours", r.get_text().strip()))
        self.ctx.hint(q, "When an upgrade may apply (local time); it may wrap midnight")
        g.add(q)
        pol = Adw.ExpanderRow(title="Per capability", subtitle="Off, Safe or Any for each")
        self.ctx.hint(pol, "Safe: a newer version or better quantisation of the same model family. Any: any catalog "
                           "pick that beats the current one, within the budget, goal and licence filter")
        policy = dict(self.up_s.get("policy") or {})
        for cap in C.CAPABILITIES:
            r = Adw.ActionRow(title=TITLES.get(cap, cap))
            r.add_suffix(_dropdown(self.ctx, POLICIES, policy.get(cap, "off"), f"The upgrade policy for {cap}",
                                   lambda v, c=cap: self.set_policy(c, v)))
            self.ctx.hint(r, f"What may replace the {cap} model this lab runs")
            pol.add_row(r)
        g.add(pol)
        self.up_preview = Adw.ExpanderRow(title="What would upgrade now", subtitle="Press Check")
        self.up_preview.add_suffix(self.ctx.button("Check", self.preview_upgrades,
                                                   "Runs bromigos lab models upgrades: proposals with their reason, "
                                                   "gain and cost; nothing changes"))
        self.ctx.hint(self.up_preview, "The policy's proposals for this lab right now")
        g.add(self.up_preview)

    def _catalog(self):
        g = self.ctx.group(self.page, "Catalog", "The researched list of models per capability and size "
                                                 "(bromigos-lab-catalog; refreshed weekly).")
        try:
            cat = C.load()
            sub = f"version {cat.version} · researched {cat.researched} · refreshed {cat.refreshed}"
            pend = [p for p in cat.pending if p.get("state", "pending review") == "pending review"]
        except Exception as e:                                     # noqa: BLE001
            sub, pend = f"not readable: {e}", []
        self.ctx.row(g, "Model catalog", sub, hint="Where the picks come from (docs/lab-models.md)",
                     buttons=[("Refresh", self.refresh, "Fetch the newest signed catalog from bromigOS's package "
                                                        "repository (bromigos lab models refresh)")])
        if pend:
            self.ctx.row(g, "Pending review", f"{len(pend)} candidates the weekly refresh found",
                         hint="\n".join(f"{p.get('capability', '')}: {p.get('title', '')}" for p in pend[:12]))
        bench = Adw.SwitchRow(title="Bench candidates on the lab",
                              subtitle="When a lab GPU is idle, load a candidate, run one fixed test, measure VRAM "
                                       "and speed, unload. Off by default.")
        bench.set_active(bool(self.bench_s.get("enabled", False)))
        bench.connect("notify::active", lambda r, _p: self.set_bench(r.get_active()))
        self.ctx.hint(bench, "The catalog-bench job: one at a time through the lab's queue, never crowding the "
                             "voice service; measured numbers replace estimates for your hardware")
        g.add(bench)

    # ------------------------------------------------------------------ changes
    def set_plan(self, k, v):
        self.plan_s[k] = v
        self.save("plan", self.plan_s)
        self.replan()

    def set_goal(self, cap, v):
        self.goals[cap] = v
        self.set_plan("goals", dict(self.goals))

    def toggle_want(self, cap, on):
        (self.wants.add if on else self.wants.discard)(cap)
        self.set_plan("wants", [c for c in C.CAPABILITIES if c in self.wants])

    def toggle_always(self, cap, on):
        (self.always.add if on else self.always.discard)(cap)
        self.set_plan("always", [c for c in C.CAPABILITIES if c in self.always])

    def set_budget(self, key, gib, label):
        label.set_label(f"{gib:.0f} GiB")
        b = dict(self.plan_s.get("budgets") or {})
        b[key] = round(gib, 1)
        self.set_plan("budgets", b)

    def set_up(self, k, v):
        self.up_s[k] = v
        self.save("upgrade", self.up_s)

    def set_policy(self, cap, v):
        p = dict(self.up_s.get("policy") or {})
        p[cap] = v
        self.set_up("policy", {k: x for k, x in p.items() if x != "off"})

    def set_bench(self, on):
        self.bench_s["enabled"] = bool(on)
        self.save("bench", self.bench_s)
        self.ctx.toast("The lab may bench catalog candidates when idle" if on else "Catalog bench off")

    # ------------------------------------------------------------------ the plan
    def replan(self):
        if self.pending_plan:
            GLib.source_remove(self.pending_plan)
        self.pending_plan = GLib.timeout_add(450, self._run_plan)

    def _run_plan(self):
        self.pending_plan = None
        self.res_note.set_title("Planning…")
        self.json(["plan", "--json"], self._planned)
        return False

    def _planned(self, doc, err):
        for r in self.result_rows:
            self.res_group.remove(r)
        self.result_rows = []
        if not doc:
            self.res_note.set_title(f"The planner didn't answer: {err or 'no output'}")
            return
        self.res_note.set_title(f"Catalog researched {doc['catalog']['researched']} · LLM load: "
                                f"{doc['load']['clients']} client(s), {doc['load']['context'] // 1024}k context")
        if not self.hardware:
            self._gpus(doc["hardware"])
        for n, c in enumerate(doc["configurations"], 1):
            row = Adw.ExpanderRow(title=f"{n}. {c['name']}", subtitle=c["sacrifice"])
            row.set_subtitle_lines(3)
            self.ctx.hint(row, f"{c['aim']}. Open it for each GPU's peak and each model's place")
            for d in c["devices"]:
                r = Adw.ActionRow(title=f"{d['name']}: peak {d['peak_gib']:.1f} of {d['budget_gib']:.1f} GiB",
                                  subtitle=f"resident {d['resident_gib']:.1f} GiB · headroom {d['headroom_gib']:.1f} "
                                           f"GiB · swaps: {', '.join(d['swaps']) or 'none'}")
                r.set_subtitle_lines(3)
                self.ctx.hint(r, "Resident models stay loaded; the on-demand ones load one at a time beside them")
                row.add_row(r)
            for p in c["placements"]:
                if p.get("shared_with"):
                    sub = f"the {p['shared_with']} model serves it too"
                else:
                    sub = (f"{p['quant']} · {p['runtime']} · {'+'.join(p['device_names'])} · "
                           f"{p['per_gpu_gib']:.1f} GiB · {'stays loaded' if p['resident'] else 'on demand'} · "
                           f"{p['speed_text']} · {p['licence_plain']}")
                r = Adw.ActionRow(title=f"{TITLES.get(p['capability'], p['capability'])}: {p['name']}", subtitle=sub)
                r.set_subtitle_lines(3)
                self.ctx.hint(r, p.get("why") or "")
                row.add_row(r)
            for m in c["missing"]:
                r = Adw.ActionRow(title=f"{TITLES.get(m['capability'], m['capability'])}: none", subtitle=m["why"])
                self.ctx.hint(r, "Raise a budget, turn something off, or let it load on demand")
                row.add_row(r)
            self.res_group.add(row)
            self.result_rows.append(row)

    def _gpus(self, hardware):
        self.hardware = [d for d in hardware if d["vendor"] != "cpu"]
        while (r := self.gpu_box.get_row_at_index(0)) is not None:
            self.gpu_box.remove(r)
        if not self.hardware:
            self.gpu_box.append(Adw.ActionRow(title="No GPU found: the plan uses the CPU"))
            return
        budgets = dict(self.plan_s.get("budgets") or {})
        for d in self.hardware:
            row = Adw.ActionRow(title=d["name"] + (" (this machine, your screen)" if d["desktop"] else ""),
                                subtitle=f"{d['vram_gib']:.0f} GiB{' unified memory' if d['unified'] else ''}")
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, max(1.0, round(d["vram_gib"])), 1)
            scale.set_draw_value(False)
            scale.set_size_request(240, -1)
            scale.set_valign(Gtk.Align.CENTER)
            scale.set_value(float(budgets.get(d["key"], d["budget_gib"])))
            lab = Gtk.Label(label=f"{scale.get_value():.0f} GiB", xalign=1)
            lab.add_css_class("bromigos-value")
            self.ctx.hint(scale, "Drag: the most VRAM the lab may use here. On a card you game on, leave what your "
                                 "games need")
            self.ctx.hint(lab, "This GPU's budget")
            scale.connect("value-changed", lambda s, k=d["key"], lab=lab: self.set_budget(k, s.get_value(), lab))
            box = Gtk.Box(spacing=12)
            box.append(scale)
            box.append(lab)
            row.add_suffix(box)
            self.ctx.hint(row, f"{d['name']}: saved by its name ({d['key']}), never its host")
            self.gpu_box.append(row)

    # ------------------------------------------------------------------ upgrades, refresh
    def preview_upgrades(self):
        self.up_preview.set_subtitle("Checking…")

        def done(doc, err):
            if not doc:
                self.up_preview.set_subtitle(f"didn't answer: {err}")
                return
            ps = doc.get("proposals") or []
            self.up_preview.set_subtitle(f"{len(ps)} proposal(s)" if ps else "nothing to upgrade under this policy")
            for p in ps:
                r = Adw.ActionRow(title=f"{p['capability']}: {p['from']} → {p['to']}",
                                  subtitle=f"{p['reason']} · {p['action']}")
                r.set_subtitle_lines(4)
                self.ctx.hint(r, f"{p['kind']}; licence {p['licence']} ({p['licence_plain']})")
                self.up_preview.add_row(r)
            self.up_preview.set_expanded(bool(ps))
        self.json(["upgrades", "--json"], done)

    def refresh(self):
        self.ctx.toast("Fetching the newest signed catalog…")

        def done(doc, err):
            f = (doc or {}).get("fetch") or {}
            self.ctx.toast("Catalog: " + (f"updated to version {f.get('version')}" if f.get("updated")
                                          else (f.get("why") or err or "no answer")))
            if f.get("updated"):
                self.replan()
        self.json(["refresh", "--json"], done)


def build_section(ctx, page):
    """For the Lab page: the planner, upgrades and catalog groups, added to `page`."""
    s = Section(ctx, page)
    s.build()
    return s


