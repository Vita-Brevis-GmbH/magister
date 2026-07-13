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

/** Route the fetch mock by path: /schools returns a list, everything else the class. */
function routeFetch(opts: { schools?: unknown; classResponse: unknown }): void {
  fetchMock.mockImplementation((input: string) => {
    const url = String(input);
    if (url.endsWith("/schools")) {
      return Promise.resolve(jsonResponse(opts.schools ?? []));
    }
    return Promise.resolve(jsonResponse(opts.classResponse));
  });
}

function classPostBody(): Record<string, unknown> {
  const call = fetchMock.mock.calls.find((c) => String(c[0]) === "/api/classes");
  expect(call).toBeTruthy();
  return JSON.parse((call![1] as RequestInit).body as string) as Record<string, unknown>;
}

describe("CreateClassModal", () => {
  it("submits name + kuerzel + jahrgangsstufe and omits school_id for schulleitung", async () => {
    routeFetch({
      classResponse: {
        id: 7,
        school_id: 1,
        name: "4a",
        kuerzel: "4A",
        jahrgangsstufe: 4,
        status: "active",
        created_at: "2026-05-08T12:00:00+00:00",
        updated_at: "2026-05-08T12:00:00+00:00",
      },
    });

    renderWithQuery(
      <CreateClassModal open={true} onClose={() => {}} defaultSchoolId={1} isAdmin={false} />,
    );
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/^name$/i), "4a");
    await user.type(screen.getByLabelText(/kürzel/i), "4A");
    await user.type(screen.getByLabelText(/jahrgangsstufe/i), "4");
    await user.click(screen.getByRole("button", { name: /anlegen/i }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some((c) => String(c[0]) === "/api/classes")).toBe(true);
    });
    const body = classPostBody();
    expect(body).toEqual({
      name: "4a",
      kuerzel: "4A",
      jahrgangsstufe: 4,
      jahrgangsstufe_bis: null,
      details: null,
    });
    expect(body).not.toHaveProperty("school_id");
  });

  it("sends a grade range (von + bis) for a multi-grade class", async () => {
    routeFetch({
      classResponse: {
        id: 9,
        school_id: 1,
        name: "Mehrklasse",
        kuerzel: null,
        jahrgangsstufe: 1,
        jahrgangsstufe_bis: 3,
        status: "active",
        created_at: "2026-07-13T12:00:00+00:00",
        updated_at: "2026-07-13T12:00:00+00:00",
      },
    });

    renderWithQuery(
      <CreateClassModal open={true} onClose={() => {}} defaultSchoolId={1} isAdmin={false} />,
    );
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/^name$/i), "Mehrklasse");
    await user.type(screen.getByLabelText(/jahrgangsstufe/i), "1");
    await user.type(screen.getByLabelText(/bis \(optional\)/i), "3");
    await user.click(screen.getByRole("button", { name: /anlegen/i }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some((c) => String(c[0]) === "/api/classes")).toBe(true);
    });
    expect(classPostBody().jahrgangsstufe_bis).toBe(3);
  });

  it("requires + sends school_id from the dropdown when isAdmin", async () => {
    routeFetch({
      schools: [
        { id: 42, name: "Schule X", kuerzel: "X", scope_short: "X" },
        { id: 7, name: "Schule Y", kuerzel: "Y", scope_short: "Y" },
      ],
      classResponse: {
        id: 8,
        school_id: 42,
        name: "5b",
        kuerzel: null,
        jahrgangsstufe: 5,
        status: "active",
        created_at: "2026-05-08T12:00:00+00:00",
        updated_at: "2026-05-08T12:00:00+00:00",
      },
    });

    renderWithQuery(
      <CreateClassModal open={true} onClose={() => {}} defaultSchoolId={null} isAdmin={true} />,
    );
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/^name$/i), "5b");
    await user.type(screen.getByLabelText(/jahrgangsstufe/i), "5");
    // The school dropdown is populated from GET /schools.
    await waitFor(() => {
      expect(screen.getByRole("option", { name: /Schule X/ })).toBeTruthy();
    });
    await user.selectOptions(screen.getByLabelText(/schule/i), "42");
    await user.click(screen.getByRole("button", { name: /anlegen/i }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some((c) => String(c[0]) === "/api/classes")).toBe(true);
    });
    expect(classPostBody().school_id).toBe(42);
  });
});
