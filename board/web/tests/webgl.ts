// Which browser draws WebGL in the tests.
//
// Home and every machine's page now draw a hologram, and on a software renderer (all CI has) each
// costs seconds of processor. So only the specs that test what the holograms draw get a browser
// with WebGL (`test.use(WEBGL)`: the station, a machine's hero, hostile data, the hints and names,
// the pictures). Every other spec runs with WebGL off: there the station stands as words (its line,
// readouts, alarm, deck list and deck plan), which is all those specs read.
//
// BOARD_TEST_GPU=1 (a local run on a machine with a graphics card) draws on the card instead,
// still headless, and then every spec has WebGL. tests/renderer.ts says which renderer a run got.

export const GPU = process.env.BOARD_TEST_GPU === "1";

/** Chromium's flags for a browser that draws WebGL: on the card, or on the software renderer. */
export const WEBGL_ARGS = GPU ? ["--enable-gpu", "--use-angle=vulkan", "--enable-features=Vulkan", "--ignore-gpu-blocklist"] : ["--enable-unsafe-swiftshader"];
/** The flags for every other spec: WebGL off, unless the card draws it for nothing. */
export const PLAIN_ARGS = GPU ? WEBGL_ARGS : ["--disable-3d-apis"];

/** For a spec that tests the holograms: `test.use(WEBGL)` at the top of the file. */
export const WEBGL = { launchOptions: { args: WEBGL_ARGS } };

/** With WebGL off, three.js says on the console that it couldn't make a context. That is the flag's doing, not an error of the page. */
export const NO_WEBGL = /THREE\.WebGLRenderer: .*(WebGL context could not be created|Error creating WebGL context)/;
