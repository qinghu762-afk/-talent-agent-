import { defineConfig } from "@playwright/test";
import { readFileSync } from "node:fs";
const liveBaseURL = process.env.LIVE_BASE_URL?.replace(/\/$/, "");
if (liveBaseURL) {
  if (
    !["http://127.0.0.1:18080", "http://localhost:18080"].includes(liveBaseURL)
  )
    throw new Error("真实验收仅允许新平台本机18080端口");
  const envText = readFileSync(new URL("../.env", import.meta.url), "utf8");
  const raw = envText.match(/^\s*ADMIN_PASSWORD\s*=\s*(.+)\s*$/m)?.[1]?.trim();
  if (!raw) throw new Error("新平台配置缺少ADMIN_PASSWORD");
  process.env.LIVE_API_PASSWORD = raw.replace(/^(['"])(.*)\1$/, "$2");
}
export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  fullyParallel: false,
  outputDir: liveBaseURL ? "live-artifacts/results" : "test-results",
  reporter: liveBaseURL
    ? [
        ["list"],
        ["html", { outputFolder: "live-artifacts/report", open: "never" }],
        ["json", { outputFile: "live-artifacts/report/results.json" }],
      ]
    : "list",
  use: {
    baseURL: liveBaseURL || "http://127.0.0.1:5188",
    channel: "chrome",
    viewport: { width: 1440, height: 1000 },
    screenshot: "only-on-failure",
    trace: liveBaseURL ? "off" : "retain-on-failure",
  },
  webServer: liveBaseURL
    ? undefined
    : {
        command: "npm.cmd run dev -- --port 5188",
        url: "http://127.0.0.1:5188",
        reuseExistingServer: true,
      },
  timeout: 30000,
});
