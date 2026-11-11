// The fixtures have the shapes the service sends. Every fixture document (the door, the session,
// the board, each job) is compared, key by key and type by type, with the real answers in
// tests/contract/service.json: a key the service sends must be there with a type the service
// sends it with, and a key the service doesn't send may only be one of the additions the page
// has asked the service for (named in ASKED, and in the contracts note). A fixture written in
// another shape than the service's fails here, before any page test runs on it.
import { readdirSync, readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { real } from "./service";

test.beforeEach(({}, info) => test.skip(info.project.name !== "desktop", "no browser needed: once is enough"));

/** What the samples show at one place of a document. */
interface Seen {
  types: Set<string>;
  keys: Map<string, Seen>;
  required: Set<string> | null;
  items: Seen | null;
}
const typeOf = (v: unknown) => (v === null ? "null" : Array.isArray(v) ? "array" : typeof v);
const blank = (): Seen => ({ types: new Set(), keys: new Map(), required: null, items: null });

function learn(s: Seen, v: unknown): Seen {
  s.types.add(typeOf(v));
  if (Array.isArray(v)) for (const x of v) learn((s.items ??= blank()), x);
  else if (v && typeof v === "object") {
    const keys = Object.keys(v);
    s.required = s.required ? new Set([...s.required].filter((k) => keys.includes(k))) : new Set(keys);
    for (const k of keys) learn(s.keys.get(k) ?? s.keys.set(k, blank()).get(k)!, (v as Record<string, unknown>)[k]);
  }
  return s;
}

/** What the page has asked the service for and it doesn't send yet (board-contracts.md, board-web's
 *  sections): the only places a fixture may hold more than a real answer does. */
const ASKED = [
  /^board\.actions$/, // the verbs the page may send to POST /api/actions
  /^board\.machines\[\]\.(readings|hardware|updates)$/, // a machine's readings, its hardware, its pending updates
  /^board\.apps\[\]\.(reading|update)$/, // a tile's one reading and its update (DESIGN §3; null in every real answer today)
];
/** Maps whose keys are names (a command, a drive's reading), not fields: any key may be there. */
const NAMED = [/^board\.sources$/, /\.(readings|trend|rules|evidence|facts|timers|settings)$/, /^board\.system\./];

function check(s: Seen, v: unknown, path: string, out: string[]) {
  if (ASKED.some((r) => r.test(path))) return;
  const t = typeOf(v);
  if (!s.types.has(t)) return void out.push(`${path}: ${t}, but the service sends ${[...s.types].join(" or ")}`);
  if (Array.isArray(v)) {
    if (s.items) v.forEach((x) => check(s.items!, x, `${path}[]`, out));
  } else if (v && typeof v === "object") {
    const named = NAMED.some((r) => r.test(path));
    for (const k of s.required ?? []) if (!(k in v) && !named) out.push(`${path}.${k}: missing, and the service always sends it`);
    for (const [k, x] of Object.entries(v)) {
      const known = s.keys.get(k);
      if (known) check(known, x, `${path}.${k}`, out);
      else if (!named && !ASKED.some((r) => r.test(`${path}.${k}`))) out.push(`${path}.${k}: a key the service doesn't send`);
    }
  }
}

const jobsOf = (text: string) => JSON.parse(text.split("\n").find((l) => l.startsWith("data: "))!.slice(6)).jobs as unknown[];
const SHAPES = {
  board: Object.values(real.boards).reduce(learn, blank()),
  door: Object.values(real.doors).reduce(learn, blank()),
  session: [real.http.session_signed_in.body, real.http.session_signed_out.body, real.http.signin.body].reduce(learn, blank()),
  job: Object.keys(real.http).filter((k) => /^activity_(?!signed_out)/.test(k)).flatMap((k) => jobsOf(real.http[k].body)).reduce(learn, blank()),
};

const dir = new URL("../fixtures/", import.meta.url);
const fixtures = readdirSync(dir).filter((f) => f.endsWith(".json"));

test("there are fixtures to check", () => {
  expect(fixtures.length).toBeGreaterThan(10);
});

for (const file of fixtures)
  test(`fixtures/${file} has the service's shapes`, () => {
    const f = JSON.parse(readFileSync(new URL(file, dir), "utf8"));
    const out: string[] = [];
    const doc = (kind: keyof typeof SHAPES, v: any, path = kind as string) => v && typeof v === "object" && "$status" in v ? null : check(SHAPES[kind], v, path, out);
    doc("door", f.door);
    doc("session", f.session);
    doc("board", f.board);
    if (f.signin) doc("session", f.signin.session);
    for (const j of f.activity) doc("job", j);
    for (const e of f.stream ?? []) if (e.event === "job") doc("job", e.data);
    expect(out).toEqual([]);
  });

test("this check can fail: the shapes the first fixtures had are refused", () => {
  const out: string[] = [];
  const b = structuredClone(real.boards.healthy);
  check(SHAPES.board, { ...b, updates: { ...b.updates.updates, rollbacks: [] } }, "board", out); // `updates` flat, as the page once read it
  expect(out.join("\n")).toContain("board.updates.updates: missing");
  out.length = 0;
  check(SHAPES.board, { ...b, backups: { ...b.backups, last_success: 1794264000, snapshots: 21 } }, "board", out);
  expect(out.join("\n")).toMatch(/board\.backups\.last_success: number, but the service sends/);
  out.length = 0;
  const { age_s: _gone, ...old } = b;
  check(SHAPES.board, { ...old, extra: 1 }, "board", out);
  expect(out).toEqual(["board.age_s: missing, and the service always sends it", "board.extra: a key the service doesn't send"]);
});
