/**
 * Benutzer anlegen: die Ziel-OU steht unter dem Standort. Ohne Standort ist
 * sie Pflicht, mit Standort optional, bei fester Kontoart der Zielgruppe weg.
 */
/* @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";

vi.mock("@tanstack/react-router", async (orig) => ({
  ...(await orig<typeof import("@tanstack/react-router")>()),
  useNavigate: () => vi.fn(),
}));

const { NewUserPage } = await import("./_app.admin.user-new");

const fetchMock = vi.fn();
let mailDomains: unknown = { domains: [], upn_domains: [] };

const SCHOOLS = [
  { id: 1, name: "Schule A", kuerzel: "A", scope_short: "A" },
  { id: 2, name: "Schule B", kuerzel: "B", scope_short: "B" },
];
const TEMPLATES = [
  {
    id: 7,
    name: "Lehrperson",
    description: null,
    kind: "teacher",
    ad_groups: [],
    school_ids: [1],
    status: "active",
    password_profile: "teacher",
    force_change: true,
    cannot_change_password: false,
    password_never_expires: false,
    store_password: false,
    ad_ou: null,
    created_at: "2026-10-20T00:00:00Z",
    updated_at: "2026-10-20T00:00:00Z",
  },
];

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { headers: { "content-type": "application/json" } });
}

beforeAll(async () => {
  await i18n.changeLanguage("de");
});

beforeEach(() => {
  fetchMock.mockReset();
  mailDomains = { domains: [], upn_domains: [] };
  fetchMock.mockImplementation((url: string) => {
    const u = String(url);
    if (u.endsWith("/api/schools")) return Promise.resolve(json(SCHOOLS));
    if (u.includes("/api/admin/group-templates")) return Promise.resolve(json(TEMPLATES));
    if (u.endsWith("/api/users/mail-domains")) return Promise.resolve(json(mailDomains));
    if (u.endsWith("/api/me/modules"))
      return Promise.resolve(json({ profile: "school", modules: [] }));
    return Promise.resolve(json([]));
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
      <NewUserPage />
    </QueryClientProvider>,
  );
}

describe("Benutzer anlegen — Ziel-OU", () => {
  it("steht unter dem Standort und ist ohne Standort Pflicht", async () => {
    renderPage();
    await screen.findByRole("option", { name: "Schule A" });
    const ou = screen.getByLabelText("Ziel-OU");
    expect(ou).toBeRequired();
    // Reihenfolge: Standort, Ziel-OU, Zielgruppe, Kontoart.
    const unit = screen.getByLabelText(/Ziel-Schule/);
    const zielgruppe = screen.getByLabelText("Zielgruppe");
    const kontoart = screen.getByLabelText("Kontoart");
    const follows = (a: Element, b: Element): boolean =>
      Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
    expect(follows(unit, ou)).toBe(true);
    expect(follows(ou, zielgruppe)).toBe(true);
    expect(follows(zielgruppe, kontoart)).toBe(true);
    expect(screen.getByRole("button", { name: /anlegen/i })).toBeDisabled();

    const user = userEvent.setup();
    await user.type(ou, "Sonstige");
    expect(screen.getByText(/vollständigen Pfad/)).toBeInTheDocument();
    await user.clear(ou);
    await user.type(ou, "OU=Sonstige,DC=schule,DC=local");
    expect(screen.queryByText(/vollständigen Pfad/)).not.toBeInTheDocument();
  });

  it("ist mit Standort optional und bei fester Kontoart der Zielgruppe weg", async () => {
    renderPage();
    await screen.findByRole("option", { name: "Schule A" });
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText(/Ziel-Schule/), "1");
    const ou = await screen.findByLabelText("Ziel-OU (optional)");
    expect(ou).not.toBeRequired();
    // Liegt nicht im Standort → Hinweis.
    await user.type(ou, "OU=Sonstige,DC=schule,DC=local");
    expect(screen.getByText(/liegt nicht im/i)).toBeInTheDocument();

    const zielgruppe = screen.getByLabelText("Zielgruppe");
    await waitFor(() => expect(within(zielgruppe).getByText("Lehrperson")).toBeInTheDocument());
    await user.selectOptions(zielgruppe, "7");
    await waitFor(() => expect(screen.queryByLabelText(/^Ziel-OU/)).not.toBeInTheDocument());
  });
});

describe("Benutzer anlegen — Domains", () => {
  it("bietet für die Mailadresse die Mail-Domains, für den UPN auch die aus dem AD", async () => {
    mailDomains = { domains: ["schule.ch"], upn_domains: ["schule.ch", "schule.local"] };
    renderPage();
    const mailDomain = await screen.findByRole("combobox", { name: "Mail-Domain" });
    expect(
      within(mailDomain)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["schule.ch"]);
    const upnDomain = screen.getByRole("combobox", { name: "UPN-Domain" });
    expect(
      within(upnDomain)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["schule.ch", "schule.local"]);
    // Leer = kein Postfach; kein Pflichtfeld.
    expect(screen.getByLabelText("E-Mail (optional)")).not.toBeRequired();
  });
});
