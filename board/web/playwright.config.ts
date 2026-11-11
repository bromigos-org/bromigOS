// Headless Chromium against the fixture build (npm run build:fixtures), served as the server
// serves it (tests/serve.mjs). Nothing opens on the desktop: there is no headed project.
import { defineConfig, devices } from "@playwright/test";
import { WEBGL_ARGS } from "./tests/webgl";

const port = Number(process.env.PORT ?? 4317);

export default defineConfig({
  testDir: "tests",
  // says which renderer WebGL has, and stops a BOARD_TEST_GPU=1 run that isn't on the card
  globalSetup: "./tests/renderer.ts",
  fullyParallel: true,
  timeout: 60_000,
  // the hologram draws on a software renderer in headless Chromium: a few workers at a time
  workers: process.env.CI ? 2 : 6,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    headless: true,
    timezoneId: "America/Los_Angeles",
    locale: "en-US",
    trace: "retain-on-failure",
    // WebGL without a graphics card (CI, and the default everywhere): Chromium's software
    // renderer. BOARD_TEST_GPU=1 uses this computer's card instead (tests/webgl.ts)
    launchOptions: { args: WEBGL_ARGS },
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 900 } } },
    { name: "phone", use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true } },
  ],
  webServer: { command: `node tests/serve.mjs ${port}`, url: `http://127.0.0.1:${port}/`, reuseExistingServer: !process.env.CI },
});
