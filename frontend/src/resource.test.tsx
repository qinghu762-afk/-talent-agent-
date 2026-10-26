import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { isActive, useResource } from "./api";
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
describe("active work polling lifecycle", () => {
  it("polls dispatched work and stops once completed", async () => {
    vi.useFakeTimers();
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: "dispatched" })),
      )
      .mockResolvedValue(new Response(JSON.stringify({ status: "completed" })));
    vi.stubGlobal("fetch", fetcher);
    const hook = renderHook(() =>
      useResource<{ status: string }>("/tasks/one", (data) =>
        isActive(data.status),
      ),
    );
    await act(async () => {});
    expect(hook.result.current.data?.status).toBe("dispatched");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(hook.result.current.data?.status).toBe("completed");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(12000);
    });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it("cancels pending work and clears its timer when the page unmounts", async () => {
    vi.useFakeTimers();
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ status: "running" })));
    vi.stubGlobal("fetch", fetcher);
    const hook = renderHook(() =>
      useResource<{ status: string }>("/matches/one", (data) =>
        isActive(data.status),
      ),
    );
    await act(async () => {});
    hook.unmount();
    await vi.advanceTimersByTimeAsync(9000);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
  });
  it("retains current detail while refreshing the same path", async () => {
    let finish!: (value: Response) => void;
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ name: "现有档案" })))
      .mockImplementation(
        () =>
          new Promise<Response>((resolve) => {
            finish = resolve;
          }),
      );
    vi.stubGlobal("fetch", fetcher);
    const hook = renderHook(() =>
      useResource<{ name: string }>("/talents/one"),
    );
    await waitFor(() =>
      expect(hook.result.current.data?.name).toBe("现有档案"),
    );
    act(() => hook.result.current.reload());
    expect(hook.result.current.data?.name).toBe("现有档案");
    await act(async () => {
      finish(new Response(JSON.stringify({ name: "更新档案" })));
    });
    expect(hook.result.current.data?.name).toBe("更新档案");
  });
});
