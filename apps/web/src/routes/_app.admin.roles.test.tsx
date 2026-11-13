/* @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";
import type { LoginAccountOut } from "@/api/types";
import { DEFAULT_PREFS } from "@/lib/format";
import { NoPermissions } from "./_app.index";
import { LoginAccountsCard } from "./_app.admin.roles";

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

/** `/me/preferences` (Formate) beantworten, alles andere über `handler`. */
function routed(handler: (url: string, init?: RequestInit) => Response): void {
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    if (String(url).endsWith("/me/preferences")) {
      return Promise.resolve(jsonResponse(DEFAULT_PREFS));
    }
    return Promise.resolve(handler(String(url), init));
  });
}

function renderWithQuery(node: React.ReactNode): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

const ADMIN: LoginAccountOut = {
  id: 1,
  username: "automato-admin",
  display_name: "Automato Admin",
  email: null,
  principal_guid: "8a1f0a52-5c1d-5d7e-9a7f-000000000001",
  bound: true,
  enabled: true,
  ad_linked: false,
  bootstrap_admin: true,
  created_at: "2026-11-13T08:00:00Z",
  last_login_at: "2026-11-13T08:00:00Z",
};

const NEW: LoginAccountOut = {
  ...ADMIN,
  id: 2,
  username: "neue.person",
  display_name: null,
  principal_guid: "8a1f0a52-5c1d-5d7e-9a7f-000000000002",
  bound: false,
  bootstrap_admin: false,
  last_login_at: null,
};

describe("LoginAccountsCard (ADR-0025)", () => {
  it("lists accounts and protects the first admin from the console", async () => {
    routed(() => jsonResponse([ADMIN, NEW]));
    renderWithQuery(<LoginAccountsCard />);
    expect(await screen.findByText("automato-admin")).toBeInTheDocument();
    expect(screen.getByText("Erster Admin")).toBeInTheDocument();
    expect(screen.getByText("noch nie angemeldet")).toBeInTheDocument();
    // Sperren/Löschen nur für das zweite Konto, Bindung lösen nur für das erste.
    expect(screen.getAllByRole("button", { name: "Sperren" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Löschen" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Bindung lösen" })).toHaveLength(1);
  });

  it("creates an account in advance", async () => {
    routed((_url, init) =>
      init?.method === "POST" ? jsonResponse(NEW, { status: 201 }) : jsonResponse([]),
    );
    renderWithQuery(<LoginAccountsCard />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/benutzername in keycloak/i), "neue.person");
    await user.click(screen.getByRole("button", { name: /vorab anlegen/i }));
    await waitFor(() => {
      const post = fetchMock.mock.calls.find((c) => (c[1] as RequestInit)?.method === "POST");
      expect(post).toBeDefined();
      expect(String(post![0])).toBe("/api/admin/login-accounts");
      expect(JSON.parse((post![1] as RequestInit).body as string)).toEqual({
        username: "neue.person",
      });
    });
  });

  it("names a taken user name", async () => {
    routed((_url, init) =>
      init?.method === "POST"
        ? jsonResponse({ detail: "login_account_exists" }, { status: 409 })
        : jsonResponse([]),
    );
    renderWithQuery(<LoginAccountsCard />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/benutzername in keycloak/i), "doppelt");
    await user.click(screen.getByRole("button", { name: /vorab anlegen/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/gibt es schon/i);
  });
});

describe("NoPermissions (ADR-0025)", () => {
  it("says that the account has no permissions yet and who grants them", () => {
    render(<NoPermissions name="neue.person" />);
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent(/noch keine rechte/i);
    expect(status).toHaveTextContent(/neue\.person/);
    expect(status).toHaveTextContent(/IT-Anbieter/);
  });
});
