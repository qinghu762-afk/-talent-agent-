import {
  fireEvent,
  render,
  screen,
  waitFor,
  cleanup,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";
import { TaskResult, MatchDimensions } from "./components";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  location.hash = "";
});
it("匹配四维使用中文标签，未设置维度不会显示为零分", () => {
  render(
    <MatchDimensions
      dimensions={{
        skills: { score: 80, weight: 0.4 },
        experience: { score: 75, weight: 0.25 },
        projects: { score: 90, weight: 0.25 },
        bonus: { score: null, weight: 0.1 },
      }}
    />,
  );
  expect(screen.getByText("项目相关性（权重 25%）")).toBeInTheDocument();
  expect(screen.getByText("岗位加分项（权重 10%）")).toBeInTheDocument();
  expect(screen.getByText("未设置，不参与评分")).toBeInTheDocument();
  expect(screen.queryByText("0 分", { exact: true })).not.toBeInTheDocument();
});
it("问数澄清只显示追问且不显示SQL或导出", () => {
  render(
    <TaskResult
      run={{
        id: "clarify1",
        result: {
          needs_clarification: true,
          question: "请指定统计季度",
          sql: "SELECT secret",
          report_id: "should-not-render",
          answer: "应隐藏",
        },
      }}
    />,
  );
  expect(screen.getByText("请指定统计季度")).toBeInTheDocument();
  expect(screen.queryByText("SELECT secret")).not.toBeInTheDocument();
  expect(screen.queryByText("应隐藏")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: "下载 Word 报告" }),
  ).not.toBeInTheDocument();
});
it("问数补充回答沿用服务端会话编号", async () => {
  location.hash = "analysis";
  const bodies: any[] = [];
  vi.stubGlobal("fetch", async (url: string, options?: RequestInit) => {
    let data: any = { items: [], total: 0 };
    if (url.endsWith("auth/me"))
      data = { id: "u1", username: "管理员", role: "admin" };
    else if (url.endsWith("/analysis")) {
      bodies.push(JSON.parse(options?.body as string));
      data = { id: bodies.length === 1 ? "clarify1" : "answer1" };
    } else if (url.endsWith("runs/clarify1"))
      data = {
        id: "clarify1",
        status: "succeeded",
        result: {
          needs_clarification: true,
          question: "请指定统计季度",
          session_id: "s1",
        },
      };
    else if (url.endsWith("runs/answer1"))
      data = {
        id: "answer1",
        status: "succeeded",
        result: { answer: "统计结果已返回", session_id: "s1" },
      };
    return new Response(JSON.stringify({ code: "ok", data }));
  });
  render(<App />);
  const question = await screen.findByRole("textbox", { name: "数据问题" });
  fireEvent.change(question, { target: { value: "统计员工人数" } });
  fireEvent.click(screen.getByRole("button", { name: "分析数据" }));
  await screen.findByText("请指定统计季度");
  fireEvent.change(question, { target: { value: "2026年第一季度" } });
  fireEvent.click(
    await screen.findByRole("button", { name: "补充并继续分析" }),
  );
  await waitFor(() =>
    expect(bodies[1]).toMatchObject({
      question: "2026年第一季度",
      session_id: "s1",
    }),
  );
  await screen.findByText("统计结果已返回");
});
it("未登录时显示中文登录入口并提交真实凭据", async () => {
  const calls: string[] = [];
  vi.stubGlobal("fetch", async (url: string, options?: RequestInit) => {
    calls.push(url);
    if (url.endsWith("/auth/me"))
      return new Response('{"message":"请登录"}', { status: 401 });
    if (url.endsWith("/auth/login"))
      return new Response(
        '{"code":"ok","data":{"id":"u1","username":"张三","role":"employee"}}',
      );
    return new Response('{"code":"ok","data":{"items":[],"total":0}}');
  });
  render(<App />);
  await screen.findByRole("button", { name: "登录工作台" });
  fireEvent.change(screen.getByLabelText("账号"), {
    target: { value: "zhangsan" },
  });
  fireEvent.change(screen.getByLabelText("密码"), {
    target: { value: "password123" },
  });
  fireEvent.click(screen.getByRole("button", { name: "登录工作台" }));
  await waitFor(() => expect(calls).toContain("/api/v1/auth/login"));
  await screen.findByText("张三");
  expect(
    screen.queryByRole("menuitem", { name: "账号与组织" }),
  ).not.toBeInTheDocument();
});
it("列表请求失败时显示服务端错误而非空成功", async () => {
  vi.stubGlobal("fetch", async (url: string) =>
    url.endsWith("/auth/me")
      ? new Response(
          '{"code":"ok","data":{"id":"u1","username":"管理员","role":"admin"}}',
        )
      : new Response('{"message":"数据服务暂不可用"}', { status: 503 }),
  );
  render(<App />);
  await screen.findByText("数据服务暂不可用");
  expect(screen.getByRole("button", { name: /重\s*试/ })).toBeInTheDocument();
});
