// Before `next build`: STATIC's crew for Lamplight (lib/lamplight-assets.ts), from the repository's
// own mascot art, into public/lamplight/ (not committed: one copy of each painting, in mascot/).
//
//   crew/NAME.webp   the cut-outs that ship (mascot/crew/), copied as they are
//   still/NAME.webp  a shell's portrait: the first frame of its loop in the guide (mascot/static/),
//                    lifted out of the animated WebP as the picture it already is
//
// Nothing is decoded or encoded, so the build needs no image library and two builds are the same
// files. The mascot folder is two levels up in the repository; a build elsewhere (the package's)
// names it in BOARD_MASCOT.
import { copyFileSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const mascot = process.env.BOARD_MASCOT || new URL("../../../mascot/", import.meta.url).pathname;
const out = new URL("../public/lamplight/", import.meta.url).pathname;

const CREW = ["owl", "owl-scan", "lineman", "lineman-stand", "noir"];
/** Each shell's loop in the guide: OWL searching, LINEMAN at a junction box, NOIR hosting. */
const STILLS = { owl: "antenna-168.webp", lineman: "whack-168.webp", noir: "host-168.webp" };

function fail(words) {
  console.error(`art: ${words}\n     STATIC's art is the repository's mascot/ folder; BOARD_MASCOT names it when the page is built elsewhere.`);
  process.exit(1);
}

/**
 * The first frame of an animated WebP, as a still WebP. The container is RIFF: after "WEBP" come
 * chunks (a four-letter name, a length, the bytes, padded to an even length). Each frame is an
 * ANMF chunk: sixteen bytes of placing and timing, then the frame's own picture chunks. A frame
 * that fills the canvas and is one plain "VP8 " picture is already a whole WebP file once it has
 * a RIFF header of its own.
 */
function firstFrame(file) {
  const b = readFileSync(file);
  if (b.toString("latin1", 0, 4) !== "RIFF" || b.toString("latin1", 8, 12) !== "WEBP") fail(`${file} isn't a WebP file.`);
  let canvas = null;
  for (let o = 12; o + 8 <= b.length; ) {
    const name = b.toString("latin1", o, o + 4), size = b.readUInt32LE(o + 4), at = o + 8;
    if (name === "VP8X") canvas = [b.readUIntLE(at + 4, 3) + 1, b.readUIntLE(at + 7, 3) + 1];
    if (name === "ANMF") {
      const x = b.readUIntLE(at, 3), y = b.readUIntLE(at + 3, 3), w = b.readUIntLE(at + 6, 3) + 1, h = b.readUIntLE(at + 9, 3) + 1;
      const pic = b.toString("latin1", at + 16, at + 20), len = b.readUInt32LE(at + 20);
      if (x || y || !canvas || w !== canvas[0] || h !== canvas[1] || pic !== "VP8 " || 24 + len + (len & 1) > size + (size & 1))
        fail(`${file}'s first frame isn't one plain picture the size of the loop, so it can't be lifted out as it is.`);
      const chunk = b.subarray(at + 16, at + 24 + len + (len & 1));
      const head = Buffer.alloc(12);
      head.write("RIFF", 0, "latin1");
      head.writeUInt32LE(4 + chunk.length, 4);
      head.write("WEBP", 8, "latin1");
      return Buffer.concat([head, chunk]);
    }
    o = at + size + (size & 1);
  }
  fail(`${file} has no frames.`);
}

rmSync(out, { recursive: true, force: true });
mkdirSync(join(out, "crew"), { recursive: true });
mkdirSync(join(out, "still"), { recursive: true });
for (const name of CREW) {
  const from = join(mascot, "crew", `${name}.webp`);
  if (!existsSync(from)) fail(`${from} is missing.`);
  copyFileSync(from, join(out, "crew", `${name}.webp`));
}
for (const [shell, loop] of Object.entries(STILLS)) {
  const from = join(mascot, "static", loop);
  if (!existsSync(from)) fail(`${from} is missing.`);
  writeFileSync(join(out, "still", `${shell}.webp`), firstFrame(from));
}
console.log(`art: ${CREW.length} cut-outs and ${Object.keys(STILLS).length} portraits in public/lamplight/`);
