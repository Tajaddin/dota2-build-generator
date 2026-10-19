import { defineConfig } from "@playwright/test";
import os from "node:os";
import path from "node:path";

// Runs the real Python server (with the built UI) on a spare port and a throwaway user folder.
const port = 4343;
const home = path.join(os.tmpdir(), `d2bg-e2e-${Date.now()}`);

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    // Locally the installed Edge is used, so no browser download is needed; CI installs Chromium.
    channel: process.env.CI ? undefined : "msedge",
    trace: "retain-on-failure",
  },
  webServer: {
    command: `uv run d2bg serve --no-open --port ${port}`,
    cwd: "..",
    url: `http://127.0.0.1:${port}/health`,
    reuseExistingServer: false,
    timeout: 120_000,
    env: { D2BG_HOME: home },
  },
});
