// Headless Chromium against the fixture build (npm run build:fixtures), served as the server
// serves it (tests/serve.mjs). Nothing opens on the desktop: there is no headed project.
import { defineConfig, devices } from "@playwright/test";

const port = Number(process.env.PORT ?? 4317);
// WebGL is drawn by Chromium's software renderer: CI has no graphics card, and CI is the reference.
// BOARD_TEST_GPU=1 (a local run on a machine with a card) draws it on the card instead, still
// headless; tests/renderer.ts says which renderer the run got, and fails it if the card wasn't used.
const gpu = process.env.BOARD_TEST_GPU === "1";
const webgl = gpu ? ["--enable-gpu", "--use-angle=vulkan", "--enable-features=Vulkan", "--ignore-gpu-blocklist"] : ["--enable-unsafe-swiftshader"];

export default defineConfig({
  testDir: "tests",
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
    launchOptions: { args: webgl },
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 900 } } },
    { name: "phone", use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true } },
  ],
  webServer: { command: `node tests/serve.mjs ${port}`, url: `http://127.0.0.1:${port}/`, reuseExistingServer: !process.env.CI },
});
