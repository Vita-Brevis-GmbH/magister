/** Systemeinstellungen → Domänen: Mail- und UPN-Domains pflegen. */
/* @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { DomainsCard } from "@/components/DomainsCard";
import i18n from "@/i18n";

const fetchMock = vi.fn();
let saved: unknown = null;

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
  saved = null;
  fetchMock.mockReset();
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    if (String(url) === "/api/admin/domains" && init?.method === "PUT") {
      saved = JSON.parse(String(init.body));
      return Promise.resolve(
        json({
          ...(saved as object),
          upn_choices: ["schule.ch", "sus-schule.ch", "schule.local"],
        }),
      );
    }
    if (String(url) === "/api/admin/domains")
      return Promise.resolve(
        json({
          mail_domains: ["schule.ch"],
          upn_domains: [],
          upn_choices: ["schule.ch", "schule.local"],
          mail_suggestions: ["lp.schule.ch"],
        }),
      );
    return Promise.resolve(json({}));
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DomainsCard", () => {
  it("schlägt vor, was das AD kennt, und speichert beide Listen", async () => {
    const user = userEvent.setup();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <DomainsCard />
      </QueryClientProvider>,
    );
    // Was das AD kennt, steht als Vorschlag da — ein Klick übernimmt es.
    await user.click(await screen.findByRole("button", { name: "schule.local übernehmen" }));
    await user.click(screen.getByRole("button", { name: "lp.schule.ch übernehmen" }));
    expect(screen.queryByRole("button", { name: "schule.local übernehmen" })).toBeNull();
    const upn = screen.getByLabelText("Zusätzliche UPN-Domänen");
    await user.type(upn, "{enter}SUS-Schule.ch");
    await user.click(screen.getByRole("button", { name: "Domänen speichern" }));
    expect((await screen.findByRole("status")).textContent).toBe("Gespeichert.");
    expect(saved).toEqual({
      mail_domains: ["schule.ch", "lp.schule.ch"],
      upn_domains: ["schule.local", "sus-schule.ch"],
    });
  });
});
