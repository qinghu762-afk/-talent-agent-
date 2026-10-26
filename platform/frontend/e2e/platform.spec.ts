import { test, expect, type Page } from "@playwright/test";
const admin = { id: "u1", username: "测试管理员", role: "admin", org_id: "o1" };
async function fixture(page: Page, role = "admin") {
  const calls: { path: string; method: string; body: any }[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(),
      path = new URL(request.url()).pathname.replace("/api/v1/", ""),
      method = request.method();
    let body: any;
    try {
      body = request.postDataJSON();
    } catch {}
    calls.push({ path, method, body });
    let data: any = { items: [], total: 0 };
    if (path === "auth/me") data = { ...admin, role };
    else if (path === "dashboard")
      data = {
        counts: { talents: 0, jobs: 0, assessments: 1, training: 1, runs: 0 },
      };
    else if (path === "jobs")
      data = {
        items: [
          {
            id: "j1",
            title: "数据工程师",
            requirements: { required_skills: ["Python"] },
            status: "active",
          },
        ],
        total: 1,
      };
    else if (path === "jobs/j1/match") data = { id: "r-match" };
    else if (path === "talents/text") data = { id: "r-resume" };
    else if (path === "knowledge/text")
      data = { id: "k1", run_id: "r-knowledge", title: body.title };
    else if (path === "assessments")
      data = {
        items: [
          {
            id: "a1",
            title: "Python能力测评",
            status: "published",
            duration_minutes: 30,
          },
        ],
        total: 1,
      };
    else if (path === "assessments/a1" || path === "assessments/a1/start")
      data = {
        id: "a1",
        title: "Python能力测评",
        status: method === "POST" ? "started" : "published",
        deadline: new Date(Date.now() + 1800000).toISOString(),
        duration_minutes: 30,
        questions: [
          {
            id: "q1",
            title: "选择Python关键字",
            question_type: "single",
            options: ["def", "function"],
            points: 100,
          },
        ],
      };
    else if (path === "assessments/a1/submit") data = { id: "r-assessment" };
    else if (path === "runs/r-match")
      data = {
        id: "r-match",
        status: "succeeded",
        progress: 100,
        result: {
          candidates: [
            {
              talent_id: "t1",
              name: "测试候选人",
              revision: 2,
              score: {
                eligible: true,
                total: 82,
                dimensions: {
                  skills: { score: 88, weight: 0.4 },
                  experience: { score: 76, weight: 0.25 },
                  projects: { score: 84, weight: 0.25 },
                  bonus: { score: null, weight: 0.1 },
                },
                strengths: ["Python技能有原文支持"],
                gaps: ["需核实数据仓库项目"],
                evidence: [
                  { quote: "负责Python数据管道开发", source_id: "d1" },
                ],
              },
              profile: { name: "测试候选人", skills: ["Python"] },
            },
          ],
          diagnostics: { searched: 1 },
          versions: { chat: "test-model" },
        },
      };
    else if (path.startsWith("runs/"))
      data = {
        id: path.split("/")[1],
        status: "succeeded",
        progress: 100,
        result: { answer: "任务完成", citations: [] },
      };
    else if (path === "training-plans")
      data = {
        items: [
          {
            id: "p1",
            title: "数据能力培养",
            status: "assigned",
            course_ids: ["c1"],
          },
        ],
        total: 1,
      };
    else if (path === "training-plans/p1")
      data = {
        id: "p1",
        title: "数据能力培养",
        status: "assigned",
        course_ids: ["c1"],
        progress: {},
      };
    else if (path === "courses/c1")
      data = {
        id: "c1",
        title: "Python数据入门",
        content: "课程正文与练习说明",
        duration_seconds: 300,
      };
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        code: "ok",
        data,
        request_id: "browser-contract-test",
      }),
    });
  });
  return calls;
}
test("管理员各模块可打开且空状态可操作", async ({ page }) => {
  await fixture(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "工作概览" })).toBeVisible();
  for (const [hash, title] of [
    ["talents", "人才档案"],
    ["questions", "题库"],
    ["courses", "课程资源"],
    ["knowledge", "知识库"],
    ["approvals", "审批待办"],
    ["runs", "任务中心"],
    ["notifications", "通知"],
    ["skills", "Skills"],
    ["automations", "定时自动化"],
    ["users", "账号与组织"],
    ["issues", "审计与异常"],
  ]) {
    await page.goto("/#" + hash);
    await expect(
      page.getByRole("heading", { name: title, exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /刷\s*新/ }).first(),
    ).toBeVisible();
  }
  await page.goto("/#chat");
  await expect(page.getByRole("textbox", { name: "知识问题" })).toBeVisible();
  await page.goto("/#analysis");
  await expect(page.getByRole("textbox", { name: "数据问题" })).toBeVisible();
  await page.screenshot({
    path: "test-results/desktop-workbench.png",
    fullPage: true,
  });
});
test("粘贴履历提交真实契约并打开运行进度", async ({ page }) => {
  const calls = await fixture(page);
  await page.goto("/#talents");
  await page.getByRole("button", { name: "导入履历" }).click();
  await page.getByText("粘贴文本", { exact: true }).click();
  await page
    .getByLabel("履历全文")
    .fill("测试候选人，Python工程师，2020年起从事数据开发。");
  await page.getByRole("button", { name: "保存并处理" }).click();
  await expect(page.getByText("r-resume", { exact: true })).toBeVisible();
  expect(
    calls.find((call) => call.path === "talents/text")?.body.text,
  ).toContain("Python工程师");
});
test("知识新增跟踪run_id而非知识记录id", async ({ page }) => {
  const calls = await fixture(page);
  await page.goto("/#knowledge");
  await page.getByRole("button", { name: "新增知识材料" }).click();
  await page.getByText("粘贴文本", { exact: true }).click();
  await page.getByLabel("标题", { exact: true }).fill("测试学习制度");
  await page.getByLabel("知识正文").fill("员工应按计划完成学习。");
  await page.getByRole("button", { name: "保存并处理" }).click();
  await expect(page.getByText("r-knowledge", { exact: true })).toBeVisible();
  expect(calls.some((call) => call.path === "runs/k1")).toBe(false);
});
test("匹配结果展示分值、条件、证据和CSV出口", async ({ page }) => {
  await fixture(page);
  await page.goto("/#jobs");
  await page.getByRole("button", { name: "运行匹配" }).click();
  await expect(
    page.getByText("测试候选人", { exact: true }).first(),
  ).toBeVisible();
  await expect(page.getByText("82 分", { exact: true })).toBeVisible();
  await expect(
    page.getByText("项目相关性（权重 25%）", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("岗位加分项（权重 10%）", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("未设置，不参与评分", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("负责Python数据管道开发", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "导出候选人 CSV" }),
  ).toHaveAttribute("href", "/api/v1/matches/r-match/export.csv");
  await page.screenshot({
    path: "test-results/matching-evidence.png",
    fullPage: true,
  });
});
test("员工完成获批测评并提交选项原文", async ({ page }) => {
  const calls = await fixture(page, "employee");
  await page.goto("/#assessments");
  await expect(page.getByRole("menuitem", { name: /账号与组织/ })).toHaveCount(
    0,
  );
  await page.getByRole("button", { name: "进入测评" }).click();
  await page.getByRole("button", { name: "开始测评" }).click();
  await page.getByRole("radio", { name: "def", exact: true }).check();
  await page.getByRole("button", { name: /提交答卷/ }).click();
  await page.getByRole("button", { name: /确\s*定/ }).click();
  await expect(page.getByText("r-assessment", { exact: true })).toBeVisible();
  expect(
    calls.find((call) => call.path === "assessments/a1/submit")?.body.answers,
  ).toEqual({ q1: "def" });
});
test("移动端导航无管理入口、可以进入课程并记录进度", async ({ page }) => {
  const calls = await fixture(page, "employee");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "打开导航" }).click();
  await page
    .getByRole("menuitem", { name: /培训与学习/ })
    .last()
    .click();
  await page.getByRole("button", { name: "进入学习" }).click();
  await page.getByRole("button", { name: "学习课程" }).click();
  await expect(page.getByText("课程正文与练习说明")).toBeVisible();
  await page.getByRole("button", { name: "保存学习进度" }).click();
  await expect
    .poll(() =>
      calls.some((call) => call.path === "training-plans/p1/progress"),
    )
    .toBe(true);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/mobile-learning.png",
    fullPage: true,
  });
});
test("403、服务故障和非法页面有明确反馈", async ({ page }) => {
  await fixture(page, "employee");
  await page.goto("/#users");
  await expect(page.getByText("无权访问此页面")).toBeVisible();
  await page.route("**/api/v1/assessments", (route) =>
    route.fulfill({
      status: 403,
      contentType: "application/json",
      body: JSON.stringify({
        code: "forbidden",
        message: "仅可访问自己的测评",
      }),
    }),
  );
  await page.goto("/#assessments");
  await expect(page.getByText("无权执行此操作")).toBeVisible();
  await expect(page.getByRole("button", { name: /重\s*试/ })).toBeVisible();
});

test("人才自然语言检索使用items结果并展示原文证据", async ({ page }) => {
  const calls = await fixture(page);
  const respond = (route: any, data: any) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ code: "ok", data }),
    });
  await page.route("**/api/v1/talents/search", (route) =>
    respond(route, { id: "r-search" }),
  );
  await page.route("**/api/v1/runs/r-search", (route) =>
    respond(route, {
      id: "r-search",
      kind: "search",
      status: "succeeded",
      result: {
        items: [
          {
            talent_id: "t1",
            name: "检索候选人",
            similarity: 0.92,
            revision: 3,
            evidence: [{ quote: "主导Python数据治理项目" }],
            profile: { skills: ["Python"] },
          },
        ],
        total: 1,
      },
    }),
  );
  await page.goto("/#talents");
  await page
    .getByRole("textbox", { name: "人才检索需求" })
    .fill("Python数据治理");
  await page.getByRole("button", { name: "智能检索" }).click();
  await expect(page.getByRole("heading", { name: "检索候选人" })).toBeVisible();
  await expect(
    page.getByText("主导Python数据治理项目", { exact: true }),
  ).toBeVisible();
});

test("课程完成前禁考、有效进度后提交选项原文并展示成绩", async ({ page }) => {
  await fixture(page, "employee");
  let complete = false;
  let submitted: any;
  const respond = (route: any, data: any) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ code: "ok", data }),
    });
  await page.route("**/api/v1/training-plans/p1", (route) =>
    respond(route, {
      id: "p1",
      title: "数据能力培养",
      course_ids: ["c1"],
      progress: {
        c1: { completed: complete, position_seconds: complete ? 300 : 0 },
      },
    }),
  );
  await page.route("**/api/v1/courses/c1", (route) =>
    respond(route, {
      id: "c1",
      title: "Python数据入门",
      content: "课程内容",
      duration_seconds: 300,
      quiz: [
        {
          id: "cq1",
          title: "选择Python关键字",
          question_type: "single",
          options: ["def", "function"],
        },
      ],
    }),
  );
  await page.route("**/api/v1/training-plans/p1/progress", (route) => {
    complete = true;
    return respond(route, {
      progress: { c1: { completed: true, position_seconds: 300 } },
    });
  });
  await page.route("**/api/v1/training-plans/p1/quiz", (route) => {
    submitted = route.request().postDataJSON();
    return respond(route, {
      score: 100,
      passed: true,
      threshold: 80,
      attempt: 1,
    });
  });
  await page.goto("/#learning");
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
  expect(submitted).toEqual({ course_id: "c1", answers: { cq1: "def" } });
});

test("发布返回审批记录时不把审批编号当作运行任务", async ({ page }) => {
  const calls = await fixture(page);
  const respond = (route: any, data: any) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ code: "ok", data }),
    });
  await page.route("**/api/v1/assessments", (route) =>
    respond(route, {
      items: [{ id: "draft1", title: "待发布测评", status: "draft" }],
      total: 1,
    }),
  );
  await page.route("**/api/v1/assessments/draft1/publish", (route) =>
    respond(route, {
      id: "approval1",
      kind: "assessment_publish",
      status: "pending",
    }),
  );
  await page.goto("/#assessments");
  await page.getByRole("button", { name: "提交发布审批" }).click();
  await expect(page.getByText("操作已完成", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("dialog", { name: "任务进度与结果" }),
  ).toHaveCount(0);
  expect(calls.some((call) => call.path === "runs/approval1")).toBe(false);
});

test("角色模板维护与账号模板关联提交权限策略", async ({ page }) => {
  await fixture(page);
  let rolePayload: any, userPayload: any;
  const template = {
    id: "role1",
    name: "受限HR",
    base_role: "hr",
    permissions: ["GET:talents"],
    denied_fields: ["phone"],
    data_scope: "org",
  };
  const respond = (route: any, data: any) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ code: "ok", data }),
    });
  await page.route("**/api/v1/roles", (route) => {
    if (route.request().method() === "POST") {
      rolePayload = route.request().postDataJSON();
      return respond(route, { ...template, ...rolePayload });
    }
    return respond(route, { items: [template], total: 1 });
  });
  await page.route("**/api/v1/organizations", (route) =>
    respond(route, { items: [{ id: "o1", name: "测试组织" }], total: 1 }),
  );
  await page.route("**/api/v1/users", (route) => {
    if (route.request().method() === "POST") {
      userPayload = route.request().postDataJSON();
      return respond(route, { id: "new-user", ...userPayload });
    }
    return respond(route, { items: [], total: 0 });
  });
  await page.goto("/#users");
  await page.getByRole("button", { name: "新建角色模板" }).click();
  await page.getByLabel("模板名称", { exact: true }).fill("受限招聘HR");
  await page.getByLabel("基础角色", { exact: true }).click();
  await page.getByTitle("人力资源", { exact: true }).click();
  await page.getByRole("combobox", { name: "允许操作", exact: true }).click();
  await page.getByTitle("查看人才档案", { exact: true }).click();
  await page
    .getByRole("combobox", { name: "允许操作", exact: true })
    .press("Escape");
  await page.getByLabel("隐藏字段", { exact: true }).click();
  await page.getByTitle("电话", { exact: true }).click();
  await page.getByLabel("隐藏字段", { exact: true }).press("Escape");
  await page.getByLabel("模板名称", { exact: true }).click();
  await page.getByRole("button", { name: /保\s*存/, exact: true }).click();
  await expect.poll(() => rolePayload?.permissions).toEqual(["GET:talents"]);
  expect(rolePayload).toMatchObject({
    base_role: "hr",
    denied_fields: ["phone"],
    data_scope: "org",
  });
  await page.getByRole("button", { name: "新建账号" }).click();
  await page.getByLabel("账号", { exact: true }).fill("limited-hr");
  await page.getByLabel("密码", { exact: true }).fill("ContractTest123!");
  await page.getByLabel("角色模板", { exact: true }).click();
  await page.getByTitle("受限HR (role1)", { exact: true }).click();
  await expect(page.getByLabel("角色", { exact: true })).toBeDisabled();
  await page.getByLabel("所属组织", { exact: true }).click();
  await page.getByTitle("测试组织 (o1)", { exact: true }).click();
  await page.getByRole("button", { name: /保\s*存/, exact: true }).click();
  await expect.poll(() => userPayload?.role_template_id).toBe("role1");
  expect(userPayload.role).toBeUndefined();
});

test("事件自动化仅提交事件配置并保留事件参数引用", async ({ page }) => {
  await fixture(page);
  let payload: any;
  const respond = (route: any, data: any) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ code: "ok", data }),
    });
  await page.route("**/api/v1/skills", (route) =>
    respond(route, { items: [{ id: "skill1", name: "培养建议" }], total: 1 }),
  );
  await page.route("**/api/v1/automations", (route) => {
    if (route.request().method() === "POST") {
      payload = route.request().postDataJSON();
      return respond(route, { id: "auto1", ...payload });
    }
    return respond(route, { items: [], total: 0 });
  });
  await page.goto("/#automations");
  await page.getByRole("button", { name: "新建自动化" }).click();
  await page.getByLabel("名称", { exact: true }).fill("测评后生成培养建议");
  await page.getByLabel("关联Skill", { exact: true }).click();
  await page.getByTitle("培养建议 (skill1)", { exact: true }).click();
  await expect(page.getByLabel("执行间隔（秒）", { exact: true })).toHaveValue(
    "3600",
  );
  await page.getByLabel("触发方式", { exact: true }).focus();
  await page.getByLabel("触发方式", { exact: true }).press("ArrowDown");
  await page.getByTitle("事件触发", { exact: true }).click();
  await expect(page.getByLabel("执行间隔（秒）", { exact: true })).toHaveCount(
    0,
  );
  await page.getByLabel("业务事件", { exact: true }).click();
  await page.getByTitle("测评处理完成", { exact: true }).click();
  await page
    .getByLabel("执行参数", { exact: true })
    .fill('{"talent_id":"$event.talent_id"}');
  await page.getByRole("button", { name: /保\s*存/, exact: true }).click();
  await expect.poll(() => payload?.trigger).toBe("event");
  expect(payload).toMatchObject({
    event_kind: "assessment",
    parameters: { talent_id: "$event.talent_id" },
    enabled: true,
  });
  expect(payload.interval_seconds).toBeUndefined();
});

test("数据分析支持五类图形、适用性提示及主题尺寸切换", async ({ page }) => {
  await fixture(page);
  const submissions: any[] = [];
  const respond = (route: any, data: any) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ code: "ok", data }),
    });
  await page.route("**/api/v1/analysis", (route) => {
    submissions.push(route.request().postDataJSON());
    return respond(route, {
      id: submissions.length === 1 ? "analysis-clarify" : "analysis-chart1",
    });
  });
  await page.route("**/api/v1/runs/analysis-clarify", (route) =>
    respond(route, {
      id: "analysis-clarify",
      status: "succeeded",
      kind: "analysis",
      result: {
        needs_clarification: true,
        question: "请指定统计季度",
        session_id: "session-clarify",
      },
    }),
  );
  await page.route("**/api/v1/runs/analysis-chart1", (route) =>
    respond(route, {
      id: "analysis-chart1",
      status: "succeeded",
      kind: "analysis",
      result: {
        answer: "授权查询结果",
        columns: ["组织", "季度", "人数", "达标率", "课时"],
        rows: [
          ["研发", "Q1", 12, 90, 60],
          ["销售", "Q1", 8, 85, 40],
          ["研发", "Q2", 14, 92, 80],
        ],
      },
    }),
  );
  await page.goto("/#analysis");
  await page
    .getByRole("textbox", { name: "数据问题" })
    .fill("比较组织培养情况");
  await page.getByRole("button", { name: "分析数据" }).click();
  await expect(page.getByText("请指定统计季度", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "结果图表", exact: true }),
  ).toHaveCount(0);
  await expect(page.getByRole("link", { name: "下载 Word 报告" })).toHaveCount(
    0,
  );
  await page
    .getByRole("textbox", { name: "数据问题" })
    .fill("比较2026年第一和第二季度");
  await page.getByRole("button", { name: "补充并继续分析" }).click();
  expect(submissions[1]).toMatchObject({
    session_id: "session-clarify",
    question: "比较2026年第一和第二季度",
  });
  await expect(
    page.getByRole("img", { name: "授权数据查询柱状图", exact: true }),
  ).toBeVisible();
  const select = async (name: string, title: string) => {
    await page.getByRole("combobox", { name, exact: true }).focus();
    await page.getByRole("combobox", { name, exact: true }).press("ArrowDown");
    await page.getByTitle(title, { exact: true }).click();
  };
  await select("图表类型", "折线图");
  await expect(
    page.getByRole("img", { name: "授权数据查询折线图", exact: true }),
  ).toBeVisible();
  await select("图表类型", "饼图");
  await expect(
    page.getByRole("img", { name: "授权数据查询饼图", exact: true }),
  ).toBeVisible();
  await select("图表类型", "雷达图");
  await expect(
    page.getByText("雷达图需要至少三个数值指标，请增加指标选择。", {
      exact: true,
    }),
  ).toBeVisible();
  await select("数值指标", "达标率");
  await select("数值指标", "课时");
  await page.getByRole("heading", { name: "结果图表", exact: true }).click();
  await expect(
    page.getByRole("img", { name: "授权数据查询雷达图", exact: true }),
  ).toBeVisible();
  await select("图表类型", "热力图");
  await expect(
    page.getByRole("img", { name: "授权数据查询热力图", exact: true }),
  ).toBeVisible();
  await select("图表主题", "深色主题");
  await select("图表尺寸", "宽展");
  await expect(
    page.getByRole("img", { name: "授权数据查询热力图", exact: true }),
  ).toHaveCSS("height", "520px");
  await page.getByRole("heading", { name: "结果图表", exact: true }).click();
  await page
    .getByRole("combobox", { name: "图表尺寸", exact: true })
    .press("Escape");
  await expect(page.getByTitle("紧凑", { exact: true })).toBeHidden();
  await page
    .getByRole("heading", { name: "结果图表", exact: true })
    .locator("..")
    .screenshot({ path: "test-results/analysis-chart-dark.png" });
});
