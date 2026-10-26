import { afterEach, describe, expect, it, vi } from "vitest";
import {
  api,
  ApiError,
  items,
  visiblePages,
  chartOption,
  deadlineRemaining,
  taskId,
} from "./api";
afterEach(() => vi.unstubAllGlobals());
describe("平台安全请求与角色", () => {
  it("知识材料优先跟踪后台任务编号", () => {
    expect(taskId({ id: "knowledge-1", run_id: "run-1" })).toBe("run-1");
    expect(taskId({ id: "run-2" })).toBe("run-2");
  });
  it("重新打开测评时按服务端截止时间恢复倒计时", () => {
    expect(
      deadlineRemaining(
        { deadline: "2026-10-21T10:01:00Z" },
        Date.parse("2026-10-21T10:00:00Z"),
      ),
    ).toBe(60);
    expect(
      deadlineRemaining(
        { deadline: "2026-10-21T09:00:00Z" },
        Date.parse("2026-10-21T10:00:00Z"),
      ),
    ).toBe(0);
  });
  it("分析结果转为可绘制且可核对的坐标轴", () => {
    const option = chartOption({
      type: "bar",
      x: "组织",
      y: "人数",
      data: [
        ["研发", 12],
        ["销售", 8],
      ],
    });
    expect(option?.xAxis.data).toEqual(["研发", "销售"]);
    expect(option?.series[0].data).toEqual([12, 8]);
    expect(chartOption(null)).toBeNull();
  });
  it("使用cookie并提取统一envelope", async () => {
    let sent: RequestInit | undefined;
    vi.stubGlobal("fetch", async (_url: string, options: RequestInit) => {
      sent = options;
      return new Response(
        JSON.stringify({
          code: "ok",
          data: { items: [{ id: "t1" }], total: 1 },
        }),
      );
    });
    expect(items(await api("talents"))).toEqual([{ id: "t1" }]);
    expect(sent?.credentials).toBe("include");
  });
  it("拒绝403并保留服务端错误", async () => {
    vi.stubGlobal(
      "fetch",
      async () =>
        new Response(
          JSON.stringify({ code: "forbidden", message: "无权访问此组织" }),
          { status: 403 },
        ),
    );
    await expect(api("users")).rejects.toMatchObject({
      status: 403,
      message: "无权访问此组织",
    });
    expect(ApiError).toBeDefined();
  });
  it("员工只能看自己的学习测评入口", () => {
    expect(visiblePages("employee")).toContain("learning");
    expect(visiblePages("employee")).not.toContain("users");
    expect(visiblePages("manager")).toContain("approvals");
    expect(visiblePages("hr")).toContain("talents");
  });
  it("上传表单不设置JSON内容类型", async () => {
    let headers: HeadersInit | undefined;
    vi.stubGlobal("fetch", async (_url: string, options: RequestInit) => {
      headers = options.headers;
      return new Response('{"code":"ok","data":{"id":"r1"}}');
    });
    await api("talents/import", { method: "POST", body: new FormData() });
    expect(new Headers(headers).has("Content-Type")).toBe(false);
  });
});
