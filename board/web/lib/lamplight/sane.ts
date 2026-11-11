// The door: whatever a host hands the station is made to fit `LamplightData` before anything is
// drawn from it. The data is some server's answer, and on the Lab board much of it is commands'
// own output, so it is not trusted to have the right shape:
//
//   - a state, kind, tone or mark that isn't one of the allowed words becomes "unknown" / "other"
//     (or the plain default), so no word from the data ever picks a shape, a colour or a class;
//   - a field that should be text and isn't is absent, a number that isn't one is absent or 0, a
//     list that isn't one is empty, and an entry with no id is dropped;
//   - nothing is added: a layer the host didn't send is still not drawn.
//
// mount(), mountMachine() and every update() pass their data through here, so the drawing code
// can rely on the types. Text is still only text: it is escaped where it enters markup (base.ts).
import type { DeckId, LampKind, LampState, LamplightData, PartId } from "./types";

type Rec = Record<string, unknown>;
const rec = (v: unknown): Rec | null => (v && typeof v === "object" && !Array.isArray(v) ? (v as Rec) : null);
const recs = (v: unknown): Rec[] => (Array.isArray(v) ? v.filter((x): x is Rec => !!rec(x)) : []);
const str = (v: unknown): string | undefined => (typeof v === "string" ? v : typeof v === "number" && Number.isFinite(v) ? String(v) : undefined);
const txt = (v: unknown, fallback = ""): string => str(v) ?? fallback;
const num = (v: unknown): number | undefined => (typeof v === "number" && Number.isFinite(v) ? v : undefined);
const yes = (v: unknown): boolean => v === true;
const one = <const T extends string, const F>(v: unknown, allowed: readonly T[], fallback: F): T | F => ((allowed as readonly unknown[]).includes(v) ? (v as T) : fallback);

export const KINDS: readonly LampKind[] = ["server", "storage", "node", "desktop", "router", "ups", "other"];
export const STATES: readonly LampState[] = ["ok", "warn", "down", "unknown", "setup", "busy"];
const DECK_IDS: readonly DeckId[] = ["D3", "D2", "D1", "DOCK"];
const PART_IDS: readonly PartId[] = ["mast", "dish", "whips", "arrays", "rackroom", "dock", "hull"];

const words = (v: unknown): { words: string; hint: string } | null => { const o = rec(v); return o ? { words: txt(o.words), hint: txt(o.hint) } : null; };

export function sane(input: unknown): LamplightData {
  const d = rec(input) ?? {}, lab = rec(d.lab) ?? {}, status = rec(d.status) ?? {};
  const head = rec(d.headline), quiet = rec(d.quiet), plan = rec(d.plan), x = rec(d.exchange);
  const sky = rec(d.sky), goals = rec(d.goals), show = rec(d.show), hub = rec(d.hub), parts = rec(d.parts);
  const out: LamplightData = {
    lab: { name: txt(lab.name, "the lab"), address: str(lab.address) ?? null },
    at: num(d.at) ?? null, clock: str(d.clock) ?? null, age: str(d.age) ?? null,
    status: { state: one(status.state, ["ok", "needs-you", "setup", "unknown"], "unknown"), words: txt(status.words) },
    headline: head && txt(head.words) ? { words: txt(head.words), tone: one(head.tone, ["ok", "warn", "q"], "q"), hint: str(head.hint) } : null,
    machines: recs(d.machines).filter((m) => txt(m.id)).map((m) => ({
      id: txt(m.id), name: txt(m.name, txt(m.id)), kind: one(m.kind, KINDS, "other"), role: txt(m.role),
      state: one(m.state, STATES, "unknown"), word: txt(m.word), reading: str(m.reading) ?? null,
      here: yes(m.here), page: m.page !== false, cause: str(m.cause) ?? null, deck: one(m.deck, DECK_IDS, undefined),
    })),
    needs: recs(d.needs).map((n) => {
      const subject = rec(n.subject);
      return {
        id: txt(n.id), machine: txt(n.machine), words: txt(n.words), detail: str(n.detail) ?? null, severity: one(n.severity, ["warn", "danger"], "warn"),
        subject: subject ? { type: txt(subject.type), name: txt(subject.name) } : null, go: str(n.go) ?? null, job: str(n.job) ?? null, since: num(n.since) ?? null,
      };
    }),
    jobs: recs(d.jobs).map((j) => ({ id: txt(j.id), machine: txt(j.machine), kind: txt(j.kind), title: txt(j.title), pct: num(j.pct) ?? null })),
    plan: plan ? {
      title: txt(plan.title), from: str(plan.from),
      steps: recs(plan.steps).map((s) => ({ words: txt(s.words), detail: str(s.detail), hint: str(s.hint) })),
      can: (Array.isArray(plan.can) ? plan.can : []).filter((c): c is "approve" | "change" | "no" => c === "approve" || c === "change" || c === "no"),
    } : null,
    quiet: quiet ? { on: yes(quiet.on), until: str(quiet.until) ?? null } : null,
    mascot: one(d.mascot, ["on", "quiet", "off"], "on"),
    exchange: x ? { mood: txt(x.mood), thought: txt(x.thought), vector: txt(x.vector), why: txt(x.why) } : null,
    sky: sky ? {
      arcs: recs(sky.arcs).map((a) => ({ name: txt(a.name), hint: txt(a.hint), stars: num(a.stars) ?? 2, open: yes(a.open), fresh: yes(a.fresh) })),
      goals: recs(sky.goals).map((g) => ({ name: txt(g.name), hint: txt(g.hint) })),
      copies: rec(sky.copies) ? { proven: yes(rec(sky.copies)!.proven), fresh: yes(rec(sky.copies)!.fresh), hint: txt(rec(sky.copies)!.hint) } : null,
    } : null,
    log: Array.isArray(d.log) ? recs(d.log).map((e) => ({
      at: txt(e.at), title: txt(e.title), detail: txt(e.detail), kind: one(e.kind, ["arc", "copy", "event", "goal"], "event"), mark: one(e.mark, ["open", "fresh"], null),
    })) : null,
    goals: goals ? {
      rank: rec(goals.rank) ? (() => { const r = rec(goals.rank)!; return { title: txt(r.title), xp: num(r.xp) ?? 0, from: num(r.from) ?? 0, to: num(r.to) ?? 1, next: txt(r.next), gained: num(r.gained) }; })() : null,
      list: recs(goals.list).map((g) => ({ state: one(g.state, ["done", "progress", "todo"], "todo"), title: txt(g.title), detail: txt(g.detail), xp: num(g.xp) ?? 0, cap: txt(g.cap), fresh: yes(g.fresh) })),
    } : null,
    show: show && recs(show.cards).length ? {
      when: txt(show.when), aired: yes(show.aired),
      cards: recs(show.cards).map((c) => ({ kind: one(c.kind, ["open", "bump", "card"], "card"), over: txt(c.over), title: txt(c.title), detail: str(c.detail), vector: str(c.vector), art: str(c.art), hint: txt(c.hint) })),
      thread: rec(show.thread) ? (() => {
        const t = rec(show.thread)!;
        return { title: txt(t.title), night: txt(t.night), steps: recs(t.steps).map((s) => ({ when: txt(s.when), date: str(s.date), title: txt(s.title), detail: txt(s.detail), next: yes(s.next) })) };
      })() : null,
    } : null,
    friends: Array.isArray(d.friends) ? recs(d.friends).filter((f) => txt(f.id)).map((f) => ({ id: txt(f.id), name: txt(f.name), lit: yes(f.lit), decks: num(f.decks) ?? 0, stars: num(f.stars) ?? 0, last: txt(f.last) })) : null,
    hub: hub ? {
      name: txt(hub.name), line: txt(hub.line),
      members: recs(hub.members).map((m) => ({ id: txt(m.id), name: txt(m.name), state: one(m.state, ["lit", "out", "new"], "out"), you: yes(m.you), hint: txt(m.hint) })),
      docks: recs(hub.docks).map((k) => ({ name: txt(k.name), lit: yes(k.lit), hint: txt(k.hint) })),
      op: words(hub.op), favour: words(hub.favour),
      sector: Array.isArray(hub.sector) ? recs(hub.sector).map((s) => ({ name: txt(s.name), here: yes(s.here), hint: txt(s.hint) })) : undefined,
    } : null,
  };
  if (parts) {
    out.parts = {};
    for (const id of PART_IDS) { const p = rec(parts[id]); if (p) out.parts[id] = { state: one(p.state, STATES, "unknown"), word: txt(p.word) }; }
  }
  if (Array.isArray(d.joining)) out.joining = recs(d.joining).map((j) => ({ name: txt(j.name), word: txt(j.word) }));
  return out;
}
