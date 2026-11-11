// What every test shares: opening the page on a fixture, catching page errors and Content
// Security Policy violations, and the list of routes (IA.md §2) with what each must show.
import { expect, type Page } from "@playwright/test";
import { NO_WEBGL } from "./webgl";

declare global {
  interface Window {
    __csp: string[];
  }
}

/** Every route the board has, with the words its crumb must end with. */
export const ROUTES: { hash: string; crumb: RegExp; fixture?: string }[] = [
  { hash: "home", crumb: /Home$/ },
  { hash: "add-machine", crumb: /Add a machine$/ },
  { hash: "m/myserver", crumb: /myserver›Overview$/ },
  { hash: "m/myserver/vitals", crumb: /myserver›Vitals$/ },
  { hash: "m/myserver/hardware", crumb: /myserver›Hardware$/ },
  { hash: "den", crumb: /Den › Remote$/ },
  { hash: "den/library", crumb: /Den › Library$/ },
  { hash: "den/requests", crumb: /Den › Requests$/ },
  { hash: "den/play", crumb: /Den › Play$/ },
  { hash: "cameras", crumb: /Cameras$/, fixture: "cameras" },
  { hash: "supply", crumb: /Supply › Installed$/ },
  { hash: "supply/browse", crumb: /Supply › Browse$/ },
  { hash: "supply/updates", crumb: /Supply › Updates$/ },
  { hash: "app/photos", crumb: /Supply › (Photos|photos)$/ },
  { hash: "app/photos/remove", crumb: /Remove (Photos|photos)$/ },
  { hash: "data", crumb: /Data › Drives$/ },
  { hash: "data/backups", crumb: /Data › Backups$/ },
  { hash: "data/move", crumb: /Data › Move in$/ },
  { hash: "network", crumb: /Network › Devices$/ },
  { hash: "people", crumb: /People › Household$/ },
  { hash: "people/ways", crumb: /People › Ways in$/ },
  { hash: "activity", crumb: /Activity › Now$/ },
  { hash: "settings/lab", crumb: /Settings › Lab$/ },
  { hash: "settings", crumb: /Settings › Notifications$/ },
  { hash: "settings/mascot", crumb: /Settings › Mascot$/ },
];

/** The page states every route is checked in. */
export const STATES = ["healthy", "needs-you", "setup", "lab", "as-served", "cant-read", "watch"];

export async function open(page: Page, fixture: string, hash = "") {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    // allowed: a missing font file (CI may have no Geist Mono), and three.js saying WebGL is off (tests/webgl.ts)
    if (m.type() === "error" && !/fonts\/GeistMono/.test(m.location().url) && !NO_WEBGL.test(m.text())) errors.push(`console: ${m.text()}`);
  });
  await page.addInitScript(() => {
    window.__csp = [];
    document.addEventListener("securitypolicyviolation", (e) => window.__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
  });
  await page.goto(`/?fixture=${fixture}${hash ? `#${hash}` : ""}`);
  await expect(page.locator(".shell")).toBeVisible({ timeout: 15_000 });
  return {
    errors,
    csp: () => page.evaluate(() => window.__csp),
  };
}

/**
 * A page's one status line. Home's is the station's own line (Lamplight is handed the page's
 * headline), or the hero's frame until the station has loaded; a machine's is under its hero;
 * elsewhere it is the stage's.
 */
export const VERDICT = ".stage .verdict, .mgroups .verdict, .lamp.on .head .line";
/** Home: when the server read itself, and how long ago (the station's, or the frame's chip). */
export const READ_AT = ".lamp.on .head .readat, .stage.lamp-wait .chip";

/** The controls a person can press or type in, that are on screen now. */
export const CONTROLS = 'a[href], button, input, select, textarea, summary, [role="button"], [tabindex]:not([tabindex="-1"])';
