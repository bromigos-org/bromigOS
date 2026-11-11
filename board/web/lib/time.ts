// Times as a person reads them: the local clock, and how long ago. The API sends milliseconds
// since the epoch, UTC (DESIGN.md §4).

const pad = (n: number) => String(n).padStart(2, "0");

/** "14:02", in this browser's time zone. */
export function clock(ms: number): string {
  const d = new Date(ms);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** "14:02" today, "yesterday 14:02", or "3 Nov" further back. */
export function when(ms: number, now: number): string {
  const d = new Date(ms), n = new Date(now);
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((day(n) - day(d)) / 86_400_000);
  if (days === 0) return clock(ms);
  if (days === 1) return `yesterday ${clock(ms)}`;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

/** "just now", "4 min ago", "2 h ago", "3 days ago". */
export function ago(ms: number, now: number): string {
  const s = Math.max(0, Math.round((now - ms) / 1000));
  if (s < 45) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 36) return `${h} h ago`;
  const d = Math.round(h / 24);
  return d === 1 ? "1 day ago" : `${d} days ago`;
}

/** "4 min", "1 h 20 min": how long something took or has run. */
export function took(ms: number): string {
  const m = Math.max(0, Math.round(ms / 60_000));
  if (m < 1) return "under a minute";
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60), r = m % 60;
  return r ? `${h} h ${r} min` : `${h} h`;
}

/** A reading older than its max_age_s is stale: drawn static grey with its age (DESIGN §3). */
export const stale = (at: number, maxAgeS: number, now: number) => now - at > maxAgeS * 1000;

/** How long, with no "ago": "under a minute", "4 min", "2 h", "3 days". */
export function span(ms: number): string {
  const said = ago(0, Math.max(0, ms));
  return said === "just now" ? "under a minute" : said.replace(/ ago$/, "");
}
