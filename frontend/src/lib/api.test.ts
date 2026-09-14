import { afterEach, expect, it, vi } from "vitest";
import { api, download, setToken } from "./api";
afterEach(() => {
  setToken("");
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
it("rejects off-origin downloads and unsafe paths before sending credentials", async () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  setToken("test-only-token");
  await expect(download("https://example.invalid/file", "x")).rejects.toThrow(
    "project API",
  );
  await expect(api("//example.invalid")).rejects.toThrow("Invalid API");
  expect(fetcher).not.toHaveBeenCalled();
});
it("retains the deadline while the response body is still arriving", async () => {
  vi.useFakeTimers();
  const fetcher = vi.fn((_url, init) =>
    Promise.resolve({
      ok: true,
      json: () =>
        new Promise((_resolve, reject) =>
          init.signal.addEventListener("abort", () =>
            reject(new Error("aborted")),
          ),
        ),
    }),
  );
  vi.stubGlobal("fetch", fetcher);
  const result = expect(api("/parcels")).rejects.toThrow("timed out");
  await vi.advanceTimersByTimeAsync(20001);
  await result;
  expect(fetcher).toHaveBeenCalledTimes(1);
});
it("does not retry an interrupted write and warns about uncertain completion", async () => {
  vi.useFakeTimers();
  const fetcher = vi.fn(
    (_url, init) =>
      new Promise((_resolve, reject) =>
        init.signal.addEventListener("abort", () =>
          reject(new Error("aborted")),
        ),
      ),
  );
  vi.stubGlobal("fetch", fetcher);
  const result = expect(api("/reviews", { object_id: "test" })).rejects.toThrow(
    "Check the saved record or job",
  );
  await vi.advanceTimersByTimeAsync(20001);
  await result;
  expect(fetcher).toHaveBeenCalledTimes(1);
});
it("preserves server status for deliberate read retry decisions", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ detail: "Permission denied" }), {
          status: 403,
        }),
      ),
  );
  await expect(api("/audit")).rejects.toMatchObject({
    status: 403,
    message: "Permission denied",
  });
});
