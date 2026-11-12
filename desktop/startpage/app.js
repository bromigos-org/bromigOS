// Bromigos start page: clock, search, and the snapshot written by snapshot.py
// (data.js, refreshed every minute by bromigos-startpage.timer).
"use strict";

const ENGINES = {
  google: { name: "Google", url: "https://www.google.com/search?q=" },
  ddg: { name: "DuckDuckGo", url: "https://duckduckgo.com/?q=" },
};
const STALE_S = 180; // snapshot older than this: statuses go grey

const $ = (id) => document.getElementById(id);
const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private window */ } },
};

// ---------------------------------------------------------------- clock
const DAYS = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
const pad = (n) => String(n).padStart(2, "0");
function tick() {
  const d = new Date();
  $("time").textContent = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  $("date").textContent = `${DAYS[d.getDay()]} ${pad(d.getDate())} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}
tick();
setInterval(tick, 1000);

// ---------------------------------------------------------------- search
// Default follows the browser's own engine: LibreWolf ships DuckDuckGo,
// Chrome here is set to Google. A choice made in the menu is remembered.
const isGecko = navigator.userAgent.includes("Firefox/");
const engineSel = $("engine");
engineSel.value = store.get("engine") in ENGINES ? store.get("engine") : (isGecko ? "ddg" : "google");
engineSel.addEventListener("change", () => store.set("engine", engineSel.value));
$("search").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("q").value.trim();
  if (!q) return;
  // A bare URL or host goes straight there.
  if (/^https?:\/\//i.test(q)) { location.href = q; return; }
  if (/^[\w-]+(\.[\w-]+)+(:\d+)?(\/\S*)?$/.test(q) && !q.includes(" ")) { location.href = "https://" + q; return; }
  location.href = ENGINES[engineSel.value].url + encodeURIComponent(q);
});
document.addEventListener("keydown", (e) => {
  if (e.key === "/" && document.activeElement !== $("q")) { e.preventDefault(); $("q").focus(); }
});

// ---------------------------------------------------------------- snapshot
function el(tag, attrs, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") n.className = v; else n.setAttribute(k, v);
  }
  for (const k of kids) n.append(k);
  return n;
}
function ago(sec) {
  if (sec < 90) return `${Math.max(0, Math.round(sec))} s ago`;
  if (sec < 5400) return `${Math.round(sec / 60)} min ago`;
  if (sec < 172800) return `${Math.round(sec / 3600)} h ago`;
  return `${Math.round(sec / 86400)} d ago`;
}
function rate(bps) {
  if (bps == null) return "-";
  const u = ["B/s", "KB/s", "MB/s", "GB/s"];
  let i = 0;
  while (bps >= 1000 && i < u.length - 1) { bps /= 1000; i++; }
  return `${bps.toFixed(i ? 1 : 0)} ${u[i]}`;
}
const num = (v, digits = 0) => (v == null ? "-" : Number(v).toFixed(digits));

function renderSwitchboard(s, stale) {
  const box = $("tiles");
  box.replaceChildren();
  for (const t of s.switchboard || []) {
    const state = stale || t.up == null ? "unknown" : (t.up ? "up" : "down");
    const word = { up: "answering", down: "not answering", unknown: "status unknown" }[state];
    box.append(el("a", { class: "tile", href: t.url, title: `${t.name}: ${t.role}. Opens ${t.url} (${word})` },
      el("span", { class: `dot ${state}` }),
      el("span", {}, el("b", {}, t.name), el("small", {}, t.role))));
  }
  const ups = (s.switchboard || []).filter((t) => t.up).length;
  $("sw-meta").textContent = stale ? "STATUS STALE" : `${ups}/${(s.switchboard || []).length} UP`;
  $("sw-meta").title = "Answering links. Dots: green answering, red not, grey unknown or stale.";
}

function row(label, value, hint, cls) {
  return [el("dt", { title: hint }, label), el("dd", { title: hint, class: cls || "" }, ...value)];
}

function renderLab(s, stale) {
  const box = $("readouts");
  box.replaceChildren();
  const lab = s.lab || {};
  const m = lab.summary;
  const link = $("lab-link");
  if (link && lab.url) {
    link.href = lab.url;
    link.closest("h2").title = `Lab status from ${lab.source || lab.url}, read on this machine every minute`;
  }
  const meta = $("lab-meta");
  if (!m) {
    const why = {
      "no-token": `No read-only token at ~/.local/share/bromigos/lab-token${lab.token_vault ? ` (Vault ${lab.token_vault})` : ""}; run bromigos secrets sync.`,
      unconfigured: "No lab configured: bromigos setup homelab (or a lab source in ~/.config/bromigos/homelab.toml).",
      unauthorized: "The Lab refused the token (401/403).",
      down: `${lab.url || "The Lab"} did not answer.`,
    }[lab.state] || `The Lab answered ${lab.state}.`;
    meta.textContent = "NO DATA";
    meta.className = "meta bad";
    box.append(...row("STATUS", [why], "Why there are no Lab numbers", "bad"));
    return;
  }
  const labAge = s.at - (m.generatedAt || 0);
  meta.textContent = lab.state === "stale" || stale ? "STALE" : "LIVE";
  meta.className = "meta" + (lab.state === "stale" || stale ? " warn" : "");
  meta.title = `The Lab generated this snapshot ${ago(labAge)} before it was read`;
  const b = (t) => el("b", {}, String(t));
  box.append(
    ...row("NODES", [b(`${m.nodesReady}/${m.nodesTotal}`), " ready"], "Kubernetes nodes Ready / total",
      m.nodesReady < m.nodesTotal ? "bad" : ""),
    ...row("PODS", [b(num(m.podsRunning)), " running", m.podsNotRunning ? `, ${num(m.podsNotRunning)} not` : ""],
      "Pods running, and pods not running", m.podsNotRunning ? "warn" : ""),
    ...row("ALERTS", [b(num(m.alertsFiring)), " firing"], "Alertmanager alerts firing now (Grafana / Alertmanager for detail)",
      m.alertsFiring ? "warn" : ""),
    ...row("ARGO CD", [b(`${m.argoHealthy}/${m.argoTotal}`), " healthy"], "Argo CD applications healthy / total",
      m.argoHealthy < m.argoTotal ? "warn" : ""),
    ...row("SERVICES", [b(`${m.servicesUp}/${m.servicesTotal}`), " up",
      m.servicesDown.length ? ` (down: ${m.servicesDown.join(", ")})` : ""],
      "Lab services answering their health check", m.servicesDown.length ? "bad" : ""),
    ...row("CPU", [b(`${num(m.cpuNow)}%`), " cluster"], "Cluster CPU use now"),
    ...row("GPU", [b(`${num(m.gpuUtil)}%`), ` across ${m.gpuCount}`], "GPU utilisation across the Lab GPUs"),
    ...row("AI", [b(num(m.aiRpm, 1)), " req/min"], "LiteLLM requests per minute"),
    ...row("WAN", [`↓ `, b(rate(m.wanDownBps)), `  ↑ `, b(rate(m.wanUpBps))], "Internet traffic down / up right now"),
  );
}

function renderNotes(s) {
  const n = s.notes || { lines: [] };
  const list = $("notes-list");
  list.replaceChildren();
  if (!n.lines.length) {
    list.append(el("li", { class: "empty" }, "No notes yet. ALT N writes in the desktop panel, ALT SHIFT N adds a quick note."));
  }
  for (const line of n.lines) list.append(el("li", {}, line));
  $("notes-meta").textContent = n.mtime ? `EDITED ${ago(s.at - n.mtime).toUpperCase()}` : "";
  $("notes-meta").title = n.count > n.lines.length ? `Showing the last ${n.lines.length} of ${n.count} lines` : "All lines shown";
}

// ---------------------------------------------------------------- lab jobs
function secs(ms) {
  const s = Math.max(0, Math.round((ms || 0) / 1000));
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`;
}
function renderLabJobs(s, stale) {
  const box = $("labjobs"), body = $("lj-body"), meta = $("lj-meta");
  const lj = s.labjobs;
  box.hidden = !lj;
  if (!lj) return;
  body.replaceChildren();
  const now = el("div", { class: "lj-now" });
  if (!lj.running.length) {
    now.append(el("p", { class: "empty", title: "No generation or pipeline run is going on now" },
      lj.queued.count ? `Nothing is running; ${lj.queued.count} waiting.` : "Nothing is being made right now."));
  }
  for (const r of lj.running) {
    const pic = el("figure", { class: "lj-pic", title: r.preview ? "The picture as it's made: the latest preview the lab sent" :
      "No picture yet: it comes from the follower (bromigos-labjobs.service), and from ComfyUI only with the relay node" });
    if (r.preview) pic.append(el("img", { src: `${r.preview}?t=${s.at}`, alt: `${r.title}: the picture so far` }));
    else pic.append(el("span", { class: "lj-none" }, (r.label || "LAB").toUpperCase()));
    const pct = r.pct == null ? null : Math.max(0, Math.min(100, r.pct));
    const bar = el("div", { class: "lj-bar", title: pct == null ? "How far: not said yet" : r.estimated ?
      `About ${pct} %: estimated from how long this workflow took before` : `${pct} % done, as ComfyUI measures it` });
    bar.append(el("i", { style: `width:${pct ?? 0}%` }));
    const time = [r.elapsed_ms != null ? `${secs(r.elapsed_ms)} so far` : "", r.estimate_ms ? `usually ${secs(r.estimate_ms)}` : ""].filter(Boolean).join(" · ");
    now.append(el("div", { class: "lj-run" }, pic,
      el("div", {}, el("b", { title: r.title }, r.title),
        el("small", { title: "Where it runs, and who asked" }, [r.where, r.client ? `from ${r.client}` : ""].filter(Boolean).join(" · ")),
        el("span", { class: "lj-stage", title: "The stage it's at" }, `${r.stage || "Running"}${pct != null ? ` · ${pct} %${r.estimated ? " (estimate)" : ""}` : ""}`),
        bar, el("small", {}, time),
        el("code", { title: "Follow it live in a terminal" }, `bromigos activity watch ${r.id}`))));
  }
  if (lj.queued.count) {
    now.append(el("p", { class: "lj-queue", title: lj.queued.titles.join("\n") }, `NEXT · ${lj.queued.count}: ${lj.queued.titles[0]}${lj.queued.count > 1 ? " …" : ""}`));
  }
  const made = el("ol", { class: "lj-made", "aria-label": "What it made lately" });
  for (const m of lj.latest) {
    const word = { succeeded: "made", failed: "failed", cancelled: "stopped", interrupted: "interrupted" }[m.state] || m.state;
    const t = el("li", { title: `${m.title}: ${m.summary || word}` });
    t.append(m.thumb ? el("img", { src: m.thumb, alt: m.title }) : el("span", { class: `lj-none ${m.state === "succeeded" ? "" : "bad"}` },
      m.kind === "video" ? "CLIP" : m.kind === "model3d" ? "3D" : m.state === "succeeded" ? "DONE" : word.toUpperCase()));
    t.append(el("small", {}, `${(m.label || "").toUpperCase()} · ${m.ended_at ? ago(s.at - m.ended_at / 1000) : word}`));
    made.append(t);
  }
  if (!lj.latest.length) made.append(el("li", { class: "empty" }, "Nothing made yet."));
  body.append(now, made);
  const live = lj.instances.some((i) => i.relay);
  meta.textContent = stale ? "STALE" : lj.error ? "CAN'T READ" : lj.following ? (live ? "LIVE PICTURES" : "QUEUE AND RESULTS") : "READ EVERY MINUTE";
  meta.className = "meta" + (lj.error ? " bad" : stale ? " warn" : "");
  meta.title = lj.error ? `The lab's jobs couldn't be read (${lj.error}): bromigos activity --lab says why`
    : live ? "The follower gets ComfyUI's previews as it makes them (the relay node is installed there)"
    : "Pictures appear as jobs finish; the picture while one is made needs the relay node on the ComfyUI (docs/activity.md)";
}

function render() {
  const s = window.BROMIGOS_SNAPSHOT;
  const foot = $("foot");
  if (!s) {
    foot.textContent = "No snapshot yet. Run: systemctl --user enable --now bromigos-startpage.timer";
    foot.className = "bad";
    $("tiles").replaceChildren(el("p", { class: "empty" }, "The links come from the snapshot."));
    renderLab({ lab: { state: "no snapshot" } }, true);
    renderNotes({ notes: { lines: [] } });
    renderLabJobs({}, true);
    return;
  }
  const age = Date.now() / 1000 - s.at;
  const stale = age > STALE_S;
  renderSwitchboard(s, stale);
  renderLab(s, stale);
  renderNotes(s);
  renderLabJobs(s, stale);
  foot.textContent = `Snapshot ${ago(age)}` + (stale ? " (stale: is bromigos-startpage.timer running?)" : "");
  foot.className = stale ? "warn" : "";
}

// Reload data.js without reloading the page.
function load() {
  const old = document.getElementById("snapshot");
  const sc = el("script", { id: "snapshot", src: `data.js?t=${Date.now()}` });
  sc.onload = render;
  sc.onerror = render;
  if (old) old.remove();
  document.body.append(sc);
}
load();
setInterval(load, 30000);
setInterval(render, 10000); // keep the "ago" texts honest between loads
