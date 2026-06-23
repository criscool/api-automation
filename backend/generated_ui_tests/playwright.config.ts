import { defineConfig, devices } from "@playwright/test";
import "dotenv/config";

const HEADLESS = (process.env.UI_HEADLESS ?? "true").toLowerCase() !== "false";

export default defineConfig({
  testDir: "./scripts",
  outputDir: process.env.PW_OUTPUT_DIR || "./reports/test-results",

  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: Number(process.env.UI_PLAYWRIGHT_TIMEOUT_MS || 120_000),
  expect: {
    timeout: 15_000,
  },

  reporter: [
    ["list"],
    [
      "html",
      {
        outputFolder: process.env.PW_HTML_REPORT_DIR || "./reports/html",
        open: "never",
      },
    ],
    [
      "json",
      {
        outputFile: process.env.PW_JSON_REPORT_FILE || "./reports/results.json",
      },
    ],
  ],

  use: {
    headless: HEADLESS,
    baseURL: process.env.UI_BASE_URL || undefined,
    viewport: { width: 1280, height: 800 },
    ignoreHTTPSErrors: true,
    actionTimeout: 30_000,
    navigationTimeout: 45_000,

    video: "retain-on-failure",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },

  projects: [
    {
      name: "setup",
      testMatch: /.*auth\.setup\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 800 },
        launchOptions: {
          args: ["--no-sandbox", "--disable-dev-shm-usage"],
        },
      },
    },
    {
      name: "chromium",
      testIgnore: /.*auth\.setup\.ts/,
      dependencies: ["setup"],
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 800 },
        storageState: ".auth/user.json",
        launchOptions: {
          args: ["--no-sandbox", "--disable-dev-shm-usage"],
        },
      },
    },
  ],
});
