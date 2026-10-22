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
            view === "no_mail"
              ? [{ ...ROW, ad_object_guid: "g2", display_name: "Tim Ohne", mail: null }]
              : [ROW, { ...ROW, ad_object_guid: "g3", display_name: "Alt", days_left: -2 }],
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
});
