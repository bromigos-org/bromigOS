// The Depth drawer's contents (IA.md §4: "one press behind, always in the same place"): for each
// place, the exact commands, files and units behind it, for the power user. Plain words first on
// the page; this is the second layer. A line whose command isn't on main yet is marked planned.
import type { Route } from "./routes";

export interface DepthLine {
  text: string;
  note?: string;
  planned?: boolean;
}
export interface DepthItem {
  title: string;
  hint: string;
  lines: DepthLine[];
}

const ACTIVITY: DepthItem = {
  title: "The jobs",
  hint: "The activity commands: every long job keeps a record with named steps, in a unit of its own (docs/activity.md)",
  lines: [
    { text: "bromigos activity list", note: "the jobs, newest first" },
    { text: "bromigos activity show ID --json", note: "one job's record, as this page reads it" },
    { text: "sudo bromigos activity answer ID CHOICE", note: "answer a job that asks" },
    { text: "sudo bromigos activity cancel ID", note: "stop it, when it says that is safe" },
    { text: "sudo bromigos activity retry ID" },
    { text: "/var/lib/bromigos/activity/jobs/ID.json", note: "the record; ID.log beside it" },
  ],
};

const BOARD: DepthItem = {
  title: "This page",
  hint: "Where the board's readings come from, and the service that serves it",
  lines: [
    { text: "bromigos server status --json", note: "this server: updates, roll-backs, the battery backup" },
    { text: "bromigos alerts --json", note: "what needs you, worst first" },
    { text: "bromigos lab apps list --json", note: "one tile per catalogue item, installed or not" },
    { text: "/run/bromigos-board/board.json", note: "the snapshot, every 15 s while a browser is open" },
    { text: "systemctl status bromigos-board.service" },
  ],
};

const DOOR: DepthItem = {
  title: "Signing in",
  hint: "How a browser signs in without a password, and how to see and end its session",
  lines: [
    { text: "sudo bromigos server board code", note: "a one-time code: ten minutes, one use" },
    { text: "sudo bromigos server board sessions", note: "the signed-in browsers; sign one out" },
    { text: "GET /api/door", note: "all the door shows: the server's name and the apps to open" },
  ],
};

const DRIVES: DepthItem = {
  title: "The drives",
  hint: "Drive health: each drive judged by its own health records over time (docs/storage.md)",
  lines: [
    { text: "bromigos storage health", note: "one line per drive" },
    { text: "bromigos storage health sdb", note: "one drive: verdict, what to do, readings over time" },
    { text: "bromigos storage health --json", note: "what this page reads" },
    { text: "sudo bromigos alerts check --system --only disk.smart", note: "read the drives now" },
    { text: "/var/lib/bromigos/drives/history.json", note: "each drive's kept readings" },
  ],
};

const BACKUPS: DepthItem = {
  title: "The backups",
  hint: "The server's backups: status, the kept snapshots, getting files back, and the monthly test restore (docs/server.md)",
  lines: [
    { text: "bromigos lab backups status --json", note: "what this page reads" },
    { text: "bromigos lab backups list", note: "the kept snapshots" },
    { text: "sudo bromigos lab backups restore latest PATH", note: "get files back, beside the originals" },
    { text: "sudo bromigos lab backups test", note: "a test restore: a sample, compared, nothing of yours changed" },
    { text: "sudo bromigos lab backups run", note: "back up now" },
  ],
};

const APPS: DepthItem = {
  title: "The apps",
  hint: "The apps a Server runs: bromigos lab apps lists, adds and removes them (docs/lab.md, Apps on a Server)",
  lines: [
    { text: "bromigos lab apps list --all", note: "what runs, and what can be added" },
    { text: "bromigos lab apps show ID", note: "one app in full: units, data, health check" },
    { text: "sudo bromigos lab apps add ID --plan", note: "what it would add, and what it asks of the server" },
    { text: "sudo bromigos lab apps add ID" },
    { text: "sudo bromigos lab apps restart ID" },
    { text: "sudo bromigos lab apps remove ID", note: "keeps its data" },
    { text: "bromigos lab apps logs ID -f" },
    { text: "/etc/bromigos/lab/apps.toml", note: "what this server is meant to run" },
  ],
};

export function depthFor(route: Route, signedIn: boolean): DepthItem[] {
  if (!signedIn) return [DOOR];
  switch (route.place) {
    case "activity":
      return [ACTIVITY];
    case "people":
      return [DOOR, BOARD];
    case "supply":
    case "app":
      return [APPS, ACTIVITY];
    case "data":
      return route.tab === "backups" ? [BACKUPS] : [DRIVES, BACKUPS];
    default:
      return [BOARD, ACTIVITY];
  }
}
