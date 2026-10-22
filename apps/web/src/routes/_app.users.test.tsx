/**
 * Benutzerliste: Jahrgang und Zielgruppe als Spalten; Sortieren und Filtern
 * gehen an den Server (die Liste ist seitenweise).
 */
/* @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
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
// Ob das Konto in der Liste erscheint — eine Aktion kann es aus der Ansicht
// nehmen (es passt danach nicht mehr zum Filter).
let showUser = true;

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
  showUser = true;
  fetchMock.mockReset();
  fetchMock.mockImplementation((url: string) => {
    const u = String(url);
    if (u.startsWith("/api/users/") && u !== "/api/users/mail-domains")
      return Promise.resolve(json(USER));
    if (u.startsWith("/api/users"))
      return Promise.resolve(
        json({
          items:
            !showUser || new URL(u, "http://x").searchParams.get("jahrgangsstufe") === "1"
              ? []
              : [USER],
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
    if (u.includes("/api/admin/group-templates/7/assign")) {
      showUser = false; // passt nach dem Zuordnen nicht mehr zum Filter
      return Promise.resolve(
        json([
          {
            ad_object_guid: "g1",
            ok: true,
            error: null,
            added: [],
            removed: [],
            failed: [],
            ou_unchanged: false,
          },
        ]),
      );
    }
    if (u.includes("/api/admin/group-templates"))
      return Promise.resolve(
        json([
          {
            id: 7,
            name: "Schüler:in Zyklus 1",
            description: null,
            kind: "student_zyklus1",
            ad_groups: [],
            school_ids: [1],
            status: "active",
            password_profile: "readable",
            force_change: false,
            cannot_change_password: true,
            password_never_expires: true,
            store_password: true,
            ad_ou: null,
            created_at: "2026-10-21T00:00:00Z",
            updated_at: "2026-10-21T00:00:00Z",
          },
        ]),
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

describe("Benutzerliste — Mehrfachauswahl", () => {
  it("vergisst Zeilen, die ein Filter ausblendet", async () => {
    renderPage();
    await screen.findByRole("cell", { name: "3" });
    const user = userEvent.setup();
    await user.click(screen.getByRole("checkbox", { name: "Auswählen" }));
    expect(screen.getByText("1 ausgewählt")).toBeInTheDocument();
    // Filter blendet die Zeile aus → keine Auswahl mehr, keine Sammelaktion.
    await user.selectOptions(screen.getByLabelText("Jahrgang filtern"), "1");
    await waitFor(() => expect(screen.queryByText("1 ausgewählt")).not.toBeInTheDocument());
    // Zurück: die Zeile ist wieder da, aber nicht mehr ausgewählt.
    await user.selectOptions(screen.getByLabelText("Jahrgang filtern"), "");
    await screen.findByRole("cell", { name: "3" });
    expect(screen.getByRole("checkbox", { name: "Auswählen" })).not.toBeChecked();
  });

  it("ist nach einer Sammelaktion leer", async () => {
    renderPage();
    await screen.findByRole("cell", { name: "3" });
    const user = userEvent.setup();
    await user.click(screen.getByRole("checkbox", { name: "Auswählen" }));
    const bar = screen.getByText("1 ausgewählt").parentElement!;
    await user.click(within(bar).getByRole("button", { name: "Deaktivieren" }));
    expect(await screen.findByText(/erfolgreich/)).toBeInTheDocument();
    expect(screen.queryByText("1 ausgewählt")).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Auswählen" })).not.toBeChecked();
  });
});

describe("Benutzerliste — Auswahl nach dem Zuordnen", () => {
  it("hält keine Zeile fest, die nach der Aktion nicht mehr angezeigt wird", async () => {
    renderPage();
    await screen.findByRole("cell", { name: "3" });
    const user = userEvent.setup();
    await user.click(screen.getByRole("checkbox", { name: "Auswählen" }));
    await user.click(screen.getByRole("button", { name: "Zielgruppe zuweisen" }));
    const select = await screen.findByLabelText("Zielgruppe");
    await waitFor(() =>
      expect(within(select).getByText("Schüler:in Zyklus 1")).toBeInTheDocument(),
    );
    await user.selectOptions(select, "7");
    await user.click(screen.getByRole("button", { name: "Zuordnen" }));
    // Das Konto ist aus der Ansicht verschwunden — und damit aus der Auswahl:
    // keine Leiste mit "1 ausgewählt", die eine nächste Aktion darauf erlaubte.
    await waitFor(() => expect(screen.queryByRole("cell", { name: "3" })).not.toBeInTheDocument());
    expect(screen.queryByText("1 ausgewählt")).not.toBeInTheDocument();
  });
});
