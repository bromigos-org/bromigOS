// The catalogue's `holo` ids (homelab/lib/bromigos_homelab/provcatalog.py, HOLO) and the sprite
// symbol each one draws (DESIGN.md §5: one icon by job). An id the page doesn't know draws the
// module glyph on a dimmed plate, as an app without one of ours does.
const HOLO_ICON: Record<string, string> = {
  photos: "i-photos",
  passwords: "i-passwords",
  documents: "i-documents",
  home: "i-home",
  "file-sync": "i-sync",
  uptime: "i-uptime",
  films: "i-screen",
  music: "i-music",
  books: "i-books",
  requests: "i-requests",
  library: "i-library",
  downloads: "i-download",
  "private-network": "i-vpn",
  "ad-blocking": "i-adblock",
  shares: "i-shares",
  backups: "i-backup",
  "front-door": "i-frontdoor",
  "model-serving": "i-models",
  voice: "i-voice",
  creation: "i-creation",
  "game-server": "i-game",
  phone: "i-phone",
  cluster: "i-module",
  board: "i-board",
};

export const holoIcon = (holo: string | null | undefined): { id: string; known: boolean } =>
  holo && HOLO_ICON[holo] ? { id: HOLO_ICON[holo], known: true } : { id: "i-module", known: false };
