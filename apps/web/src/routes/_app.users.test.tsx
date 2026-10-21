/**
 * Benutzerliste: Jahrgang und Zielgruppe als Spalten; Sortieren und Filtern
 * gehen an den Server (die Liste ist seitenweise).
 */
/* @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";

vi.mock("@tanstack/react-router", async (orig) => ({
  ...(await orig<typeof import("@tanstack/react-router")>()),
  useChildMatches: () => [],
  Link: ({ children }: { children: ReactNode }) => <a>{children}</a>,
}));

const { UsersPage } = await import("./_app.users");

const fetchMock = vi.fn();

const USER = {
  ad_object_guid: "g1",
  upn: "lia@schule.ch",
  given_name: "Lia",
  surname: "Klein",
  display_name: "Lia Klein",
  kind: "student",
  enabled: true,
  school_id: 1,
  jahrgangsstufe: 3,
  group_template_id: 7,
  group_template_name: "Schüler:in Zyklus 1",
  cannot_change_password: true,
  password_never_expires: true,
  store_password: true,
  ad_groups: [],
  mail_aliases: [],
  ad_missing_since: null,
};

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { headers: { "content-type": "application/json" } });
}

function userCalls(): URL[] {
  return fetchMock.mock.calls
    .map((c) => String(c[0]))
    .filter((u) => u.startsWith("/api/users?") || u === "/api/users")
    .map((u) => new URL(u, "http://x"));
}

beforeAll(async () => {
  await i18n.changeLanguage("de");
});

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockImplementation((url: string) => {
    const u = String(url);
    if (u.startsWith("/api/users"))
      return Promise.resolve(
        json({
          items: [USER],
          zielgruppen: [{ id: 7, name: "Schüler:in Zyklus 1" }],
          total: 1,
          offset: 0,
          limit: 50,
          last_sync_at: null,
        }),
      );
    if (u.endsWith("/api/me/preferences"))
      return Promise.resolve(
        json({ language: "de", region: "CH", date_format: "DD.MM.YYYY", time_format: "24h" }),
      );
    if (u.endsWith("/api/me/modules"))
      return Promise.resolve(json({ profile: "school", modules: [] }));
    if (u.endsWith("/api/auth/me"))
      return Promise.resolve(
        json({ upn: "admin@schule.ch", is_admin: true, roles: [], ad_object_guid: "a" }),
      );
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
      <UsersPage />
    </QueryClientProvider>,
  );
}

describe("Benutzerliste", () => {
  it("zeigt Jahrgang und Zielgruppe und sortiert über den Server", async () => {
    renderPage();
    expect(await screen.findByRole("cell", { name: "3" })).toBeInTheDocument();
    expect(screen.getAllByText("Schüler:in Zyklus 1").length).toBeGreaterThan(0);
    expect(screen.getByText("gespeichert")).toBeInTheDocument();
    expect(userCalls().at(-1)?.searchParams.get("sort")).toBe("name");

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Jahrgang/ }));
    await waitFor(() => {
      const last = userCalls().at(-1)!;
      expect(last.searchParams.get("sort")).toBe("jahrgangsstufe");
      expect(last.searchParams.get("dir")).toBe("asc");
    });
    await user.click(screen.getByRole("button", { name: /Jahrgang/ }));
    await waitFor(() => expect(userCalls().at(-1)!.searchParams.get("dir")).toBe("desc"));
  });

  it("schickt die Filter an den Server", async () => {
    renderPage();
    await screen.findByRole("cell", { name: "3" });
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Jahrgang filtern"), "3");
    await user.selectOptions(screen.getByLabelText("Zielgruppe filtern"), "0");
    await user.selectOptions(screen.getByLabelText("Richtlinie filtern"), "stored");
    await user.selectOptions(screen.getByLabelText("Status filtern"), "disabled");
    await waitFor(() => {
      const p = userCalls().at(-1)!.searchParams;
      expect(p.get("jahrgangsstufe")).toBe("3");
      expect(p.get("group_template_id")).toBe("0");
      expect(p.get("policy")).toBe("stored");
      expect(p.get("enabled")).toBe("false");
    });
  });
});
