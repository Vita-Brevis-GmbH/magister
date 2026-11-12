/**
 * Passwort-Ablauf: bald fällig mit Erinnerungsstand, und Konten ohne Mailadresse.
 */
/* @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";

vi.mock("@tanstack/react-router", async (orig) => ({
  ...(await orig<typeof import("@tanstack/react-router")>()),
  Link: ({ children }: { children: ReactNode }) => <a>{children}</a>,
}));

const { PasswordExpiryPage } = await import("./_app.password-expiry");

const fetchMock = vi.fn();

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { headers: { "content-type": "application/json" } });
}

const ROW = {
  ad_object_guid: "g1",
  display_name: "Lea Muster",
  given_name: "Lea",
  surname: "Muster",
  upn: "lea@schule.ch",
  kind: "student",
  school_id: 1,
  jahrgangsstufe: 7,
  group_template_name: "Zyklus 3",
  mail: "lea@schule.ch",
  password_expires_at: "2026-10-27T06:00:00Z",
  days_left: 5,
  password_last_set: "2026-07-29T06:00:00Z",
  age_days: 85,
  password_never_expires: false,
  password_known: true,
  notice_status: "sent",
  notice_at: "2026-10-22T06:00:00Z",
  notice_threshold_days: 7,
};

beforeAll(async () => {
  await i18n.changeLanguage("de");
});

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockImplementation((url: string) => {
    const u = new URL(String(url), "http://x");
    if (u.pathname === "/api/password-expiry") {
      const view = u.searchParams.get("view");
      return Promise.resolve(
        json({
          view,
          within_days: Number(u.searchParams.get("days")),
          rows:
            view === "age"
              ? u.searchParams.get("dir") === "asc"
                ? [{ ...ROW, display_name: "Neu", age_days: 3 }]
                : [
                    {
                      ...ROW,
                      display_name: "Uralt",
                      age_days: 400,
                      password_last_set: "2025-09-17T08:00:00Z",
                      password_never_expires: true,
                    },
                    {
                      ...ROW,
                      ad_object_guid: "g4",
                      display_name: "Muss ändern",
                      age_days: null,
                      password_last_set: null,
                    },
                  ]
              : view === "no_mail"
                ? [{ ...ROW, ad_object_guid: "g2", display_name: "Tim Ohne", mail: null }]
                : [ROW, { ...ROW, ad_object_guid: "g3", display_name: "Alt", days_left: -2 }],
          total: view === "age" ? 250 : 2,
          offset: Number(u.searchParams.get("offset") ?? 0),
          limit: 100,
          notice_enabled: true,
          mail_ready: false,
          info_as_of: "2026-10-22T05:00:00Z",
        }),
      );
    }
    if (u.pathname === "/api/me/preferences")
      return Promise.resolve(
        json({ language: "de", region: "CH", date_format: "DD.MM.YYYY", time_format: "24h" }),
      );
    return Promise.resolve(json({}));
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
      <PasswordExpiryPage />
    </QueryClientProvider>,
  );
}

describe("Passwort-Ablauf", () => {
  it("zeigt Ablauf, Erinnerungsstand und warnt, wenn der Versand nicht bereit ist", async () => {
    renderPage();
    const row = (await screen.findByText("Lea Muster")).closest("tr") as HTMLElement;
    expect(within(row).getByText("in 5 Tagen")).toBeTruthy();
    expect(within(row).getByText(/gesendet am 22\.10\.2026 \(7 Tage vorher\)/)).toBeTruthy();
    expect(within(row).getByText(/Zyklus 3/)).toBeTruthy();
    const old = (await screen.findByText("Alt")).closest("tr") as HTMLElement;
    expect(within(old).getByText("abgelaufen")).toBeTruthy();
    expect(screen.getByText(/nicht vollständig eingerichtet/)).toBeTruthy();
  });

  it("listet Konten ohne Mailadresse", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Lea Muster");
    await user.click(screen.getByRole("tab", { name: "Ohne Mailadresse" }));
    const row = (await screen.findByText("Tim Ohne")).closest("tr") as HTMLElement;
    expect(within(row).getByText("keine Mail")).toBeTruthy();
    const last = new URL(String(fetchMock.mock.calls.at(-1)?.[0]), "http://x");
    expect(last.searchParams.get("view")).toBe("no_mail");
  });

  it("fragt einen anderen Zeitraum ab", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Lea Muster");
    await user.selectOptions(screen.getByLabelText("Zeitraum"), "30");
    await screen.findByText("Lea Muster");
    const calls = fetchMock.mock.calls
      .map((c) => new URL(String(c[0]), "http://x"))
      .filter((u) => u.pathname === "/api/password-expiry");
    expect(calls.at(-1)?.searchParams.get("days")).toBe("30");
  });

  it("zeigt das Passwortalter aller Konten, älteste zuerst, umkehrbar und seitenweise", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Lea Muster");
    await user.click(screen.getByRole("tab", { name: "Passwortalter" }));
    const old = (await screen.findByText("Uralt")).closest("tr") as HTMLElement;
    expect(within(old).getByText("400 Tage")).toBeTruthy();
    expect(within(old).getByText("17.09.2025")).toBeTruthy();
    expect(within(old).getByText("läuft nie ab")).toBeTruthy();
    const must = screen.getByText("Muss ändern").closest("tr") as HTMLElement;
    expect(within(must).getByText("Änderung verlangt")).toBeTruthy();
    expect(screen.getByText("250 Konten")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: /Alter/ }));
    expect(await screen.findByText("Neu")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Weiter" }));
    const calls = fetchMock.mock.calls
      .map((c) => new URL(String(c[0]), "http://x"))
      .filter((u) => u.searchParams.get("view") === "age");
    const last = calls.at(-1);
    expect(last?.searchParams.get("dir")).toBe("asc");
    expect(last?.searchParams.get("offset")).toBe("100");
  });
});
