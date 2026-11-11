// How the tests' Chromium draws WebGL (the holograms).
//
// By default it is Chromium's software renderer, SwiftShader: CI has no graphics card, and a
// run is the same everywhere. BOARD_TEST_GPU=1 puts headless Chromium on this computer's
// graphics card instead, still with no window (docs/board.md, "On a graphics card").
// BOARD_TEST_GPU_ARGS replaces the flags, for a card the default ones don't reach.

export const GPU = process.env.BOARD_TEST_GPU === "1";

/** ANGLE on Vulkan, drawing offscreen: no display server is asked for anything. */
const VULKAN = ["--ozone-platform=headless", "--use-angle=vulkan", "--enable-features=Vulkan", "--ignore-gpu-blocklist"];
const SOFTWARE = ["--enable-unsafe-swiftshader"];

export const WEBGL_ARGS: string[] = !GPU ? SOFTWARE : (process.env.BOARD_TEST_GPU_ARGS?.split(/\s+/).filter(Boolean) ?? VULKAN);

/** A renderer that is the processor, whatever it calls itself. */
export const IS_SOFTWARE = /swiftshader|llvmpipe|softpipe|software/i;
