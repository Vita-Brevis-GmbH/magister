/* @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";
import type { LoginAccountOut, RoleAssignmentOut, RoleSourceOut } from "@/api/types";
import { DEFAULT_PREFS } from "@/lib/format";
import { CockpitRolesNotice, LoginAccountsCard, RoleRow, RolesPage } from "./_app.admin.roles";

/* Rollen nur aus dem Cockpit (ADR-0027): die Seite ist dann nur lesbar. */

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
  vi.restoreAllMocks();
});

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    ...init,
    headers: { "content-type": "application/json", ...(init.headers ?? {}) },
  });
}

/** Antwort je Pfad (ohne `/api` und Abfrage); `/me/preferences` immer mit Vorgaben. */
function routed(handler: (path: string, init?: RequestInit) => Response): void {
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    const path = String(url)
      .replace(/^\/api/, "")
      .split("?")[0]!;
    if (path === "/me/preferences") return Promise.resolve(jsonResponse(DEFAULT_PREFS));
    return Promise.resolve(handler(path, init));
  });
}

function renderWithQuery(node: React.ReactNode): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

const ACCOUNT: LoginAccountOut = {
  id: 2,
  username: "neue.person",
  display_name: null,
  email: null,
  principal_guid: "8a1f0a52-5c1d-5d7e-9a7f-000000000002",
  bound: true,
  enabled: true,
  ad_linked: false,
  bootstrap_admin: false,
  created_at: "2026-11-13T08:00:00Z",
  last_login_at: "2026-11-13T08:00:00Z",
};

const GRANT: RoleAssignmentOut = {
  ad_object_guid: "8a1f0a52-5c1d-5d7e-9a7f-000000000003",
  role: "smi",
  school_id: 1,
  school_name: "Einheit A",
  granted_by: "admin@example.ch",
  granted_at: "2026-11-13T08:00:00Z",
  from_cockpit: false,
  display_name: null,
  given_name: null,
  surname: null,
  upn: "it@example.ch",
};

const LED: RoleSourceOut = { from_cockpit: true, editable: false, emergency_access: false };

function page(source: RoleSourceOut): void {
  routed((path) => {
    if (path === "/admin/roles/source") return jsonResponse(source);
    if (path === "/admin/roles") return jsonResponse([GRANT]);
    if (path === "/admin/login-accounts") return jsonResponse([ACCOUNT]);
    if (path === "/me/modules") {
      return jsonResponse({ profile: "school", modules: [], platform_managed: true });
    }
    if (path === "/schools") return jsonResponse([]);
    return jsonResponse({ roles: [], capabilities: [] });
  });
  renderWithQuery(<RolesPage />);
}

describe("RolesPage (ADR-0027)", () => {
  it("is read-only while the cockpit leads the roles", async () => {
    page(LED);
    expect(await screen.findByText("Rollen aus dem Cockpit")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/vergibt der Betreiber im Cockpit/);
    // Die vergebenen Rollen bleiben sichtbar, ohne „Entziehen".
    expect(await screen.findAllByText("it@example.ch")).not.toHaveLength(0);
    expect(screen.queryByRole("button", { name: "Entziehen" })).not.toBeInTheDocument();
    // Kein Rolleneditor, kein Konto vorab anlegen, keine Bindung lösen, kein Löschen.
    expect(screen.queryByText("Rollen vergeben")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /vorab anlegen/i })).not.toBeInTheDocument();
    expect(await screen.findByText("neue.person")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Bindung lösen" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Löschen" })).not.toBeInTheDocument();
    // Sperren bleibt.
    expect(screen.getByRole("button", { name: "Sperren" })).toBeInTheDocument();
  });

  it("stays editable with the emergency access and says so", async () => {
    page({ from_cockpit: true, editable: true, emergency_access: true });
    expect(await screen.findByText(/Notzugang/)).toBeInTheDocument();
    expect(await screen.findByText("Rollen vergeben")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Entziehen" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /vorab anlegen/i })).toBeInTheDocument();
  });

  it("is unchanged without a cockpit", async () => {
    page({ from_cockpit: false, editable: true, emergency_access: false });
    expect(await screen.findByText("Rollen vergeben")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Entziehen" })).toBeInTheDocument();
    expect(screen.queryByText("Rollen aus dem Cockpit")).not.toBeInTheDocument();
  });
});

describe("Teile nur lesbar (ADR-0027)", () => {
  it("RoleRow without a revoke button", () => {
    routed(() => new Response(null, { status: 204 }));
    renderWithQuery(
      <table>
        <tbody>
          <RoleRow a={GRANT} locked />
        </tbody>
      </table>,
    );
    expect(screen.getByText("admin@example.ch")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Entziehen" })).not.toBeInTheDocument();
  });

  it("LoginAccountsCard keeps lock and unlock only", async () => {
    routed(() =>
      jsonResponse([ACCOUNT, { ...ACCOUNT, id: 3, username: "zweite", enabled: false }]),
    );
    renderWithQuery(<LoginAccountsCard locked />);
    expect(await screen.findByText("neue.person")).toBeInTheDocument();
    expect(screen.getByText(/Anmeldekonten legt das Cockpit an/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/benutzername in keycloak/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sperren" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Freigeben" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Bindung lösen" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Löschen" })).not.toBeInTheDocument();
  });

  it("names the cockpit when the API refuses (409)", async () => {
    routed((_path, init) =>
      init?.method === "POST"
        ? jsonResponse({ detail: "roles_managed_by_cockpit" }, { status: 409 })
        : jsonResponse([]),
    );
    renderWithQuery(<LoginAccountsCard />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/benutzername in keycloak/i), "neu");
    await user.click(screen.getByRole("button", { name: /vorab anlegen/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /verwaltet der Betreiber im Cockpit/,
    );
  });

  it("a refused revoke says who assigns the roles", async () => {
    routed(() => jsonResponse({ detail: "roles_managed_by_cockpit" }, { status: 409 }));
    renderWithQuery(
      <table>
        <tbody>
          <RoleRow a={GRANT} />
        </tbody>
      </table>,
    );
    await userEvent.setup().click(screen.getByRole("button", { name: "Entziehen" }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Rollen dieses Kunden vergibt der Betreiber im Cockpit.",
      ),
    );
  });

  it("CockpitRolesNotice names the emergency access", () => {
    render(<CockpitRolesNotice emergency />);
    expect(screen.getByRole("status")).toHaveTextContent(/fremde Rolle/);
  });
});
