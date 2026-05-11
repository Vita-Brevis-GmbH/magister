/* @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";
import { CreateClassModal } from "./_app.classes";

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

describe("CreateClassModal", () => {
  it("submits name + kuerzel + jahrgangsstufe and omits school_id for schulleitung", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        id: 7,
        school_id: 1,
        name: "4a",
        kuerzel: "4A",
        jahrgangsstufe: 4,
        status: "active",
        created_at: "2026-05-08T12:00:00+00:00",
        updated_at: "2026-05-08T12:00:00+00:00",
      }),
    );

    renderWithQuery(
      <CreateClassModal open={true} onClose={() => {}} defaultSchoolId={1} isAdmin={false} />,
    );
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/^name$/i), "4a");
    await user.type(screen.getByLabelText(/kürzel/i), "4A");
    await user.type(screen.getByLabelText(/jahrgangsstufe/i), "4");
    await user.click(screen.getByRole("button", { name: /anlegen/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledOnce();
    });
    expect(fetchMock.mock.calls[0]![0]).toBe("/api/classes");
    const body = JSON.parse((fetchMock.mock.calls[0]![1] as RequestInit).body as string) as Record<
      string,
      unknown
    >;
    expect(body).toEqual({ name: "4a", kuerzel: "4A", jahrgangsstufe: 4 });
    expect(body).not.toHaveProperty("school_id");
  });

  it("requires + sends school_id when isAdmin", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        id: 8,
        school_id: 42,
        name: "5b",
        kuerzel: null,
        jahrgangsstufe: 5,
        status: "active",
        created_at: "2026-05-08T12:00:00+00:00",
        updated_at: "2026-05-08T12:00:00+00:00",
      }),
    );

    renderWithQuery(
      <CreateClassModal open={true} onClose={() => {}} defaultSchoolId={null} isAdmin={true} />,
    );
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/^name$/i), "5b");
    await user.type(screen.getByLabelText(/jahrgangsstufe/i), "5");
    await user.type(screen.getByLabelText(/school id/i), "42");
    await user.click(screen.getByRole("button", { name: /anlegen/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledOnce();
    });
    const body = JSON.parse((fetchMock.mock.calls[0]![1] as RequestInit).body as string) as Record<
      string,
      unknown
    >;
    expect(body.school_id).toBe(42);
  });
});
