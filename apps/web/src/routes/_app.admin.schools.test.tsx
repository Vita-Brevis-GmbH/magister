/* @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";
import { SchoolForm } from "./_app.admin.schools";

beforeAll(async () => {
  await i18n.changeLanguage("de");
});

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  document.cookie = "";
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

function renderWithQuery(node: React.ReactNode): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

function postBody(path: string): Record<string, unknown> {
  const call = fetchMock.mock.calls.find((c) => String(c[0]) === path);
  expect(call).toBeTruthy();
  return JSON.parse((call![1] as RequestInit).body as string) as Record<string, unknown>;
}

describe("SchoolModal (create)", () => {
  it("posts name/kuerzel/scope + address and nulls empty optional fields", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ id: 1, name: "PS Musterdorf", kuerzel: "PSM", scope_short: "PSM" }),
    );

    renderWithQuery(<SchoolForm target={null} onDone={() => {}} />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/^name$/i), "PS Musterdorf");
    await user.type(screen.getByLabelText(/^kürzel$/i), "PSM");
    await user.type(screen.getByLabelText(/bereichskürzel/i), "PSM");
    await user.type(screen.getByLabelText(/^ort$/i), "Bern");
    await user.click(screen.getByRole("button", { name: /speichern/i }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some((c) => String(c[0]) === "/api/schools")).toBe(true);
    });
    const body = postBody("/api/schools");
    expect(body.name).toBe("PS Musterdorf");
    expect(body.kuerzel).toBe("PSM");
    expect(body.scope_short).toBe("PSM");
    expect(body.city).toBe("Bern");
    expect(body.street).toBeNull();
    expect(body.latitude).toBeNull();
  });
});
