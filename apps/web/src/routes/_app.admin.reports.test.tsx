/**
 * Reports: Konten nach Kontoart und Zielgruppe in jedem Profil; Abteilungen
 * auch an einer Schule, sobald das Modul eingeschaltet ist.
 */
/* @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";

const { ReportsPage } = await import("./_app.admin.reports");

const fetchMock = vi.fn();
let modules: string[] = [];

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { headers: { "content-type": "application/json" } });
}

beforeAll(async () => {
  await i18n.changeLanguage("de");
});

beforeEach(() => {
  modules = [];
  fetchMock.mockReset();
  fetchMock.mockImplementation((url: string) => {
    const u = String(url);
    if (u === "/api/me/modules")
      return Promise.resolve(json({ profile: "school", modules: modules.map((id) => ({ id })) }));
    if (u === "/api/reports/accounts-by-kind")
      return Promise.resolve(
        json({
          total: 3,
          rows: [
            {
              kind: "student",
              total: 3,
              enabled: 2,
              disabled: 1,
              stored_password: 1,
              without_zielgruppe: 1,
              missing_in_ad: 0,
            },
          ],
        }),
      );
    if (u === "/api/reports/accounts-by-zielgruppe")
      return Promise.resolve(
        json({
          total: 3,
          rows: [
            {
              group_template_id: 7,
              name: "Schüler:in Zyklus 1",
              kind: "student_zyklus1",
              total: 2,
              enabled: 2,
              disabled: 0,
              stored_password: 1,
            },
            {
              group_template_id: null,
              name: null,
              kind: null,
              total: 1,
              enabled: 0,
              disabled: 1,
              stored_password: 0,
            },
          ],
        }),
      );
    if (u === "/api/reports/members-by-department")
      return Promise.resolve(
        json({
          total_members: 4,
          total_departments: 1,
          rows: [
            {
              department_id: 1,
              school_id: 1,
              name: "Hauswartung",
              kuerzel: null,
              member_count: 4,
              lead_count: 1,
            },
          ],
        }),
      );
    if (u.startsWith("/api/reports/students-by-class"))
      return Promise.resolve(json({ rows: [], total_students: 0, total_classes: 0 }));
    if (u.startsWith("/api/reports/students-by-school-year"))
      return Promise.resolve(json({ rows: [], total_students: 0 }));
    if (u.startsWith("/api/reports/activity"))
      return Promise.resolve(json({ since: "2026-10-01T00:00:00Z", rows: [] }));
    return Promise.resolve(json({ rows: [] }));
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderPage(): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ReportsPage />
    </QueryClientProvider>,
  );
}

describe("Reports", () => {
  it("zeigt Konten nach Kontoart und nach Zielgruppe", async () => {
    renderPage();
    const kind = (await screen.findByText("Konten nach Kontoart")).closest(
      "section",
    ) as HTMLElement;
    const row = (await within(kind).findByText("Schüler:in")).closest("tr") as HTMLElement;
    expect([...row.querySelectorAll("td")].map((c) => c.textContent)).toEqual([
      "Schüler:in",
      "3",
      "2",
      "1",
      "1",
      "1",
      "0",
    ]);
    const tpl = (await screen.findByText("Konten nach Zielgruppe")).closest(
      "section",
    ) as HTMLElement;
    expect(await within(tpl).findByText("Schüler:in Zyklus 1")).toBeTruthy();
    expect(within(tpl).getByText("Ohne Zielgruppe")).toBeTruthy();
  });

  it("zeigt Abteilungen an einer Schule nur mit eingeschaltetem Modul", async () => {
    renderPage();
    await screen.findByText("Konten nach Kontoart");
    expect(screen.queryByText("Mitarbeitende pro Abteilung")).toBeNull();
  });

  it("zeigt Abteilungen, wenn das Modul an ist", async () => {
    modules = ["departments"];
    renderPage();
    expect(await screen.findByText("Mitarbeitende pro Abteilung")).toBeTruthy();
    expect(await screen.findByText("Hauswartung")).toBeTruthy();
  });
});
