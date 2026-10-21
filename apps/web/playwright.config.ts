import { defineConfig, devices } from "@playwright/test";

// Visual and layout checks of the screens the web app shares with the desktop window (docs/phase3-web-parity-plan.md).
// The browser talks to a web app started with the sign-in stub and no engine: every /api call is answered by the
// test itself (e2e/mock-api.ts), so the checks need no services and the pictures are the same on every run.
//
//   pnpm --filter web test:e2e                      the layout checks and the screenshots
//   pnpm --filter web test:e2e --update-snapshots   after a change to how a screen should look
//
// Screenshots are kept per operating system (the fonts differ); CI runs only the layout checks (`@layout`).
const PORT = 3100;

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./e2e/results",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  expect: { toHaveScreenshot: { maxDiffPixelRatio: 0.01, stylePath: "./e2e/screenshot.css" } },
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: "retain-on-failure" },
  projects: [
    {
      name: "desktop-dark",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 800 },
        colorScheme: "dark",
      },
    },
    {
      name: "desktop-light",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 800 },
        colorScheme: "light",
      },
    },
    {
      name: "phone-dark",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 390, height: 844 },
        colorScheme: "dark",
        hasTouch: true,
      },
    },
  ],
  webServer: {
    // a production build: the dev server recompiles pages on first visit and is not steady enough for screenshots
    // (CI has built the app in the step before)
    command: process.env.CI
      ? `pnpm exec next start --port ${PORT}`
      : `pnpm exec next build && pnpm exec next start --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/music`,
    env: {
      AUTH_MODE: "stub",
      API_BASE_URL: "http://127.0.0.1:9",
      NEXT_TELEMETRY_DISABLED: "1",
    },
    reuseExistingServer: !process.env.CI,
    timeout: 300_000,
  },
});
