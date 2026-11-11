// The page wears the server's world (themes/<name>): its tokens are styles/tokens.css, picked by
// data-world on <html>. The door names the world before sign-in, so the page never flashes another.
import { WORLDS, type World } from "./api/types";

export function asWorld(name: string | null | undefined): World {
  return (WORLDS as readonly string[]).includes(name ?? "") ? (name as World) : "wick";
}

export function wearWorld(name: string | null | undefined): World {
  const w = asWorld(name);
  if (typeof document !== "undefined") document.documentElement.dataset.world = w;
  return w;
}
