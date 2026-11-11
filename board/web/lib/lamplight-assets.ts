// What Lamplight may draw on the Lab board: the manifest its module is handed (lib/lamplight/types.ts,
// `LamplightAssets`). The module asks for nothing that isn't named here.
//
// Models (public/holo/, docs/ASSETS.md): the station is the Wick's mesh, cut open in code, as a relay
// station of the Wick's class; the rack and the workstation are bromigos.org's. Each has a lighter
// bake (lite/) that the station draws, and the rack and the workstation keep their full mesh for a
// machine's own page.
//
// A machine kind with no model here is drawn as its icon on its deck tray. Storage, node, router
// and battery wait there: their meshes were made with Pixal3D, whose DINOv3 licence isn't cleared,
// so they aren't shipped. When a clean remake lands, its files go in public/holo/ and its line goes
// in `models` and `kinds`; nothing else changes.
//
// Crew (scripts/art.mjs copies and cuts these from the repository's mascot/ at build time): the five
// cut-outs that ship (mascot/crew/), and behind them the round portraits cut from the guide's
// loops (mascot/static/), used only for a shell whose cut-out isn't here. SPARK, HERMIT and EXO
// have neither, so they are named in words.
import type { ModelInfo } from "./holo/view";
import type { LamplightAssets } from "./lamplight/types";
import rackLite from "@/public/holo/lite/rack.json";
import wickCut from "@/public/holo/lite/wick-cut.json";
import workstationLite from "@/public/holo/lite/workstation.json";
import rack from "@/public/holo/rack.json";
import workstation from "@/public/holo/workstation.json";

// the part lists are the bakes' own files: their number triples read as number[] from JSON
const info = (j: unknown) => j as ModelInfo;

export const ASSETS: LamplightAssets = {
  base: "/",
  models: {
    "wick-cut": { src: "holo/lite/wick-cut.bin", info: info(wickCut) },
    rack: { src: "holo/lite/rack.bin", info: info(rackLite), full: { src: "holo/rack.bin", info: info(rack) } },
    workstation: { src: "holo/lite/workstation.bin", info: info(workstationLite), full: { src: "holo/workstation.bin", info: info(workstation) } },
  },
  kinds: { server: "rack", desktop: "workstation" },
  art: {
    // OWL listens on the mast, and leans in to look while something needs you
    "crew/owl": "lamplight/crew/owl.webp",
    "crew/owl-work": "lamplight/crew/owl-scan.webp",
    // LINEMAN at work on a machine, and waiting in quarters
    "crew/lineman": "lamplight/crew/lineman.webp",
    "crew/lineman-rest": "lamplight/crew/lineman-stand.webp",
    "crew/noir": "lamplight/crew/noir.webp",
    "still/owl": "lamplight/still/owl.webp",
    "still/lineman": "lamplight/still/lineman.webp",
    "still/noir": "lamplight/still/noir.webp",
  },
};
