/* @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";
import type { AppSettingsOut } from "@/api/types";
import { SettingsForm } from "./_app.admin.settings";

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

function makeData(overrides: Partial<AppSettingsOut> = {}): AppSettingsOut {
  return {
    version: 5,
    oidc_issuer: "https://login.example.test/v2.0",
    oidc_client_id: "client-x",
    oidc_client_secret_set: true,
    oidc_redirect_uri: "https://magister.example.ch/api/auth/callback",
    oidc_scopes: ["openid", "profile", "email"],
    bootstrap_admins: ["admin@example.ch"],
    mail_domains: [],
    ad_dcs: ["dc1.example.local"],
    ad_bind_mode: "simple",
    ad_bind_dn: "cn=svc,dc=example,dc=local",
    ad_bind_password_set: false,
    ad_users_search_base: "OU=Users,DC=example,DC=local",
    ad_computers_search_base: null,
    ad_sync_interval_minutes: 15,
    ad_ou_students_zyklus3: null,
    ad_ou_students_other: null,
    ad_ou_teachers: null,
    zyklus1_max_grade: 2,
    zyklus2_max_grade: 6,
    updated_at: "2026-05-08T12:00:00+00:00",
    updated_by_upn: "ops@example.ch",
    ...overrides,
  };
}

function renderForm(data: AppSettingsOut): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <SettingsForm data={data} />
    </QueryClientProvider>,
  );
}

describe("SettingsForm", () => {
  it("prefills the form from props and shows the secret-set placeholder", () => {
    renderForm(makeData());
    expect(screen.getByLabelText(/issuer-url/i)).toHaveValue("https://login.example.test/v2.0");
    expect(screen.getByLabelText(/client-id/i)).toHaveValue("client-x");
    // Client secret has placeholder "(gesetzt)" because the row already
    // carries one server-side; field itself stays empty so unchanged
    // submits don't overwrite.
    const secret = screen.getByLabelText(/^client-secret$/i);
    expect(secret).toHaveValue("");
    expect(secret).toHaveAttribute("placeholder", expect.stringMatching(/gesetzt/i));
    // Bind password isn't set yet → the "(nicht gesetzt)" placeholder.
    const bindPw = screen.getByLabelText(/^bind-passwort$/i);
    expect(bindPw).toHaveAttribute("placeholder", expect.stringMatching(/nicht gesetzt/i));
  });

  it("only sends the secret when it was actually typed", async () => {
    fetchMock.mockResolvedValue(jsonResponse(makeData({ version: 6 })));
    renderForm(makeData());
    const user = userEvent.setup();

    // Change a non-secret field; do NOT touch the secret inputs.
    const issuer = screen.getByLabelText(/issuer-url/i);
    await user.clear(issuer);
    await user.type(issuer, "https://new.test/v2.0");

    await user.click(screen.getByRole("button", { name: /speichern/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledOnce();
    });
    expect(fetchMock.mock.calls[0]![0]).toBe("/api/admin/app-settings");
    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    expect(init.method).toBe("PUT");
    const payload = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(payload.oidc_issuer).toBe("https://new.test/v2.0");
    expect(payload).not.toHaveProperty("oidc_client_secret");
    expect(payload).not.toHaveProperty("ad_bind_password");
  });

  it("sends the new secret when the operator types one", async () => {
    fetchMock.mockResolvedValue(jsonResponse(makeData({ version: 7 })));
    renderForm(makeData());
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/^client-secret$/i), "fresh-secret-value");
    await user.click(screen.getByRole("button", { name: /speichern/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledOnce();
    });
    const payload = JSON.parse(
      (fetchMock.mock.calls[0]![1] as RequestInit).body as string,
    ) as Record<string, unknown>;
    expect(payload.oidc_client_secret).toBe("fresh-secret-value");
  });

  it("renders a success banner after a successful save", async () => {
    fetchMock.mockResolvedValue(jsonResponse(makeData({ version: 8 })));
    renderForm(makeData());
    const user = userEvent.setup();
    const issuer = screen.getByLabelText(/issuer-url/i);
    await user.clear(issuer);
    await user.type(issuer, "https://new.test/v2.0");
    await user.click(screen.getByRole("button", { name: /speichern/i }));
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(/gespeichert/i);
    });
  });
});
