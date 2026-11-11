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
    { text: "bromigos lab apps list --json", note: "one tile per app", planned: true },
    { text: "/run/bromigos-board/board.json", note: "the snapshot, every 15 s while a browser is open", planned: true },
    { text: "systemctl status bromigos-board.service", planned: true },
  ],
};

const DOOR: DepthItem = {
  title: "Signing in",
  hint: "How a browser signs in without a password, and how to see and end its session",
  lines: [
    { text: "sudo bromigos server board code", note: "a one-time code: ten minutes, one use", planned: true },
    { text: "sudo bromigos server board sessions", note: "the signed-in browsers; sign one out", planned: true },
    { text: "GET /api/door", note: "all the door shows: the server's name and the apps to open" },
  ],
};

export function depthFor(route: Route, signedIn: boolean): DepthItem[] {
  if (!signedIn) return [DOOR];
  switch (route.place) {
    case "activity":
      return [ACTIVITY];
    case "people":
      return [DOOR, BOARD];
    default:
      return [BOARD, ACTIVITY];
  }
}
