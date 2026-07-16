/* @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";
import { TeacherPicker } from "./_app.classes.$classId";

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

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    headers: { "content-type": "application/json" },
  });
}

function renderWithQuery(node: React.ReactNode): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

const TEACHERS = [
  {
    ad_object_guid: "g1",
    upn: "anna.lehrer@schule.ch",
    given_name: "Anna",
    surname: "Lehrer",
    display_name: "Anna Lehrer",
    kind: "teacher",
    enabled: true,
  },
  {
    ad_object_guid: "g2",
    upn: "beat.muster@schule.ch",
    given_name: "Beat",
    surname: "Muster",
    display_name: "Beat Muster",
    kind: "teacher",
    enabled: true,
  },
];

describe("TeacherPicker", () => {
  it("shows the whole teacher pool up front (no typing required)", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: TEACHERS, total: TEACHERS.length }));

    renderWithQuery(<TeacherPicker value={null} onPick={() => {}} inputId="t" />);

    // Both teachers are listed immediately, before any search input.
    await waitFor(() => {
      expect(screen.getByText("Anna Lehrer")).toBeTruthy();
      expect(screen.getByText("Beat Muster")).toBeTruthy();
    });
    // The first request carries no search term → the full pool.
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("kind=teacher");
    expect(url).not.toContain("search=");
  });

  it("selecting a candidate calls onPick with that user", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: TEACHERS, total: TEACHERS.length }));
    const onPick = vi.fn();
    renderWithQuery(<TeacherPicker value={null} onPick={onPick} inputId="t" />);

    await waitFor(() => expect(screen.getByText("Anna Lehrer")).toBeTruthy());
    await userEvent.setup().click(screen.getByText("Anna Lehrer"));
    expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ ad_object_guid: "g1" }));
  });
});
