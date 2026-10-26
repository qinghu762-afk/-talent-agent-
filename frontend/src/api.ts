import { useCallback, useEffect, useRef, useState } from "react";
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export async function api<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    headers,
    credentials: "include",
  });
  if (!response.ok) {
    let message = `请求未完成（${response.status}），请稍后重试`;
    try {
      const body = await response.json();
      message =
        typeof body.detail === "string"
          ? body.detail
          : response.status === 422
            ? "填写内容不符合要求，请检查后重试"
            : message;
    } catch {
      /* non-JSON server error */
    }
    if (response.status === 401)
      window.dispatchEvent(new Event("session-expired"));
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}
export const isActive = (status: string) =>
  [
    "queued",
    "dispatched",
    "pending",
    "running",
    "processing",
    "parsing",
    "indexing",
    "retry",
    "retrying",
  ].includes(status);
export function validateFiles(
  files: File[],
  maxFiles: number,
  maxMB: number,
  allowArchive = true,
) {
  if (!files.length) return "请先选择文件";
  if (files.length > maxFiles) return `每批最多 ${maxFiles} 个文件`;
  for (const file of files) {
    if (
      !/\.(pdf|docx?|png|jpe?g|txt)$/i.test(file.name) &&
      !(allowArchive && /\.zip$/i.test(file.name))
    )
      return `${file.name} 的文件格式不支持`;
    if (file.size > maxMB * 1024 * 1024)
      return `${file.name} 的大小超过 ${maxMB} MB`;
  }
  if (files.reduce((sum, file) => sum + file.size, 0) > 200 * 1024 * 1024)
    return "每批文件总大小不能超过 200 MB";
  return null;
}
export function toggleComparison(current: string[], id: string) {
  return current.includes(id)
    ? current.filter((item) => item !== id)
    : current.length < 3
      ? [...current, id]
      : current;
}
export function useResource<T>(
  path: string | null,
  poll?: (data: T) => boolean,
) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(Boolean(path));
  const [version, setVersion] = useState(0);
  const pollRef = useRef(poll);
  pollRef.current = poll;
  const previousPath = useRef(path);
  const reload = useCallback(() => setVersion((v) => v + 1), []);
  useEffect(() => {
    if (previousPath.current !== path) {
      setData(undefined);
      previousPath.current = path;
    }
    if (!path) {
      setData(undefined);
      setLoading(false);
      return;
    }
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    async function read() {
      try {
        const value = await api<T>(path!, { signal: controller.signal });
        if (alive) {
          setData(value);
          setError("");
          if (pollRef.current?.(value)) timer = setTimeout(read, 3000);
        }
      } catch (e) {
        if (alive && !(e instanceof DOMException && e.name === "AbortError"))
          setError(e instanceof Error ? e.message : "请求失败");
      } finally {
        if (alive) setLoading(false);
      }
    }
    void read();
    return () => {
      alive = false;
      controller.abort();
      clearTimeout(timer);
    };
  }, [path, version]);
  return { data, error, loading, reload };
}
