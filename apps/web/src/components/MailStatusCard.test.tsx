/** Mail-Status und Testmail. */
/* @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { MailStatusCard } from "@/components/MailStatusCard";
import i18n from "@/i18n";

const fetchMock = vi.fn();

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { headers: { "content-type": "application/json" } });
}

beforeAll(async () => {
  await i18n.changeLanguage("de");
});

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    const u = String(url);
    if (u === "/api/admin/mail/status")
      return Promise.resolve(
        json({
          transport: "graph",
          sender: "noreply@vitabrevis.ch",
          sender_name: "Magister",
          ready: true,
          missing: [],
          expiry_notice_enabled: true,
          expiry_notice_days: [14, 7, 1],
          platform_managed: true,
        }),
      );
    if (u === "/api/admin/mail/test") {
      const to = (JSON.parse(String(init?.body)) as { to: string }).to;
      return Promise.resolve(
        json(
          to === "it@schule.ch"
            ? { ok: true, error: null }
            : { ok: false, error: "graph: sendMail 403 ErrorAccessDenied" },
        ),
      );
    }
    return Promise.resolve(json({}));
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("MailStatusCard", () => {
  it("zeigt den Stand und meldet das Ergebnis der Testmail", async () => {
    const user = userEvent.setup();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MailStatusCard />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Microsoft 365 (Graph)")).toBeTruthy();
    expect(screen.getByText("Magister <noreply@vitabrevis.ch>")).toBeTruthy();
    expect(screen.getByText("an — 14, 7, 1 Tage vorher")).toBeTruthy();

    const input = screen.getByLabelText("Testmail an");
    await user.type(input, "it@schule.ch");
    await user.click(screen.getByRole("button", { name: "Testmail senden" }));
    expect((await screen.findByRole("status")).textContent).toBe(
      "Gesendet. Bitte im Postfach prüfen.",
    );
    await user.clear(input);
    await user.type(input, "x@schule.ch");
    await user.click(screen.getByRole("button", { name: "Testmail senden" }));
    expect((await screen.findByRole("status")).textContent).toBe(
      "Nicht gesendet: graph: sendMail 403 ErrorAccessDenied",
    );
  });
});
