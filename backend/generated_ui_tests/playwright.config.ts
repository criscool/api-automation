import { defineConfig, devices } from "@playwright/test";
import "dotenv/config";

const HEADLESS = (process.env.UI_HEADLESS ?? "true").toLowerCase() !== "false";

export default defineConfig({
  testDir: "./scripts",
  outputDir: process.env.PW_OUTPUT_DIR || "./reports/test-results",
  testIgnore: "**/recordings/**",
  globalSetup: "./global-setup.ts",

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
    // Allure 原始事件流：每次执行都写，不调 generate；
    // 由后端 allure_service 在用户按钮触发时按需聚合成 HTML 报告
    // 兼容 allure-playwright 2.x (outputFolder) 和 3.x (resultsDir) 两种参数名
    [
      "allure-playwright",
      {
        resultsDir: process.env.PW_ALLURE_RESULTS_DIR || "./reports/allure-results",
        outputFolder: process.env.PW_ALLURE_RESULTS_DIR || "./reports/allure-results",
        suiteTitle: false,
        detail: true,
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
      name: "chromium",
      testIgnore: /.*auth\.setup\.ts/,
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
