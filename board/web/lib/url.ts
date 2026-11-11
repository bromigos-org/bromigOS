// An address the API sent, before it becomes a link: only http: and https: ever do. Anything
// else (javascript:, data:, a relative path, not a string) is no link at all. Every place the
// page turns a server-given address into an href goes through here (lib/api/read.ts).
export function webUrl(value: unknown): string | null {
  if (typeof value !== "string" || !value || value.length > 2000) return null;
  let u: URL;
  try {
    u = new URL(value.trim());
  } catch {
    return null;
  }
  // the address as the server gave it (trimmed), once it is known to be a web address
  return u.protocol === "http:" || u.protocol === "https:" ? value.trim() : null;
}

/** The address without its scheme, for showing under a tile. */
export const shownUrl = (url: string) => url.replace(/^https?:\/\//, "").replace(/\/$/, "");
