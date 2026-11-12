/**
 * Passwort-Import: Standard ist die CSV, ausnahmsweise eine PDF-Klassenliste.
 * Die anderen Importe nehmen nur CSV an.
 */
/* @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";

vi.mock("@tanstack/react-router", async (orig) => ({
  ...(await orig<typeof import("@tanstack/react-router")>()),
  useChildMatches: () => [],
  Link: ({ children }: { children: ReactNode }) => <a>{children}</a>,
}));

const { ImportsPage } = await import("./_app.admin.imports");

const fetchMock = vi.fn();

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

beforeAll(async () => {
  await i18n.changeLanguage("de");
});

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    const u = String(url);
    if (u.startsWith("/api/imports?") && init?.method === "POST")
      return Promise.resolve(json({ detail: "pdf_no_password_table" }, 400));
    if (u.startsWith("/api/imports")) return Promise.resolve(json([]));
    if (u === "/api/me")
      return Promise.resolve(json({ upn: "sl@schule.ch", is_admin: false, school_scope: [1] }));
    if (u === "/api/me/preferences")
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
      <ImportsPage />
    </QueryClientProvider>,
  );
}

describe("Import — PDF nur für Passwörter", () => {
  it("nimmt beim Passwort-Import auch ein PDF an, sonst nur CSV", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Neuer Import" }));
    const csvOnly = screen.getByLabelText<HTMLInputElement>("CSV-Datei");
    expect(csvOnly.accept).toBe(".csv,text/csv");

    await user.click(screen.getByRole("tab", { name: "Passwörter bestehender Konten" }));
    const input = screen.getByLabelText<HTMLInputElement>(/ausnahmsweise eine PDF-Klassenliste/);
    expect(input.accept).toContain(".pdf");
    expect(screen.getByText(/Standard ist die CSV/)).toBeTruthy();

    const pdf = new File(["%PDF-1.7"], "klasse4.pdf", { type: "application/pdf" });
    await user.upload(input, pdf);
    await user.click(screen.getByRole("button", { name: "Hochladen & prüfen" }));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "Im PDF wurde keine Tabelle mit den Spalten Benutzername und Passwort gefunden.",
    );
  });
});
