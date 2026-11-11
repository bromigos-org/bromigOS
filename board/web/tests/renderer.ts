// Before the suite: which renderer draws WebGL in these browsers, said once. The suite's reference
// is software rendering (CI has no graphics card). BOARD_TEST_GPU=1 asks for the machine's own card
// instead (playwright.config.ts); then a browser that fell back to the processor fails the run
// here, rather than quietly taking every core.
import { chromium, type FullConfig } from "@playwright/test";

export const SOFTWARE = /swiftshader|llvmpipe|softpipe|software/i;

export default async function renderer(config: FullConfig) {
  const use = config.projects[0].use;
  const browser = await chromium.launch({ headless: true, channel: use.channel, args: use.launchOptions?.args });
  try {
    const page = await browser.newPage();
    const name = await page.evaluate(() => {
      const gl = document.createElement("canvas").getContext("webgl2");
      const ext = gl?.getExtension("WEBGL_debug_renderer_info");
      return gl ? String(gl.getParameter(ext ? ext.UNMASKED_RENDERER_WEBGL : gl.RENDERER)) : "no WebGL";
    });
    console.log(`WebGL renderer: ${name}`);
    if (process.env.BOARD_TEST_GPU === "1" && (name === "no WebGL" || SOFTWARE.test(name)))
      throw new Error(`BOARD_TEST_GPU=1 asked for the graphics card, but WebGL is drawn by "${name}". Run without it, or see docs/board.md, "Building and testing".`);
  } finally {
    await browser.close();
  }
}
