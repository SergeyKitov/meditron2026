import { defineConfig } from "@playwright/test";

const webPort = Number(process.env.MEDITRON_WEB_PORT ?? "5173");
const baseURL = `http://127.0.0.1:${webPort}`;

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  timeout: 45000,
  use: {
    baseURL,
    viewport: { width: 1440, height: 1100 },
    trace: "retain-on-failure",
  },
  webServer: {
    command: "bash ../scripts/e2e-server.sh",
    url: `${baseURL}/health`,
    reuseExistingServer: false,
    timeout: 45000,
  },
});
