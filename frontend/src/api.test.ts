import { afterEach, describe, expect, it, vi } from "vitest";
import { api, validateFiles, isActive, toggleComparison } from "./api";
afterEach(() => vi.unstubAllGlobals());
describe("authenticated API boundary", () => {
  it("includes cookies and surfaces a revision conflict without discarding it", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ detail: "档案已被其他用户修改" }), {
          status: 409,
          headers: { "Content-Type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetcher);
    await expect(
      api("/talents/42", {
        method: "PUT",
        body: JSON.stringify({ revision: 2 }),
      }),
    ).rejects.toThrow("档案已被其他用户修改");
    expect(fetcher.mock.calls[0][0]).toBe("/api/v1/talents/42");
    expect(fetcher.mock.calls[0][1].credentials).toBe("include");
  });
  it("does not set JSON content type for multipart uploads", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", fetcher);
    await api("/batches", { method: "POST", body: new FormData() });
    expect(
      new Headers(fetcher.mock.calls[0][1].headers).has("Content-Type"),
    ).toBe(false);
  });
});
describe("workflow constraints", () => {
  it("rejects the whole oversized batch before upload", () =>
    expect(
      validateFiles(
        Array.from({ length: 201 }, () => new File(["a"], "cv.pdf")),
        200,
        20,
      ),
    ).toMatch("200"));
  it("rejects oversized or unsupported files and accepts supported resumes", () => {
    expect(validateFiles([new File(["hello"], "cv.exe")], 200, 20)).toMatch(
      "格式",
    );
    expect(
      validateFiles([new File(["a".repeat(2048)], "cv.pdf")], 200, 0.001),
    ).toMatch("大小");
    expect(
      validateFiles(
        [new File(["a"], "cv.pdf"), new File(["a"], "cv.docx")],
        200,
        20,
      ),
    ).toBeNull();
  });
  it("polls only nonterminal work", () => {
    expect(isActive("queued")).toBe(true);
    expect(isActive("running")).toBe(true);
    expect(isActive("failed")).toBe(false);
    expect(isActive("completed")).toBe(false);
  });
  it("limits comparison to three distinct candidates and allows deselect", () => {
    expect(toggleComparison(["a", "b", "c"], "d")).toEqual(["a", "b", "c"]);
    expect(toggleComparison(["a", "b"], "a")).toEqual(["b"]);
    expect(toggleComparison(["a"], "b")).toEqual(["a", "b"]);
  });
});
