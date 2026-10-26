import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { App as AntApp, ConfigProvider } from "antd";
import App from "./App";
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
function mount() {
  return render(
    <ConfigProvider wave={{ disabled: true }}>
      <AntApp>
        <App />
      </AntApp>
    </ConfigProvider>,
  );
}
beforeEach(() => {
  window.getComputedStyle = vi
    .fn()
    .mockReturnValue({
      getPropertyValue: () => "",
      overflowX: "visible",
      overflowY: "visible",
    }) as unknown as typeof window.getComputedStyle;
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
describe("login and role permissions", () => {
  it("validates missing credentials, logs in, and excludes account management for normal users", async () => {
    const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
      if (url.endsWith("/auth/me")) return json({ detail: "请登录" }, 401);
      if (url.endsWith("/auth/login"))
        return json({
          user: { id: "one", username: "operator", role: "user" },
        });
      if (url.endsWith("/system"))
        return json({
          services: { postgres: { ok: true, detail: "" } },
          limits: { batch_files: 200, file_mb: 20 },
          models: {},
          mode: "private",
        });
      if (url.endsWith("/dashboard"))
        return json({
          talents: 0,
          indexed: 0,
          queued: 0,
          issues: 0,
          jobs: 0,
          documents: 0,
          failed: 0,
        });
      return json([]);
    });
    vi.stubGlobal("fetch", fetcher);
    mount();
    await screen.findByText("登录工作台");
    fireEvent.click(screen.getByRole("button", { name: /登\s*录/ }));
    await screen.findByText("请输入账号");
    expect(
      fetcher.mock.calls.filter((call) => call[0].endsWith("/auth/login")),
    ).toHaveLength(0);
    fireEvent.change(screen.getByLabelText("账号"), {
      target: { value: "operator" },
    });
    fireEvent.change(screen.getByLabelText("密码"), {
      target: { value: "password123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: /登\s*录/ }));
    await screen.findByText("导入简历");
    expect(screen.queryByText("账号管理")).not.toBeInTheDocument();
    expect(screen.getByText("operator")).toBeInTheDocument();
    const login = fetcher.mock.calls.find((call) =>
      call[0].endsWith("/auth/login"),
    );
    expect(JSON.parse(login![1]!.body as string)).toEqual({
      username: "operator",
      password: "password123456",
    });
  });
  it("shows service error instead of invented metrics", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url.endsWith("/auth/me")
          ? json({ id: "admin", username: "admin", role: "admin" })
          : url.endsWith("/dashboard")
            ? json({ detail: "暂时无法读取档案数量" }, 503)
            : url.endsWith("/system")
              ? json({
                  services: {},
                  limits: { batch_files: 200, file_mb: 20 },
                  models: {},
                  mode: "private",
                })
              : json([]),
      ),
    );
    mount();
    await screen.findByText("暂时无法读取档案数量");
    expect(screen.getByText("账号管理")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });
});
