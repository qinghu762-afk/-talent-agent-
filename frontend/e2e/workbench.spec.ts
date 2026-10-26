import { test, expect, type Page } from "@playwright/test";
// Synthetic API fixtures are isolated to browser tests and are never loaded by the app.
const profile = {
  name: "测试人才甲",
  phone: null,
  email: "test@example.invalid",
  location: "杭州",
  education: [],
  experiences: [],
  projects: [],
  skills: ["Python"],
  certificates: [],
  intentions: [],
  evidence: {
    skills: [{ quote: "测试原文：使用 Python 完成数据处理", page: 1 }],
  },
  summary: "测试经历摘要",
  tags: [],
  anomalies: [],
  experience_months: 24,
  completeness: 0.5,
};
const talent = {
  id: "t1",
  name: profile.name,
  profile,
  revision: 2,
  indexed_revision: 2,
  active: true,
  created_at: "2026-10-20T10:00:00Z",
  documents: [{ id: "d1", filename: "测试简历.txt", status: "completed" }],
  revisions: [{ revision: 1, profile, reason: "首次解析" }],
  merges: [],
};
const requirements = {
  required_skills: ["Python"],
  preferred_skills: [],
  min_experience_months: 12,
  min_education: null,
  required_certificates: [],
  location: null,
  responsibilities: ["数据处理"],
  evidence: {},
};
const job = {
  id: "j1",
  title: "测试数据工程师",
  description: "测试岗位内容",
  requirements,
  revision: 1,
  status: "completed",
};
const candidates = Array.from({ length: 4 }, (_, i) => ({
  talent_id: `t${i + 1}`,
  name: `测试人才${i + 1}`,
  profile,
  revision: 2,
  score: {
    eligible: i === 0,
    total: 90 - i * 10,
    dimensions: [
      {
        key: "skills",
        label: "技能覆盖",
        score: 90 - i * 10,
        weight: 0.5,
        evidence: ["测试技能依据"],
      },
      {
        key: "experience",
        label: "相关经验",
        score: 80,
        weight: 0.5,
        evidence: ["测试经验依据"],
      },
    ],
    conditions: [
      {
        label: "必备技能 Python",
        status: i === 0 ? "pass" : "unknown",
        evidence: i === 0 ? "测试原文包含 Python" : "档案未提供可核实依据",
      },
    ],
    strengths: ["技能相关"],
    gaps: [],
    unknowns: i === 0 ? [] : ["技能需确认"],
  },
}));
const run = {
  id: "r1",
  job_id: "j1",
  status: "completed",
  job_snapshot: { title: job.title, requirements, revision: 1 },
  results: candidates,
  diagnostics: { eligible: 1 },
  model_versions: {
    chat: { name: "local-test", digest: "test-digest" },
    embedding: { name: "local-test", digest: "test-embedding-digest" },
  },
  duration_ms: 1200,
  created_at: "2026-10-20T10:00:00Z",
};
async function mock(page: Page, role = "recruiter", results = candidates) {
  const mutations: { path: string; method: string; body: any }[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api/v1", "");
    const method = request.method();
    let body: any = null;
    try {
      body = request.postDataJSON();
    } catch {}
    if (method !== "GET") mutations.push({ path, method, body });
    let result: unknown = [];
    if (path === "/auth/me")
      result = { id: "u1", username: "测试操作员", role };
    else if (path === "/system")
      result = {
        services: {
          postgres: { ok: true, detail: "" },
          redis: { ok: true, detail: "" },
        },
        limits: { batch_files: 200, file_mb: 20 },
        models: { chat: "local-test", embedding: "local-test" },
        mode: "private",
      };
    else if (path === "/dashboard")
      result = {
        talents: 0,
        indexed: 0,
        queued: 0,
        issues: 0,
        jobs: 0,
        documents: 0,
        failed: 0,
      };
    else if (path === "/batches" && method === "POST")
      result = { id: "b1", created_at: "2026-10-20T10:00:00Z", items: [] };
    else if (path === "/tasks")
      result = [
        {
          id: "task1",
          kind: "ingest",
          status: "failed",
          attempts: 1,
          error: "测试解析失败",
          created_at: "2026-10-20T10:00:00Z",
        },
      ];
    else if (path.startsWith("/tasks/") && method === "POST")
      result = { ok: true };
    else if (path === "/talents") result = { items: [talent], total: 1 };
    else if (path === "/talents/t1" && method === "GET") result = talent;
    else if (path === "/talents/t1" && method === "PUT")
      result = { ...talent, profile: body.profile, revision: 3 };
    else if (path === "/jobs")
      result = method === "GET" ? [job] : { id: "j1", task_id: "task2" };
    else if (path === "/jobs/j1/matches")
      result =
        method === "GET"
          ? [{ ...run, results }]
          : { id: "r1", task_id: "task3" };
    else if (path === "/matches/r1") result = { ...run, results };
    else if (path === "/users")
      result =
        method === "GET"
          ? [{ id: "u1", username: "测试操作员", role: "admin", active: true }]
          : { id: "u2", ...body, active: true };
    await route.fulfill({ json: result });
  });
  return mutations;
}
test("task upload and retry use real user interactions", async ({ page }) => {
  const mutations = await mock(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "任务中心" })).toBeVisible();
  await expect(page.getByText("账号管理", { exact: true })).toHaveCount(0);
  await page.locator("input[type=file]").setInputFiles({
    name: "测试简历.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("测试简历"),
  });
  await page.getByRole("button", { name: "开始解析（1）" }).click();
  await expect(page.getByText("文件已进入解析队列")).toBeVisible();
  expect(
    mutations.some((m) => m.path === "/batches" && m.method === "POST"),
  ).toBe(true);
  await page.getByRole("button", { name: /重\s*试/, exact: true }).click();
  await expect(page.getByText("已重新加入队列")).toBeVisible();
  expect(mutations.some((m) => m.path === "/tasks/task1/retry")).toBe(true);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: ".qa/tasks-desktop.png",
    fullPage: true,
    animations: "disabled",
  });
});
test("talent edit preserves revision and evidence", async ({ page }) => {
  const mutations = await mock(page);
  await page.goto("/");
  await page.getByRole("menuitem", { name: "人才库" }).click();
  await page.getByRole("button", { name: "查看档案", exact: true }).click();
  await page.getByRole("tab", { name: "原文依据与文件" }).click();
  await expect(
    page.getByText("测试原文：使用 Python 完成数据处理"),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "测试简历.txt" }),
  ).toHaveAttribute("href", "/api/v1/documents/d1/file");
  await page.getByRole("button", { name: "编辑档案" }).click();
  await page.getByLabel("经历摘要", { exact: true }).fill("已核对的测试摘要");
  await page.getByRole("button", { name: "保存档案" }).click();
  await expect(page.getByText("档案已保存，正在更新检索信息")).toBeVisible();
  const edit = mutations.find(
    (m) => m.path === "/talents/t1" && m.method === "PUT",
  );
  expect(edit?.body.revision).toBe(2);
  expect(edit?.body.profile.summary).toBe("已核对的测试摘要");
  expect(edit?.body.profile.evidence.skills[0].quote).toContain("测试原文");
});
test("match comparison is capped at three and unknown hard conditions are visible", async ({
  page,
}) => {
  await mock(page);
  await page.goto("/");
  await page.getByRole("menuitem", { name: "岗位与匹配" }).click();
  await page.getByRole("button", { name: "条件与匹配结果" }).click();
  await page.getByRole("tab", { name: "匹配历史" }).click();
  await page.getByRole("button", { name: "查看结果", exact: true }).click();
  await expect(page.getByText("选择最多 3 位候选人比较")).toBeVisible();
  for (let i = 1; i <= 3; i++)
    await page.getByRole("checkbox", { name: `比较 测试人才${i}` }).check();
  await expect(
    page.getByRole("checkbox", { name: "比较 测试人才4" }),
  ).toBeDisabled();
  await expect(
    page.getByRole("img", { name: "候选人评分维度比较图" }),
  ).toBeVisible();
  await page.getByText("查看比较数值").click();
  await expect(page.locator(".accessible-chart")).toBeVisible();
  await page.getByRole("button", { name: "评分与依据" }).nth(1).click();
  await expect(page.getByText("未知 · 不通过")).toBeVisible();
  await expect(page.getByText("档案未提供可核实依据")).toBeVisible();
  await page.screenshot({
    path: ".qa/match-evidence.png",
    fullPage: true,
    animations: "disabled",
  });
});
test("same-name candidates remain distinct when comparison selection changes", async ({
  page,
}) => {
  const sameName = [
    {
      ...candidates[0],
      talent_id: "12345678-0000-4000-8000-000000000001",
      name: "同名测试人才",
    },
    {
      ...candidates[1],
      talent_id: "12345678-0000-4000-8000-000000000002",
      name: "同名测试人才",
    },
  ];
  await mock(page, "recruiter", sameName);
  await page.goto("/");
  await page.getByRole("menuitem", { name: "岗位与匹配" }).click();
  await page.getByRole("button", { name: "条件与匹配结果" }).click();
  await page.getByRole("tab", { name: "匹配历史" }).click();
  await page.getByRole("button", { name: "查看结果", exact: true }).click();
  const first = page.getByRole("checkbox", {
    name: "比较 同名测试人才（12345678-0000-4000-8000-000000000001）",
    exact: true,
  });
  const second = page.getByRole("checkbox", {
    name: "比较 同名测试人才（12345678-0000-4000-8000-000000000002）",
    exact: true,
  });
  await first.check();
  await second.check();
  await page.getByText("查看比较数值").click();
  const comparison = page.locator(".accessible-chart");
  await expect(
    comparison.getByRole("columnheader", {
      name: "同名测试人才（12345678-0000-4000-8000-000000000001）",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    comparison.getByRole("columnheader", {
      name: "同名测试人才（12345678-0000-4000-8000-000000000002）",
      exact: true,
    }),
  ).toBeVisible();
  const values = comparison.getByRole("row").filter({ hasText: "技能覆盖" });
  await expect(values.getByRole("cell")).toHaveText(["90.0", "80.0"]);
  await first.uncheck();
  await expect(second).toBeChecked();
  await expect(
    comparison.getByRole("columnheader", {
      name: "同名测试人才（12345678-0000-4000-8000-000000000002）",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    comparison
      .getByRole("row")
      .filter({ hasText: "技能覆盖" })
      .getByRole("cell"),
  ).toHaveText(["80.0"]);
});
test("admin account creation submits recruiter role", async ({ page }) => {
  const mutations = await mock(page, "admin");
  await page.goto("/");
  await page.getByRole("menuitem", { name: "账号管理" }).click();
  await page.getByRole("button", { name: "新增账号" }).click();
  await page.getByLabel("账号", { exact: true }).fill("tester");
  await page.getByLabel("初始密码").fill("TestPassword123456");
  await page.getByRole("button", { name: /保\s*存/, exact: true }).click();
  await expect(page.getByText("账号已创建")).toBeVisible();
  expect(
    mutations.find((m) => m.path === "/users" && m.method === "POST")?.body
      .role,
  ).toBe("recruiter");
});
test("mobile empty states fit the viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mock(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "任务中心" })).toBeVisible();
  await expect(
    page.getByText("还没有导入批次。选择上方文件，建立第一份人才档案。"),
  ).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
  await page.screenshot({
    path: ".qa/tasks-mobile.png",
    fullPage: true,
    animations: "disabled",
  });
});
