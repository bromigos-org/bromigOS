// The post without a browser (lib/post/): the one table that says which job stands where, the
// door its data comes through, the floor the crew walk on, and the art folder it draws from.
//
// The walk is the part that must never go wrong: the crew may only be on a stretch of floor
// between two joined stops, whatever the jobs do and whenever they are re-sent. So the model is
// run through random job churn, and after every step the worst distance of any crew member from
// the floor must be 0, and every job that runs must have a crew member or a lit room.
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { chart, far, head, offPath, rooms, way, walk, type Walk } from "../lib/post/floor";
import { fromJobs } from "../lib/post/from-jobs";
import { CREW, Model } from "../lib/post/model";
import { PLACES, RULES, STATES, drawn, ending, placeFor, type PlaceId } from "../lib/post/places";
import { sane, saneJob, sanePack } from "../lib/post/sane";
import { JOB_STATES, type PostJob } from "../lib/post/types";

test.beforeEach(({}, info) => test.skip(info.project.name !== "desktop", "no browser needed: once is enough"));

const ART = new URL("../public/post/", import.meta.url).pathname;
const pack = sanePack(JSON.parse(readFileSync(`${ART}post.json`, "utf8")))!;
const job = (over: Partial<PostJob> = {}): PostJob => ({ id: "j1", kind: "backup.run", title: "Backing up", state: "running", step: null, pct: null, agent: null, parent: null, ok: null, ...over });

// ---------------------------------------------------------------- the table

/** Every kind bromigOS has (docs/activity.md, lib/jobs.ts, the commands that start jobs), and where each is drawn. */
const KINDS: [string, PlaceId][] = [
  ["lab.image", "rack"], ["lab.edit", "rack"], ["lab.cutout", "rack"], ["lab.upscale", "rack"], ["lab.video", "rack"], ["lab.model3d", "rack"], ["lab.comfyui", "rack"], ["lab.pipeline", "rack"],
  ["app.install", "fabricator"], ["app.remove", "fabricator"], ["app.restart", "fabricator"], ["app.update", "fabricator"], ["app.update-all", "fabricator"], ["app.rollback", "fabricator"],
  ["app.models", "pad"], ["server.update", "pad"], ["server.install", "pad"],
  ["backup.run", "press"], ["backup.drive", "press"], ["backup.restore", "press"], ["backup.test-restore", "press"],
  ["drive.test", "core"], ["drive.replace", "core"], ["pool.check", "core"], ["storage.add", "core"], ["salvage.scan", "core"],
  ["ci.check", "terminal"], ["something.else", "terminal"],
];

test("the table: each kind bromigOS has stands at one place", () => {
  for (const [kind, place] of KINDS) expect(placeFor({ kind, agent: null }).place, kind).toBe(place);
  // the kinds the page has an icon for are all in the list above: the table was written against them
  const icons = [...readFileSync(new URL("../lib/jobs.ts", import.meta.url), "utf8").matchAll(/^\s+"([a-z0-9-]+\.[a-z0-9.-]+)": "i-/gm)].map((m) => m[1]);
  expect(icons.length).toBeGreaterThan(15);
  expect(icons.filter((k) => !KINDS.some(([kind]) => kind === k))).toEqual([]);
});

test("the table: a job an AI agent asked for is at the hologram table, unless it is the lab's", () => {
  expect(placeFor({ kind: "app.install", agent: "ledger" }).place).toBe("holotable");
  expect(placeFor({ kind: "backup.run", agent: "ledger" }).place).toBe("holotable");
  expect(placeFor({ kind: "lab.pipeline", agent: "ledger" }).place).toBe("rack");
  for (const kind of ["plan.week", "ask.owner", "agent.run", "vector.plan"]) expect(placeFor({ kind, agent: null }).place, kind).toBe("holotable");
});

test("the table: a kind that is no kind still has a place, and no word of it picks one", () => {
  for (const kind of ["", "lab", "labx.image", "LAB.image", "x\"'><i>", "__proto__", "constructor.prototype"]) expect(placeFor({ kind, agent: null }).place, kind).toBe("terminal");
});

test("the table: every place and every state has its sentence, and every place stands on the station", () => {
  expect(new Set(PLACES.map((p) => p.place)).size).toBe(PLACES.length);
  for (const p of PLACES) expect(p.says, p.place).toMatch(/^[A-Z].{20,}\.$/);
  expect(STATES.map((s) => s.state).sort()).toEqual([...JOB_STATES, "unknown"].sort());
  for (const s of STATES) expect(s.says, s.state).toMatch(/^A job .{20,}\.$/);
  for (const says of Object.values(RULES)) expect(says).toMatch(/\.$/);
  const m = new Model(pack.map);
  for (const p of PLACES) {
    const spot = m.spots[p.place];
    expect(spot, p.place).toBeTruthy();
    expect(spot.stops.length, `${p.place}: a stop for each of the three crew`).toBeGreaterThanOrEqual(CREW.length);
    for (const s of spot.stops) expect(m.stops.has(s), `${p.place}: ${s}`).toBe(true);
  }
});

test("the states: only a job that runs or asks is drawn, and a part is drawn as its whole", () => {
  const has = () => false;
  expect(drawn(job({ state: "running" }), has)).toBe("run");
  expect(drawn(job({ state: "needs-you" }), has)).toBe("ask");
  for (const state of ["queued", "waiting", "succeeded", "failed", "rolled-back", "cancelled", "interrupted", "unknown"] as const) expect(drawn(job({ state }), has), state).toBeNull();
  expect(drawn(job({ parent: "whole" }), (id) => id === "whole")).toBeNull();
  expect(drawn(job({ parent: "whole" }), has), "a part whose whole the page doesn't have").toBe("run");
  expect(ending(job({ state: "succeeded", ok: true }))).toBe("ok");
  expect(ending(job({ state: "succeeded", ok: null }))).toBe("ok");
  expect(ending(job({ state: "succeeded", ok: false }))).toBe("fail");
  for (const state of ["failed", "rolled-back", "interrupted"] as const) expect(ending(job({ state })), state).toBe("fail");
  for (const state of ["cancelled", "queued", "waiting", "running", "unknown"] as const) expect(ending(job({ state })), state).toBeNull();
});

// ---------------------------------------------------------------- the door

test("the door: a job is made to fit, and what doesn't fit is absent", () => {
  expect(sane(null)).toEqual({ known: false, jobs: [] });
  expect(sane({ known: "yes", jobs: "x" })).toEqual({ known: false, jobs: [] });
  expect(sane({ known: true, jobs: [null, 3, "x", [], {}, { id: "" }, { id: 7 }] }).jobs).toEqual([]);
  expect(saneJob({ id: "a", kind: 3, title: ["x"], state: "evil", step: {}, pct: "40", agent: 1, parent: false, ok: "true" }))
    .toEqual({ id: "a", kind: "", title: "", state: "unknown", step: null, pct: null, agent: null, parent: null, ok: null });
  for (const pct of [-1, 101, NaN, Infinity]) expect(saneJob({ id: "a", pct })!.pct, String(pct)).toBeNull();
  expect(saneJob({ id: "a", pct: 0 })!.pct).toBe(0);
  expect(saneJob({ id: "a", pct: 100 })!.pct).toBe(100);
  expect(saneJob({ id: "a", title: "x".repeat(5000) })!.title.length).toBeLessThanOrEqual(240);
});

test("the door: the board's own records pass as they are", () => {
  const fixture = JSON.parse(readFileSync(new URL("../fixtures/post.json", import.meta.url), "utf8"));
  // the page's reader names the agent and flattens nothing else the post reads (lib/api/read.ts)
  const data = fromJobs(fixture.activity.map((j: Record<string, unknown>) => ({ ...j, agent: null })), true);
  expect(data.known).toBe(true);
  expect(data.jobs.length).toBe(fixture.activity.length);
  const run = data.jobs.find((j) => j.kind === "backup.run" && j.state === "running")!;
  expect(run).toMatchObject({ title: "Backing up this server", pct: 40, step: "step 2 of 2 · Copying what changed", parent: null, ok: null });
  expect(data.jobs.find((j) => j.state === "failed")!.ok).toBe(false);
  expect(fromJobs(null, false)).toEqual({ known: false, jobs: [] });
  expect(fromJobs([{ id: "a" } as never, null as never, "x" as never], true).jobs).toEqual([saneJob({ id: "a" })]);
});

test("the door: a drawing that isn't one stops there", () => {
  const raw = JSON.parse(readFileSync(`${ART}post.json`, "utf8"));
  expect(pack).toBeTruthy();
  for (const bad of [null, 3, "x", [], {}, { map: {} }, { map: { ...raw.map, size: ["a", "b"] } }, { map: { ...raw.map, T: [0, 0] } }, { map: { ...raw.map, docks: [] } }, { map: { ...raw.map, start: {} } }])
    expect(sanePack(bad), JSON.stringify(bad)?.slice(0, 60)).toBeNull();
  // a room or a machine by a name that could reach another file's address is not drawn at all
  const evil = structuredClone(raw);
  evil.map.types["../x"] = evil.map.types.b; evil.map.start.s2 = ["../x", ["holotable", "rack"]];
  expect(sanePack(evil), "the control room's machines went with it, so two places stand nowhere").toBeNull();
  const odd = structuredClone(raw);
  odd.map.start.s1 = ["a", ["../../etc", "x\"><i>"]];
  expect(sanePack(odd)!.map.start.s1).toEqual(["a", [null, null]]);
  // the shuttle's strip of frames: without a count that is one, the strip isn't used
  for (const ship of [undefined, null, "x", {}, { frames: "25", w: 331, h: 250 }, { frames: 0, w: 331, h: 250 }, { frames: 2.5, w: 331, h: 250 }, { frames: 25, w: -1, h: 250 }]) expect(sanePack({ ...raw, ship })!.ship, JSON.stringify(ship)).toBeNull();
});

// ---------------------------------------------------------------- the floor

test("the floor: every walk is a chain of joined stops", () => {
  const all = rooms(pack.map), stops = chart(pack.map, all), ids = [...stops.keys()];
  expect(all.length).toBe(6);
  const wrong: string[] = [];
  for (const a of ids)
    for (const b of ids) {
      const path = way(stops, a, b);
      if (path[0] !== a || path[path.length - 1] !== b) wrong.push(`${a} → ${b}: ${path.join(" ")}`);
      for (let i = 1; i < path.length; i++) if (!stops.get(path[i - 1])!.to.includes(path[i])) wrong.push(`${a} → ${b}: ${path[i - 1]} and ${path[i]} aren't joined`);
    }
  expect(wrong).toEqual([]);
  expect(ids.length).toBeGreaterThan(30);
  // the rooms far to near, each in a band of its own under the corridors
  expect(all.map((R) => R.z)).toEqual([2000, 4000, 6000, 8000, 10000, 12000]);
  expect(all.map((R) => R.depth)).toEqual([...all.map((R) => R.depth)].sort((x, y) => x - y));
  // a room on the corridor it was not painted for is mirrored
  for (const R of all) expect(R.flip, R.id).toBe((R.T.side === "y") !== (R.on === "spine"));
});

test("the floor: someone re-sent part-way only goes on or back along the stretch they are on", () => {
  const stops = chart(pack.map, rooms(pack.map)), ids = [...stops.keys()];
  let seed = 7;
  const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const c: Walk = { pos: [...stops.get(ids[0])!.p], stop: ids[0], path: [] };
  let worst = 0, leap = 0;
  for (let i = 0; i < 6000; i++) {
    if (rnd() < 0.08) head(stops, c, ids[Math.floor(rnd() * ids.length)]);
    const before = c.pos;
    walk(stops, c, 135 * (0.01 + rnd() * 0.2));
    worst = Math.max(worst, offPath(stops, c.pos));
    // and never further in a step than their speed allows
    leap = Math.max(leap, far(before, c.pos));
  }
  expect(worst).toBeLessThan(1e-6);
  expect(leap).toBeLessThanOrEqual(135 * 0.21 + 1e-6);
  expect(leap).toBeGreaterThan(5);
});

const CHURN_KINDS = [...KINDS.map(([k]) => k), "lab.image", "lab.pipeline", "backup.run", "app.install"];

for (const seed of [1, 2, 3, 4, 5, 6])
  test(`random job churn, seed ${seed}: nobody leaves the floor, and every job that runs is shown`, () => {
    let s = seed * 7919;
    const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;
    const pick = <T>(list: readonly T[]): T => list[Math.floor(rnd() * list.length)];
    const m = new Model(pack.map);
    let jobs: PostJob[] = [], n = 0, known = true, worst = 0, figured = 0, lit = 0, walked = 0;
    const given = new Map<string, number>();
    // what went wrong, with when: one list checked at the end (an expect() a step would take minutes)
    const wrong: string[] = [];
    const must = (ok: boolean, what: () => string) => { if (!ok && wrong.length < 20) wrong.push(what()); };
    const send = (still = false) => m.set({ known, jobs: jobs.map((j) => ({ ...j })) }, still);
    send();
    for (let t = 0; t < 5000; t++) {
      const r = rnd();
      if (r < 0.03) jobs.push(job({ id: `job-${String(++n).padStart(4, "0")}`, kind: pick(CHURN_KINDS), state: pick(["queued", "running", "running", "running", "needs-you", "waiting"] as const), pct: rnd() < 0.5 ? Math.floor(rnd() * 100) : null, agent: rnd() < 0.1 ? "ledger" : null }));
      else if (r < 0.07 && jobs.length) {
        const j = pick(jobs), open = j.state === "queued" || j.state === "running" || j.state === "needs-you" || j.state === "waiting";
        if (open) { j.state = pick(["running", "needs-you", "waiting", "succeeded", "failed", "cancelled", "rolled-back", "interrupted"] as const); j.ok = j.state === "succeeded" ? true : j.state === "running" ? null : j.ok; }
      } else if (r < 0.08 && jobs.length) { const gone = pick(jobs); jobs = jobs.filter((j) => j !== gone); }
      else if (r < 0.083) known = !known;
      if (r < 0.083) send(rnd() < 0.05);          // now and then as reduced motion would: everyone placed, nobody walking

      const before = m.crew.map((c) => [...c.pos] as [number, number]);
      m.step(0.016 + rnd() * 0.2);
      // nobody is ever off the floor
      const off = m.off();
      worst = Math.max(worst, off);
      must(off < 1e-6, () => `t=${t}: a crew member is ${off} off the floor`);
      m.crew.forEach((c, i) => { if (c.state === "walk" && far(before[i], c.pos) > 0) walked++; });

      // nothing is drawn that a record didn't say
      for (const [id, L] of m.live) {
        const rec = jobs.find((j) => j.id === id);
        must(known && !!rec && (rec.state === "running" || rec.state === "needs-you"), () => `t=${t}: ${id} is drawn, and its record says ${rec?.state}`);
        if (!rec) continue;
        must(L.mode === (rec.state === "running" ? "run" : "ask"), () => `t=${t}: ${id} is drawn as ${L.mode}`);
        must(L.place === placeFor(rec).place, () => `t=${t}: ${id} is at the ${L.place}`);
        // a job keeps the crew member it was given
        if (L.who !== null) { if (given.has(id)) must(L.who === given.get(id), () => `t=${t}: ${id} changed hands`); else given.set(id, L.who); }
      }
      for (const id of [...given.keys()]) if (!m.live.has(id)) given.delete(id);
      // every job that runs has a crew member or a lit room; one that asks, a crew member or a mark
      for (const j of jobs) {
        const shows = m.shows(j.id);
        if (!known || (j.state !== "running" && j.state !== "needs-you")) { must(shows === null, () => `t=${t}: ${j.id} (${j.state}) shows as ${shows}`); continue; }
        const spot = m.spots[placeFor(j).place];
        if (j.state === "running") {
          must(shows === "figure" || shows === "room", () => `t=${t}: ${j.id} runs and shows as ${shows}`);
          must(m.machineLook(spot.place) === "run", () => `t=${t}: ${j.id} runs and its machine doesn't`);
          if (spot.room) must(m.roomLook(spot.room) !== "idle", () => `t=${t}: ${j.id} runs and its room is quiet`);
          else must(m.shuttleWanted, () => `t=${t}: ${j.id} runs at the pad and no shuttle is called`);
          if (shows === "figure") figured++; else lit++;
        } else must(shows === "figure" || (shows === "mark" && m.asksAlone(spot.place)), () => `t=${t}: ${j.id} asks and shows as ${shows}`);
      }
      // three crew, each with one job at most, no two standing on one spot
      const busy = m.crew.filter((c) => c.job);
      must(new Set(busy.map((c) => c.job)).size === busy.length, () => `t=${t}: two crew have one job`);
      const standing = m.crew.filter((c) => c.state === "work" || c.state === "wait").map((c) => c.stop);
      must(new Set(standing).size === standing.length, () => `t=${t}: two crew stand on one spot`);
      for (const c of m.crew) if (!c.job && c.state === "idle") must(c.stop === c.home, () => `t=${t}: ${c.name} rests away from the quarters`);
    }
    expect(wrong).toEqual([]);
    expect(worst, "the worst distance of any crew member from the floor").toBeLessThan(1e-6);
    // and the run really exercised it: crew walked, jobs had figures, and some ran with all three busy
    expect(walked).toBeGreaterThan(200);
    expect(figured).toBeGreaterThan(200);
    expect(lit).toBeGreaterThan(0);
  });

test("the crew face the way they walk: each loop is mirrored when the walk needs its other side", () => {
  const m = new Model(pack.map);
  m.set({ known: true, jobs: [] });
  m.set({ known: true, jobs: [job({ id: "a", kind: "server.update" }), job({ id: "b", kind: "lab.image" }), job({ id: "c", kind: "app.install" })] });
  const wrong: string[] = [];
  let steps = 0;
  for (let i = 0; i < 900; i++) {
    const before = m.crew.map((c) => [...c.pos]), stood = m.crew.map((c) => c.stop);
    m.step(0.05);
    m.crew.forEach((c, k) => {
      const dx = c.pos[0] - before[k][0], dy = c.pos[1] - before[k][1];
      // a step along one stretch of floor (one that turned a corner went two ways)
      if (c.state !== "walk" || c.stop !== stood[k] || Math.hypot(dx, dy) < 2 || Math.abs(dx) < 0.5 || Math.abs(dy) < 0.5) return;
      steps++;
      // down the screen is the front loop, up is the back one; a loop painted facing the other way is mirrored
      const loop = dy > 0 ? "to" : "away", faces = (c.flip ? -1 : 1) * c.side[loop];
      if (c.look !== loop || faces !== Math.sign(dx)) wrong.push(`${c.name} walks ${dx.toFixed(0)},${dy.toFixed(0)} in ${c.look}${c.flip ? ", mirrored" : ""}`);
    });
  }
  expect(steps).toBeGreaterThan(100);
  expect(wrong.slice(0, 5)).toEqual([]);
  // each was painted facing one way, as the art is: the three walk away from us facing right
  expect(CREW.map((c) => [c.id, c.side.to, c.side.away])).toEqual([["lineman", -1, 1], ["owl", -1, 1], ["exo", -1, 1]]);
});

test("the crew: a job keeps its crew member, a fourth lights its room, and the first reading replays nothing", () => {
  const m = new Model(pack.map);
  const four = [job({ id: "a", kind: "backup.run", pct: 40 }), job({ id: "b", kind: "lab.image" }), job({ id: "c", kind: "app.install" }), job({ id: "d", kind: "drive.test" })];
  m.set({ known: true, jobs: [...four, job({ id: "e", kind: "backup.run", state: "succeeded", ok: true }), job({ id: "f", kind: "lab.video", state: "queued" })] });
  // already there: nobody walks in from the quarters for a job that was running before the page opened
  expect(m.crew.map((c) => [c.name, c.state, c.job, c.look])).toEqual([["LINEMAN", "work", "a", "pack"], ["OWL", "work", "b", "scan"], ["EXO", "work", "c", "weld"]]);
  expect(m.news).toEqual([]);
  expect(m.shows("d")).toBe("room");
  expect(m.shows("e")).toBeNull();
  expect(m.shows("f")).toBeNull();
  expect(m.roomLook(m.spots.core.room!)).toBe("work");
  expect(m.machineLook("core")).toBe("run");
  expect(m.machineLook("terminal")).toBe("idle");
  // "a" ends well: shown once, its crew member takes the job that had nobody, and walks there on the floor
  m.set({ known: true, jobs: [{ ...four[0], state: "succeeded", ok: true }, ...four.slice(1)] });
  expect(m.news.map((n) => [n.what, n.place])).toEqual([["ok", "press"]]);
  expect(m.shows("d")).toBe("figure");
  expect(m.crew[0]).toMatchObject({ job: "d", state: "walk" });
  expect(m.roomLook(m.spots.press.room!)).toBe("done");
  let worst = 0;
  for (let i = 0; i < 400 && m.crew[0].state === "walk"; i++) { m.step(0.05); worst = Math.max(worst, m.off()); }
  expect(m.crew[0]).toMatchObject({ job: "d", state: "work", look: "crank", stop: m.spots.core.stops[0] });
  expect(worst).toBeLessThan(1e-6);
  for (let i = 0; i < 80; i++) m.step(0.05);
  expect(m.roomLook(m.spots.press.room!), "the finish shows for a moment only").toBe("idle");
  // "b" fails, "c" is stopped: one is shown once, the other leaves quietly, and both crew walk home
  m.news = [];
  m.set({ known: true, jobs: [{ ...four[1], state: "failed", ok: false }, { ...four[2], state: "cancelled" }, four[3]] });
  expect(m.news.map((n) => [n.what, n.place])).toEqual([["fail", "rack"]]);
  expect(m.flash(m.spots.rack.room!, "fail")).toBe(true);
  for (let i = 0; i < 600; i++) { m.step(0.05); worst = Math.max(worst, m.off()); }
  expect(m.crew.map((c) => c.state)).toEqual(["work", "idle", "idle"]);
  expect(worst).toBeLessThan(1e-6);
});

test("the crew: a job that asks stands and waits; two jobs at one place stand apart; the pad calls the shuttle", () => {
  const m = new Model(pack.map);
  m.set({ known: true, jobs: [] });
  expect(m.ship.state).toBe("away");
  m.set({ known: true, jobs: [job({ id: "a", kind: "lab.image" }), job({ id: "b", kind: "lab.pipeline" }), job({ id: "c", kind: "server.update", state: "needs-you" })] });
  expect(m.crew.every((c) => c.state === "walk")).toBe(true);
  let worst = 0;
  const seen: string[] = [], folds: number[] = [];
  for (let i = 0; i < 800; i++) {
    m.step(0.05); worst = Math.max(worst, m.off());
    if (seen[seen.length - 1] !== m.ship.look) seen.push(m.ship.look);
    if (m.ship.look === "fold") folds.push(m.ship.folded);
  }
  expect(worst).toBeLessThan(1e-6);
  // the shuttle flies with its legs folded away, and they come out as it settles: the strip is stepped backwards
  expect(seen).toEqual(["fly", "fold", "idle"]);
  expect(folds.length).toBeGreaterThan(20);
  expect(folds).toEqual([...folds].sort((a, b) => b - a));
  expect(folds[0]).toBeLessThanOrEqual(1);
  expect(folds[folds.length - 1]).toBeGreaterThanOrEqual(0);
  expect(m.crew.map((c) => [c.state, c.look])).toEqual([["work", "scan"], ["work", "scan"], ["wait", "idle"]]);
  expect(m.crew[0].stop).not.toBe(m.crew[1].stop);
  expect(m.spots.rack.stops).toEqual(expect.arrayContaining([m.crew[0].stop, m.crew[1].stop]));
  expect(m.ship.state, "a job at the pad, even one that asks, keeps the shuttle down").toBe("landed");
  expect(m.news.map((n) => n.what)).toEqual(["land"]);
  // the answer comes: the same crew member starts working, where they stand
  m.set({ known: true, jobs: [job({ id: "c", kind: "server.update", state: "running", pct: 10 })] });
  expect(m.crew[2]).toMatchObject({ job: "c", state: "work", look: "lift" });
  // the jobs unread: nobody is shown, and the next reading replays nothing
  m.set({ known: false, jobs: [] });
  expect(m.live.size).toBe(0);
  expect(m.crew.every((c) => c.state === "idle" && c.stop === c.home)).toBe(true);
  m.news = [];
  m.set({ known: true, jobs: [job({ id: "c", kind: "server.update", state: "succeeded", ok: true })] });
  expect(m.news).toEqual([]);
  // with no job left at the pad the shuttle waits a moment, folds its legs as it lifts off (forwards), and is gone
  m.set({ known: true, jobs: [job({ id: "x", kind: "app.models" })] });
  expect([m.ship.state, m.ship.look]).toEqual(["away", "fly"]);
  for (let i = 0; i < 120; i++) m.step(0.05);
  expect([m.ship.state, m.ship.look, m.ship.far]).toEqual(["landed", "idle", 0]);
  m.set({ known: true, jobs: [] });
  const off: string[] = [], up: number[] = [];
  for (let i = 0; i < 200 && m.ship.state !== "away"; i++) {
    m.step(0.05);
    if (off[off.length - 1] !== m.ship.look) off.push(m.ship.look);
    if (m.ship.look === "fold") up.push(m.ship.folded);
  }
  expect(m.ship.state).toBe("away");
  expect(off).toEqual(["idle", "fold", "fly"]);
  expect(up).toEqual([...up].sort((a, b) => a - b));
});

// ---------------------------------------------------------------- the art folder

test("the art: every picture and clip the post can ask for ships, and each has its line of provenance", () => {
  const have = new Set(readdirSync(ART));
  const m = new Model(pack.map), want = new Set<string>(["post.json", "frame.webp", "glow-x1.webp", "glow-x2.webp", "glow-x3.webp", "glow-pad.webp", "ship-idle.webp", "ship-fly.webp", "ship-fold.webp"]);
  // the shuttle's legs are one strip of frames side by side: the strip is as wide as the drawing says
  const strip = readFileSync(`${ART}ship-fold.webp`), x = strip.indexOf("VP8X");
  expect(pack.ship).toEqual({ frames: 25, w: 331, h: 250 });
  expect([strip.readUIntLE(x + 12, 3) + 1, strip.readUIntLE(x + 15, 3) + 1]).toEqual([pack.ship!.frames * pack.ship!.w, pack.ship!.h]);
  for (const R of m.rooms) {
    want.add(`pod-${R.type}.webp`); want.add(`glow-${R.type}.webp`);
    for (const c of R.T.clips) want.add(`pod-${R.type}-${c}.mp4`);
    for (const mach of R.machines) for (const s of ["idle", "run", "done"]) want.add(`m-${mach.kind}-${s}.webp`);
  }
  for (const c of CREW) for (const loop of ["to", "away", "idle", ...PLACES.map((p) => p.act)]) {
    want.add(`${c.id}-${loop}.webp`);
    if (loop !== "to" && loop !== "away") expect(pack.crew[`${c.id}-${loop}`], `${c.id}-${loop}'s height`).toBeGreaterThan(0.5);
  }
  expect([...want].filter((f) => !have.has(f)), "asked for, not shipped").toEqual([]);
  // every file in the folder is accounted for: a line in provenance.jsonl, with its licence and no credits spent
  const lines = readFileSync(`${ART}provenance.jsonl`, "utf8").trim().split("\n").map((l) => JSON.parse(l));
  const named = new Set<string>(lines.flatMap((l) => l.for));
  expect([...have].filter((f) => !named.has(f) && f !== "post.json" && f !== "provenance.jsonl"), "shipped with no provenance").toEqual([]);
  expect([...named].filter((f) => !have.has(f)), "provenance for a file that isn't here").toEqual([]);
  for (const l of lines) { expect(l.licence, l.step).toBe("Apache-2.0"); expect(l.credits, l.step).toBe(0); }
  expect(existsSync(`${ART}provenance.jsonl`)).toBe(true);
});
