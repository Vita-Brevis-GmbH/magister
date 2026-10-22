/**
 * Abteilungen: ein Klick öffnet die Detailseite (Kind-Route) statt die Liste
 * stehen zu lassen; die Detailseite zeigt eine Übersicht.
 */
/* @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";

let childActive = false;

vi.mock("@tanstack/react-router", async (orig) => ({
  ...(await orig<typeof import("@tanstack/react-router")>()),
  useChildMatches: () => (childActive ? [{}] : []),
  Outlet: () => <div data-testid="outlet" />,
  Link: ({ children, className }: { children: ReactNode; className?: string }) => (
    <a className={className}>{children}</a>
  ),
}));

const { DepartmentsPage } = await import("./_app.departments");
const detail = await import("./_app.departments.$departmentId");

const DEPT = {
  id: 5,
  school_id: 1,
  name: "Sekretariat",
  kuerzel: "SEK",
  details: "Empfang und Telefon",
  ad_groups: ["CN=GG_Sekretariat,OU=Gruppen,DC=firma,DC=local"],
  status: "active",
  created_at: "2026-08-01T08:00:00Z",
  updated_at: "2026-08-01T08:00:00Z",
  member_count: 1,
};
const PERSON = { display_name: null, given_name: "Eva", surname: "Muster", upn: "eva@firma.ch" };

const fetchMock = vi.fn();

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { headers: { "content-type": "application/json" } });
}

beforeAll(async () => {
  await i18n.changeLanguage("de");
});

beforeEach(() => {
  childActive = false;
  fetchMock.mockReset();
  fetchMock.mockImplementation((url: string) => {
    const u = String(url);
    if (u === "/api/departments") return Promise.resolve(json([DEPT]));
    if (u === "/api/departments/5") return Promise.resolve(json(DEPT));
    if (u === "/api/departments/5/members")
      return Promise.resolve(
        json([
          {
            id: 1,
            department_id: 5,
            ad_object_guid: "g1",
            valid_from: "2026-08-01T00:00:00Z",
            valid_to: null,
            created_at: "2026-08-01T00:00:00Z",
            ...PERSON,
          },
        ]),
      );
    if (u === "/api/departments/5/managers")
      return Promise.resolve(
        json([
          {
            id: 2,
            department_id: 5,
            ad_object_guid: "g1",
            role: "lead",
            valid_from: "2026-08-01T00:00:00Z",
            valid_to: null,
            created_at: "2026-08-01T00:00:00Z",
            ...PERSON,
          },
        ]),
      );
    if (u === "/api/schools") return Promise.resolve(json([{ id: 1, name: "Hauptsitz" }]));
    if (u === "/api/me/preferences")
      return Promise.resolve(
        json({ language: "de", region: "CH", date_format: "DD.MM.YYYY", time_format: "24h" }),
      );
    if (u === "/api/me") return Promise.resolve(json({ is_admin: true, school_scope: [] }));
    return Promise.resolve(json([]));
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function wrap(node: ReactNode): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

describe("Abteilungen", () => {
  it("zeigt in der Liste Standort und einen Details-Knopf", async () => {
    wrap(<DepartmentsPage />);
    const row = (await screen.findAllByText("Sekretariat"))[0].closest("li");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("Details")).toBeTruthy();
    expect(await within(row as HTMLElement).findByText("Hauptsitz")).toBeTruthy();
  });

  it("übergibt an die Detailseite, sobald sie offen ist", () => {
    childActive = true;
    wrap(<DepartmentsPage />);
    expect(screen.getByTestId("outlet")).toBeTruthy();
    expect(screen.queryByText("Sekretariat")).toBeNull();
  });

  it("Detailseite: Übersicht mit Standort, Leitung, Gruppen und Beschreibung", async () => {
    vi.spyOn(detail.Route, "useParams").mockReturnValue({ departmentId: "5" } as never);
    wrap(<detail.DepartmentDetailPage />);
    const overview = (await screen.findByText("Übersicht")).closest("section") as HTMLElement;
    expect(await within(overview).findByText("Hauptsitz")).toBeTruthy();
    expect(await within(overview).findByText("Eva Muster")).toBeTruthy();
    expect(within(overview).getByText("GG_Sekretariat")).toBeTruthy();
    expect(within(overview).getByText("Empfang und Telefon")).toBeTruthy();
    expect(await screen.findByText(/seit 01\.08\.2026/)).toBeTruthy();
  });
});
