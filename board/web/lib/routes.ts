// Where everything lives (the structure review, IA.md §2): one page, routed by the address's
// hash, so Caddy serves one index.html and needs no rewrites. Places are lab-wide; a machine
// is a filter; tabs are parts of a place; sheets open over the page they belong to.
//
//   #home                       Home (the default)         #add-machine        sheet over Home
//   #m/<name>[/vitals|/hardware|/setup]                     a machine
//   #den[/library|/requests|/play]   #cameras                #supply[/browse|/updates]
//   #supply/add[/<id>]  #supply/stacks   sheets over Browse  #app/<id>[/remove]  one app
//   #data[/backups|/shares|/move]    #network[/adblock|/away]   #people[/ways]
//   #activity[/history|/reports]     #job/<id>  a job's sheet over Activity
//   #settings[/lab|/notifications|/mascot|/power|/recovery|/about]
//   #signin                     the sign-in sheet over the door (signed out only)

export type Place =
  | "home"
  | "machine"
  | "den"
  | "cameras"
  | "supply"
  | "app"
  | "data"
  | "network"
  | "people"
  | "activity"
  | "settings"
  | "signin";

export interface Tab {
  id: string; // "" is the place's first tab
  label: string;
  hint: string;
  /** Not built yet: drawn dim with the planned mark, and not a link. */
  planned?: boolean;
}

export const TABS: Partial<Record<Place, Tab[]>> = {
  machine: [
    { id: "", label: "Overview", hint: "Overview: what this machine is doing, and whether it needs you" },
    { id: "vitals", label: "Vitals", hint: "Vitals: is it this machine that is slow or hot, and which app" },
    { id: "hardware", label: "Hardware", hint: "Hardware: what is in this box, who uses each part, and its system versions" },
  ],
  den: [
    { id: "", label: "Remote", hint: "Remote: what is playing where, and the controls" },
    { id: "library", label: "Library", hint: "Library: what the household can watch or hear" },
    { id: "requests", label: "Requests", hint: "Requests: ask for a title, and see how far it has come" },
    { id: "play", label: "Play", hint: "Play: the game worlds, who is on, start and stop" },
  ],
  supply: [
    { id: "", label: "Installed", hint: "Installed: what runs, where, and whether each one is well" },
    { id: "browse", label: "Browse", hint: "Browse: what the lab can run, and whether it fits" },
    { id: "updates", label: "Updates", hint: "Updates: what changes tonight, and holding one back" },
  ],
  data: [
    { id: "", label: "Drives", hint: "Drives: can the lab lose a drive today?" },
    { id: "backups", label: "Backups", hint: "Backups: when the last good copy was made, and whether a restore was proven" },
    { id: "shares", label: "Shares", hint: "Shares: folders the house can reach, and how to connect from Windows, Mac or Linux. Planned.", planned: true },
    { id: "move", label: "Move in", hint: "Move in: what is still in someone else's cloud or box" },
  ],
  network: [
    { id: "", label: "Devices", hint: "Devices: what is on the home network" },
    { id: "adblock", label: "Ad blocking", hint: "Ad blocking: what is blocked, and for whom. Planned.", planned: true },
    { id: "away", label: "Away", hint: "Away: reach home from a phone or laptop, and why one can't. Planned.", planned: true },
  ],
  people: [
    { id: "", label: "Household", hint: "Household: who is here, and what each can see" },
    { id: "ways", label: "Ways in", hint: "Ways in: where you are signed in, and signing a browser in or out" },
  ],
  activity: [
    { id: "", label: "Now", hint: "Now: running, waiting and upcoming jobs" },
    { id: "history", label: "History", hint: "History: who did what, and when, with undo while its window is open. Planned.", planned: true },
    { id: "reports", label: "Reports", hint: "Reports: the weekly lab report, sent to BRODEC. Planned.", planned: true },
  ],
  settings: [
    { id: "lab", label: "Lab", hint: "Lab: its name, its home and its address. Planned.", planned: true },
    { id: "", label: "Notifications", hint: "Notifications: where alerts go, quiet hours, and what raises them" },
    { id: "mascot", label: "Mascot", hint: "Mascot: when STATIC shows up, and quieting him" },
    { id: "power", label: "Power", hint: "Power: the battery backup and the shutdown order, price per kWh, sleep and quiet hours. Planned.", planned: true },
    { id: "recovery", label: "Recovery", hint: "Recovery: the rebuild kit and the recovery sheet. Planned.", planned: true },
    { id: "about", label: "About", hint: "About: versions, licences, what stays free. Planned.", planned: true },
  ],
};

/** Where a place's word sits in the top bar's crumb. */
export const PLACE_NAME: Record<Place, string> = {
  home: "Home",
  machine: "",
  den: "Den",
  cameras: "Cameras",
  supply: "Supply",
  app: "Supply",
  data: "Data",
  network: "Network",
  people: "People",
  activity: "Activity",
  settings: "Settings",
  signin: "Sign in",
};

export interface Route {
  place: Place;
  /** The tab's id ("" for the first), a machine's tab, or a sub-page. */
  tab: string;
  /** The machine's name, the app's id, the job's id. */
  id: string | null;
  /** A sheet open over the page: add-machine, add, stacks, remove, job. */
  sheet: string | null;
  /** The sheet's own subject (the app to add). */
  sheetId: string | null;
  /** Normalised hash, without "#". */
  hash: string;
}

const NAME = /^[a-z0-9][a-z0-9._-]{0,62}$/i;
const tabIds = (p: Place) => (TABS[p] ?? []).map((t) => t.id);

export function parse(hash: string): Route {
  const raw = decodeURIComponent(hash.replace(/^#\/?/, "")).trim();
  const [head = "", a = "", b = ""] = raw.split("/");
  const r = (place: Place, tab = "", id: string | null = null, sheet: string | null = null, sheetId: string | null = null): Route => ({
    place,
    tab,
    id,
    sheet,
    sheetId,
    hash: [head, a, b].filter(Boolean).join("/"),
  });
  switch (head) {
    case "":
    case "home":
      return r("home");
    case "add-machine":
      return r("home", "", null, "add-machine");
    case "signin":
      return r("signin");
    case "m":
      if (!NAME.test(a)) return r("home");
      return r("machine", ["vitals", "hardware", "setup"].includes(b) ? b : "", a);
    case "app":
      if (!NAME.test(a)) return r("supply");
      return r("app", "", a, b === "remove" ? "remove" : null);
    case "job":
      return NAME.test(a) ? r("activity", "", null, "job", a) : r("activity");
    case "supply":
      if (a === "add") return r("supply", "browse", null, "add", NAME.test(b) ? b : null);
      if (a === "stacks") return r("supply", "browse", null, "stacks");
      return r("supply", tabIds("supply").includes(a) ? a : "");
    case "data":
      if (a === "backups" && b === "files") return r("data", "backups", null, "files");
      return r("data", tabIds("data").includes(a) ? a : "");
    case "settings": {
      const t = tabIds("settings").includes(a) ? a : "";
      return r("settings", t === "notifications" ? "" : t);
    }
    case "den":
    case "network":
    case "people":
    case "activity":
      return r(head, tabIds(head).includes(a) ? a : "");
    case "cameras":
      return r("cameras");
    default:
      return r("home");
  }
}

/** The hash for a place and tab, as the rail and the tabs link it. */
export function href(place: Place, tab = "", id: string | null = null): string {
  if (place === "home") return "#home";
  if (place === "machine") return `#m/${id}${tab ? `/${tab}` : ""}`;
  if (place === "app") return `#app/${id}`;
  return `#${place}${tab ? `/${tab}` : ""}`;
}
