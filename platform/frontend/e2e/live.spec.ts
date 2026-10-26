import { test, expect } from "@playwright/test";
import { writeFileSync } from "node:fs";

// Opt-in: LIVE_BASE_URL uses deployed new platform; otherwise an isolated smoke API.
// Trace remains off so credential-bearing login requests are never written to disk.
test.use({ trace: "off" });
test("真实API：人才建改查、组卷审批、答卷、学习考核与成长记录", async ({
  page,
}) => {
  test.skip(
    !process.env.LIVE_API_PASSWORD,
    "设置 LIVE_API_PASSWORD 后执行真实API联调",
  );
  test.setTimeout(120000);
  page.setDefaultTimeout(15000);
  const suffix = Date.now().toString(),
    name = `合成浏览器验收人才${suffix}`,
    skill = `合成验收专用${suffix}`;
  const evidence: Record<string, any> = {
    base_url: process.env.LIVE_BASE_URL || "isolated-vite-smoke",
    synthetic_prefix: name,
  };
  const capture = async (file: string) => {
    const path = test.info().outputPath(file);
    await page.screenshot({ path, fullPage: true });
    await test.info().attach(file, { path, contentType: "image/png" });
  };
  await page.goto("/");
  await page
    .getByLabel("账号", { exact: true })
    .fill(process.env.LIVE_API_USERNAME || "admin");
  await page
    .getByLabel("密码", { exact: true })
    .fill(process.env.LIVE_API_PASSWORD!);
  const loggedIn = page.waitForResponse((r) =>
    r.url().endsWith("/api/v1/auth/login"),
  );
  try {
    await page.getByRole("button", { name: "登录工作台" }).click();
    expect((await loggedIn).ok()).toBeTruthy();
  } finally {
    const input = page.getByLabel("密码", { exact: true });
    if (await input.count()) await input.fill("");
  }
  await expect(
    page.getByRole("heading", { name: "工作概览", exact: true }),
  ).toBeVisible();
  await capture("portal-desktop.png");
  await page.goto("/#talents");
  await page.getByRole("button", { name: "新建人才档案" }).click();
  await page.getByLabel("人才画像", { exact: true }).fill(
    JSON.stringify({
      name,
      skills: [skill],
      summary: "合成浏览器验收数据，无真实个人资料",
    }),
  );
  const created = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/v1/talents") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: /保\s*存/, exact: true }).click();
  const response = await created;
  expect(response.status()).toBe(201);
  const talent = (await response.json()).data;
  evidence.talent_id = talent.id;
  await page.getByRole("searchbox", { name: "搜索人才档案" }).fill(name);
  const talentRow = page.getByRole("row").filter({ hasText: name });
  await talentRow.getByRole("button", { name: /编\s*辑/, exact: true }).click();
  await page.getByLabel("人才画像", { exact: true }).fill(
    JSON.stringify({
      name,
      skills: [skill, "合成数据核对"],
      summary: "合成浏览器验收修改已保存",
    }),
  );
  const edited = page.waitForResponse(
    (r) =>
      r.url().endsWith(`/api/v1/talents/${talent.id}`) &&
      r.request().method() === "PATCH",
  );
  await page.getByRole("button", { name: /保\s*存/, exact: true }).click();
  expect((await edited).ok()).toBeTruthy();
  await talentRow.getByRole("button", { name, exact: true }).click();
  await expect(
    page.getByText("合成浏览器验收修改已保存", { exact: true }).first(),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "能力与学习成长" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: /Close|关\s*闭/, exact: true })
    .click();

  const create = async (path: string, data: any) => {
    const r = await page.request.post(`/api/v1/${path}`, { data });
    expect(r.status(), await r.text()).toBe(201);
    return (await r.json()).data;
  };
  await create("questions", {
    title: `合成浏览器验收考题${suffix}`,
    question_type: "single",
    options: ["def", "function"],
    answer: "def",
    skills: [skill],
    points: 100,
  });
  await page.goto("/#assessments");
  await page.getByRole("button", { name: "自动组卷" }).click();
  const examTitle = `合成浏览器验收测评${suffix}`;
  await page.getByLabel("测评名称", { exact: true }).fill(examTitle);
  await page.getByLabel("参测人才", { exact: true }).click();
  await page.getByTitle(name, { exact: true }).click();
  await page.getByLabel("题目数量", { exact: true }).fill("1");
  const assembled = page.waitForResponse((r) =>
    r.url().endsWith("/api/v1/assessments/compose"),
  );
  await page.getByRole("button", { name: "生成测评草稿" }).click();
  const assembly = await assembled;
  expect(assembly.status()).toBe(201);
  const exam = (await assembly.json()).data;
  evidence.assessment_id = exam.id;
  await page.getByRole("searchbox", { name: "搜索测评" }).fill(examTitle);
  const examRow = page.getByRole("row").filter({ hasText: examTitle });
  const publishing = page.waitForResponse((r) =>
    r.url().endsWith(`/api/v1/assessments/${exam.id}/publish`),
  );
  await examRow.getByRole("button", { name: "提交发布审批" }).click();
  const approval = (await (await publishing).json()).data;
  await page.goto("/#approvals");
  await page.getByRole("searchbox", { name: "搜索审批" }).fill(approval.id);
  await page.getByRole("button", { name: /审\s*批/, exact: true }).click();
  const resolved = page.waitForResponse((r) =>
    r.url().endsWith(`/api/v1/approvals/${approval.id}/resolve`),
  );
  await page.getByRole("button", { name: "批准发布" }).click();
  expect((await resolved).ok()).toBeTruthy();
  await page.goto("/#assessments");
  await page.getByRole("searchbox", { name: "搜索测评" }).fill(examTitle);
  await page.getByRole("button", { name: "进入测评" }).click();
  await page.getByRole("button", { name: "开始测评" }).click();
  await expect(
    page.getByText(`合成浏览器验收考题${suffix}`, { exact: false }),
  ).toBeVisible();
  await expect(page.getByRole("radio").first()).toBeVisible();
  await page.getByRole("radio").first().check();
  await page.getByRole("button", { name: /提交答卷/ }).click();
  const submission = page.waitForResponse((r) =>
    r.url().endsWith(`/api/v1/assessments/${exam.id}/submit`),
  );
  await page.getByRole("button", { name: /确\s*定/, exact: true }).click();
  const submitted = await submission;
  expect(submitted.status()).toBe(202);
  const assessmentRunId = (await submitted.json()).data.id;
  const assessmentRun = await page.request.get(
    `/api/v1/runs/${assessmentRunId}`,
  );
  expect(assessmentRun.ok()).toBeTruthy();
  evidence.assessment_run = {
    id: assessmentRunId,
    status: (await assessmentRun.json()).data.status,
  };
  expect(["queued", "running", "waiting_approval", "succeeded"]).toContain(
    evidence.assessment_run.status,
  );
  await page.goto("/#assessments");
  await page.reload();
  await page.getByRole("searchbox", { name: "搜索测评" }).fill(examTitle);
  const retesting = page.waitForResponse((r) =>
    r.url().endsWith(`/api/v1/assessments/${exam.id}/retest`),
  );
  await page.getByRole("button", { name: "创建复测" }).click();
  const retestResponse = await retesting;
  expect(retestResponse.status()).toBe(201);
  expect((await retestResponse.json()).data.status).toBe("draft");
  await page.goto("/#learning");
  await page.reload();

  const course = await create("courses", {
    title: `合成浏览器验收课程${suffix}`,
    content: "合成浏览器验收：真实接口学习与考核验证",
    duration_seconds: 1,
    skills: ["Python"],
    quiz: [
      {
        id: "live-q",
        title: "Python函数关键字",
        question_type: "single",
        options: ["def", "function"],
        answer: "def",
        points: 100,
      },
    ],
  });
  const plan = await create("training-plans", {
    title: `合成浏览器验收学习计划${suffix}`,
    talent_id: talent.id,
    course_ids: [course.id],
  });
  evidence.plan_id = plan.id;
  evidence.course_id = course.id;
  await page.goto("/#learning");
  await page.reload();
  await page.getByRole("searchbox", { name: "搜索培训计划" }).fill(plan.title);
  await page.getByRole("button", { name: "进入学习" }).click();
  await page.getByRole("button", { name: "学习课程" }).click();
  await expect(
    page.getByRole("button", { name: "提交课程考核" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "标记已学到结尾" }).click();
  await page.getByRole("button", { name: "保存学习进度" }).click();
  await expect(
    page.getByRole("button", { name: "提交课程考核" }),
  ).toBeEnabled();
  await page.getByRole("radio", { name: "def", exact: true }).check();
  await page.getByRole("button", { name: "提交课程考核" }).click();
  await expect(
    page.getByText("100 分 · 通过（及格 80 分，第 1 次）", { exact: true }),
  ).toBeVisible();
  evidence.quiz_score = 100;
  await capture("learning-desktop.png");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/#dashboard");
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "工作概览", exact: true }),
  ).toBeVisible();
  await capture("portal-mobile.png");
  await page.getByRole("button", { name: "打开导航" }).click();
  await page
    .getByRole("menuitem", { name: /培训与学习/ })
    .last()
    .click();
  await page.getByRole("searchbox", { name: "搜索培训计划" }).fill(plan.title);
  await page.getByRole("button", { name: "进入学习" }).click();
  await page.getByRole("button", { name: "学习课程" }).click();
  await expect(
    page.getByRole("heading", { name: course.title, exact: true }),
  ).toBeInViewport();
  await expect(
    page.getByRole("button", { name: "提交课程考核" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await capture("learning-mobile.png");
  await page.setViewportSize({ width: 1440, height: 1000 });
  const growth = await page.request.get(`/api/v1/talents/${talent.id}/growth`);
  expect(growth.ok()).toBeTruthy();
  expect((await growth.json()).data.events.length).toBeGreaterThan(0);
  evidence.growth_events = (await growth.json()).data.events.length;
  await page.goto("/#talents");
  await page.reload();
  await page.getByRole("searchbox", { name: "搜索人才档案" }).fill(name);
  await page
    .getByRole("row")
    .filter({ hasText: name })
    .getByRole("button", { name: /删\s*除/, exact: true })
    .click();
  const deleting = page.waitForResponse(
    (r) =>
      r.url().endsWith(`/api/v1/talents/${talent.id}`) &&
      r.request().method() === "DELETE",
  );
  await page.getByRole("button", { name: /确\s*定/, exact: true }).click();
  expect((await deleting).ok()).toBeTruthy();
  await expect(page.getByRole("button", { name, exact: true })).toHaveCount(0);
  await page.goto("/#jobs");
  await page.reload();
  await page.getByRole("button", { name: "导入岗位文件" }).click();
  await page
    .getByLabel("岗位名称", { exact: true })
    .fill(`合成浏览器验收文件岗位${suffix}`);
  await page.locator('input[type="file"]').setInputFiles({
    name: "synthetic-browser-job.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(
      "合成浏览器验收岗位：数据工程师，需要Python、SQL与数据治理经验。此为合成数据。",
      "utf8",
    ),
  });
  const uploaded = page.waitForResponse((r) =>
    r.url().endsWith("/api/v1/jobs/import"),
  );
  await page.getByRole("button", { name: "上传并解析岗位" }).click();
  const uploadResponse = await uploaded;
  expect(uploadResponse.status()).toBe(202);
  const jobRun = (await uploadResponse.json()).data.id;
  await expect(page.getByText(jobRun, { exact: true })).toBeVisible();
  const jobState = await page.request.get(`/api/v1/runs/${jobRun}`);
  expect(jobState.ok()).toBeTruthy();
  evidence.job_import_run = {
    id: jobRun,
    status: (await jobState.json()).data.status,
  };
  const evidencePath = test.info().outputPath("evidence.json");
  writeFileSync(evidencePath, JSON.stringify(evidence, null, 2), "utf8");
  await test
    .info()
    .attach("synthetic-acceptance-evidence.json", {
      path: evidencePath,
      contentType: "application/json",
    });
});
