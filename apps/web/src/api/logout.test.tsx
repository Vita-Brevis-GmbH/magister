/* @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { logoutTarget, useLogout } from "./hooks";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("location", { ...window.location, assign: vi.fn(), pathname: "/" });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function wrapper({ children }: { children: React.ReactNode }): JSX.Element {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const KC_LOGOUT =
  "https://sso.example.ch/realms/kunde-a/protocol/openid-connect/logout" +
  "?client_id=magister&post_logout_redirect_uri=https%3A%2F%2Fkunde-a-um.example.ch%2Flogin";

describe("logout (ADR-0025)", () => {
  it("follows the realm's logout address the server names", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ ok: true, redirect: KC_LOGOUT }), {
        headers: { "content-type": "application/json" },
      }),
    );
    const { result } = renderHook(() => useLogout(), { wrapper });
    act(() => result.current.mutate());
    await waitFor(() => expect(window.location.assign).toHaveBeenCalledWith(KC_LOGOUT));
  });

  it("lands on /login without a redirect (local or operator session)", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        headers: { "content-type": "application/json" },
      }),
    );
    const { result } = renderHook(() => useLogout(), { wrapper });
    act(() => result.current.mutate());
    await waitFor(() => expect(window.location.assign).toHaveBeenCalledWith("/login"));
  });

  it("lands on /login when the server call fails", async () => {
    fetchMock.mockResolvedValue(new Response("boom", { status: 500 }));
    const { result } = renderHook(() => useLogout(), { wrapper });
    act(() => result.current.mutate());
    await waitFor(() => expect(window.location.assign).toHaveBeenCalledWith("/login"));
  });

  it("only follows absolute http(s) addresses", () => {
    expect(logoutTarget({ ok: true, redirect: "javascript:alert(1)" })).toBe("/login");
    expect(logoutTarget({ ok: true, redirect: "//evil.example" })).toBe("/login");
    expect(logoutTarget(undefined)).toBe("/login");
    expect(logoutTarget({ ok: true, redirect: KC_LOGOUT })).toBe(KC_LOGOUT);
  });
});
