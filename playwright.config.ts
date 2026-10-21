import { defineConfig, devices } from "@playwright/test";

// Run with: npx playwright install chromium && npm run test:e2e
// Static files are served by a tiny Python server (see webServer below); no backend is
// required because every API call is intercepted with page.route().

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:8123",
    trace: "on-first-retry",
  },
  webServer: [
    { command: "python -m http.server 8123 --directory web-room", port: 8123, reuseExistingServer: true, timeout: 10_000 },
    { command: "python -m http.server 8124 --directory dashboard/out", port: 8124, reuseExistingServer: true, timeout: 10_000 },
  ],
  projects: [{ name: "chromium", use: { ...devices["Pixel 5"] } }],
});