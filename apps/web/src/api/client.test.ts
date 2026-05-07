/* @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch, ApiError } from "./client";

const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  document.cookie = "";
  vi.stubGlobal("location", { ...window.location, assign: vi.fn(), pathname: "/" });
});
afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    ...init,
    headers: { "content-type": "application/json", ...(init.headers ?? {}) },
  });
}

describe("apiFetch", () => {
  it("returns parsed JSON on 2xx and prepends /api to absolute paths", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    const out = await apiFetch<{ ok: boolean }>("/healthz");
    expect(out).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0]![0]).toBe("/api/healthz");
  });

  it("attaches X-CSRF-Token from cookie on POST", async () => {
    document.cookie = "magister_csrf=abc123";
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await apiFetch("/classes", { method: "POST", body: { name: "4a" } });
    expect(fetchMock.mock.calls[0]![0]).toBe("/api/classes");
    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    const headers = init.headers as Headers;
    expect(headers.get("X-CSRF-Token")).toBe("abc123");
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("does NOT attach X-CSRF-Token on GET", async () => {
    document.cookie = "magister_csrf=abc123";
    fetchMock.mockResolvedValue(jsonResponse([]));
    await apiFetch("/classes");
    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    const headers = init.headers as Headers;
    expect(headers.get("X-CSRF-Token")).toBeNull();
  });

  it("throws ApiError with detail-code on 4xx", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "class_not_found" }, { status: 404 }));
    await expect(apiFetch("/classes/999")).rejects.toMatchObject({
      status: 404,
      code: "class_not_found",
    });
    await expect(apiFetch("/classes/999")).rejects.toBeInstanceOf(ApiError);
  });

  it("redirects to /login on 401", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "unauthenticated" }, { status: 401 }));
    await expect(apiFetch("/auth/me")).rejects.toBeInstanceOf(ApiError);
    expect(window.location.assign).toHaveBeenCalledWith("/login");
  });

  it("returns undefined for 204", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    const out = await apiFetch("/classes/1", { method: "DELETE" });
    expect(out).toBeUndefined();
  });
});
