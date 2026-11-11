// Before the first test: say which renderer WebGL has, so a run's log shows what drew the
// holograms. With BOARD_TEST_GPU=1 a software renderer is an error, and the run stops here:
// the switch asked for the graphics card, and a run that quietly fell back would be as slow
// as before while claiming otherwise.
import { chromium } from "@playwright/test";
import { GPU, IS_SOFTWARE, WEBGL_ARGS } from "./webgl";

export default async function renderer() {
  const browser = await chromium.launch({ headless: true, args: WEBGL_ARGS });
  let name: string | null;
  try {
    const page = await browser.newPage();
    name = await page.evaluate(() => {
      const c = document.createElement("canvas");
      const gl = (c.getContext("webgl2") ?? c.getContext("webgl")) as WebGLRenderingContext | null;
      if (!gl) return null;
      const info = gl.getExtension("WEBGL_debug_renderer_info");
      return String(gl.getParameter(info ? info.UNMASKED_RENDERER_WEBGL : gl.RENDERER));
    });
  } finally {
    await browser.close();
  }
  console.log(`WebGL renderer (UNMASKED_RENDERER_WEBGL): ${name ?? "none: this Chromium has no WebGL"}${GPU ? "  [BOARD_TEST_GPU=1]" : ""}`);
  if (GPU && (!name || IS_SOFTWARE.test(name)))
    throw new Error(
      `BOARD_TEST_GPU=1 asked for the graphics card, and WebGL is ${name ? `on a software renderer (${name})` : "not there"}. ` +
        `Flags used: ${WEBGL_ARGS.join(" ")}. Try BOARD_TEST_GPU_ARGS="--ozone-platform=headless --use-gl=angle --use-angle=gl-egl --ignore-gpu-blocklist", or run without the switch.`,
    );
}
