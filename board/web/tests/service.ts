// A stand-in for the board's service, for the contract tests: every /api/ request of one page is
// answered from tests/contract/service.json, which holds real answers of the service (made by
// scripts/make-contract.py from the service's own code and the commands' own libraries). The
// page under test is the real client (no ?fixture=), so what these tests see is what a server sees.
import { readFileSync } from "node:fs";
import { expect, type Page, type Route } from "@playwright/test";

type Json = Record<string, any>;
export const real: { now: number; http: Record<string, { status: number; headers: Record<string, string>; body: any }>; boards: Record<string, Json>; doors: Record<string, Json> } =
  JSON.parse(readFileSync(new URL("./contract/service.json", import.meta.url), "utf8"));

export const copy = <T>(x: T): T => structuredClone(x);
export const CODE = "ABCD-EFGH";

export interface Seen {
  method: string;
  path: string;
  headers: Record<string, string>;
  body: string | null;
}

/** An answer that isn't the usual 200 with a document: a status with a JSON body or a text. */
export class Answer {
  constructor(
    readonly status: number,
    readonly o: { body?: unknown; text?: string; headers?: Record<string, string> } = {},
  ) {}
}
/** One of the service's real activity streams (service.json's http.NAME), kept open. */
export class Live {
  constructor(readonly name: string) {}
}
export const live = (name: string) => new Live(name);
/** The real "Not Found" of a route the service doesn't have. */
export const NOT_FOUND = new Answer(404, { text: "Not Found" });
/** An Answer, or "gone": the connection is refused (the server went away). */
export type Other = Answer | "gone";

export class Service {
  signedIn = true;
  door: unknown = copy(real.doors.healthy);
  /** The board's document (anything at all: the tests send broken ones too), an Answer, "gone", or a function giving one each time. */
  board: unknown = copy(real.boards.healthy);
  /** The activity stream: a real stream by its name in service.json (it stays open, as the
   *  service's does), a text of events (sent, then the stream ends), or another answer. */
  activity: Live | string | Other | (() => Live | string | Other) = live("activity_healthy");
  vitals: unknown = NOT_FOUND;
  actions: unknown = NOT_FOUND;
  /** The signed-in browsers, when a test needs more than the real answer's one. The service's
   *  own rules are kept: ending one answers the new list, an unknown id its real 404. */
  browsers: { id: string; current: boolean }[] | null = null;
  /** Milliseconds /api/session waits before answering. */
  sessionDelay = 0;
  seen: Seen[] = [];
  private id = `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;

  /** Cut this page's open activity stream, as when the server goes away. */
  async drop(page: Page) {
    await page.request.get(`/__drop/${this.id}`);
  }

  count(path: string, method = "GET") {
    return this.seen.filter((s) => s.path === path && s.method === method).length;
  }

  async attach(page: Page) {
    await page.route("**/api/**", (route) => this.answer(route));
  }

  private async send(route: Route, what: unknown, status = 200) {
    if (what === "gone") return route.abort("connectionrefused");
    if (what instanceof Answer) {
      if (what.o.body !== undefined) return route.fulfill({ status: what.status, headers: what.o.headers, contentType: "application/json", body: JSON.stringify(what.o.body) });
      return route.fulfill({ status: what.status, headers: what.o.headers, contentType: "text/plain; charset=utf-8", body: what.o.text ?? "" });
    }
    return route.fulfill({ status, contentType: "application/json", headers: { "cache-control": "no-store" }, body: JSON.stringify(what) });
  }

  private stream(route: Route, what: unknown) {
    if (what instanceof Live) return route.continue({ url: new URL(`/__sse/${what.name}?id=${this.id}`, route.request().url()).href });
    if (typeof what === "string") return route.fulfill({ status: 200, contentType: "text/event-stream; charset=utf-8", body: what });
    return this.send(route, what);
  }

  private real(route: Route, name: string) {
    const r = real.http[name];
    return route.fulfill({ status: r.status, headers: r.headers, body: typeof r.body === "string" ? r.body : JSON.stringify(r.body) });
  }

  private async answer(route: Route) {
    const q = route.request(), url = new URL(q.url()), path = url.pathname, method = q.method();
    this.seen.push({ method, path, headers: q.headers(), body: q.postData() });
    if (path === "/api/door") return this.send(route, this.door);
    if (path === "/api/session" || path.startsWith("/api/session/")) {
      if (method === "GET") {
        if (this.sessionDelay) await new Promise((r) => setTimeout(r, this.sessionDelay));
        if (this.signedIn && this.browsers) return this.send(route, { ...copy(real.http.session_signed_in.body), browsers: this.browsers });
        return this.real(route, this.signedIn ? "session_signed_in" : "session_signed_out");
      }
      // as the service: every request that changes something carries the header and a JSON body
      if (q.headers()["x-bromigos-board"] !== "1") return this.real(route, "signin_no_header");
      if (!(q.headers()["content-type"] ?? "").startsWith("application/json")) return this.send(route, new Answer(415, { body: { error: { code: "not-json", words: "Send JSON (Content-Type: application/json)." } } }));
      if (method === "POST") {
        if (JSON.parse(q.postData() ?? "{}").code !== CODE) return this.real(route, "signin_wrong_code");
        this.signedIn = true;
        return this.real(route, "signin");
      }
      // DELETE /api/session/ID: another browser's id ends that one and answers the new list; an
      // id nobody has is the service's 404; this browser's own id signs it out, as below
      const id = path.startsWith("/api/session/") ? path.slice("/api/session/".length) : null;
      if (id && this.browsers && !this.browsers.some((b) => b.id === id && b.current)) {
        if (!this.browsers.some((b) => b.id === id)) return this.real(route, "signout_other_unknown");
        this.browsers = this.browsers.filter((b) => b.id !== id);
        return this.send(route, { ...copy(real.http.session_signed_in.body), browsers: this.browsers });
      }
      this.signedIn = false;
      return this.real(route, "signout");
    }
    if (!this.signedIn) return this.real(route, "board_signed_out");
    if (path === "/api/board") return this.send(route, typeof this.board === "function" ? this.board() : this.board);
    if (path === "/api/activity" && method === "GET") return this.stream(route, typeof this.activity === "function" ? this.activity() : this.activity);
    if (path === "/api/vitals") return this.send(route, this.vitals);
    if (path === "/api/actions" && method === "POST") return this.send(route, this.actions, 202);
    return this.real(route, "no_such_route"); // Starlette's answer for a route the service doesn't have
  }
}

/** What went wrong on a page: thrown errors, console errors, and content-policy violations. */
export interface Watch {
  errors: string[];
  csp(): Promise<string[]>;
}

/** Open the page on the stand-in service: the real client, under the board's content policy. */
export async function openReal(page: Page, service: Service, hash = "", opts: { quiet?: RegExp } = {}): Promise<Watch> {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const text = m.text();
    // a failed request is the test's own doing (a 4xx, 5xx or refused answer); a font may be missing in CI
    if (/Failed to load resource|net::ERR_/.test(text) || /fonts\/GeistMono/.test(m.location().url) || opts.quiet?.test(text)) return;
    errors.push(`console: ${text}`);
  });
  await page.addInitScript(() => {
    (window as any).__csp = [];
    document.addEventListener("securitypolicyviolation", (e) => (window as any).__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
  });
  await service.attach(page);
  await page.goto(`/${hash ? `#${hash}` : ""}`);
  await expect(page.locator(".shell")).toBeVisible({ timeout: 15_000 });
  return { errors, csp: () => page.evaluate(() => (window as any).__csp as string[]) };
}

/** The page is whole: the shell is there, no part of it was replaced by the boundary's sentence, nothing threw. */
export async function whole(page: Page, watch: Watch, where: string) {
  await expect(page.locator(".sh-crumb"), `${where}: the top bar`).toBeVisible();
  await expect(page.locator("#view > *").first(), `${where}: the page`).toBeVisible();
  expect(await page.locator(".broken").count(), `${where}: a part couldn't be shown`).toBe(0);
  expect(watch.errors, where).toEqual([]);
}

/** Go to another place of the page without loading it again. */
export async function go(page: Page, hash: string) {
  await page.evaluate((h) => {
    window.location.hash = h;
  }, hash);
  await page.waitForFunction((h) => window.location.hash === `#${h}`, hash);
}

/** Every place a signed-in page has. */
export const PLACES = ["home", "m/myserver", "m/myserver/vitals", "m/myserver/hardware", "data", "data/backups", "data/move", "supply", "supply/browse", "supply/updates",
  "supply/add/navidrome", "app/photos", "den", "network", "people", "people/ways", "activity", "settings", "add-machine"];

/** Let `ms` of the page's (installed) clock pass, a second at a time, so that what each timer
 *  starts (a request, and the timer its answer sets) has the real moment it needs to arrive. */
export async function pass(page: Page, ms: number) {
  for (let left = ms; left > 0; left -= 1000) {
    await page.clock.runFor(Math.min(1000, left));
    await page.waitForTimeout(40);
  }
}
