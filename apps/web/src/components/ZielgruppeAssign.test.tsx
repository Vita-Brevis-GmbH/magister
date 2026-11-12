/**
 * Zielgruppe nachträglich zuweisen: was an die API geht und was die Seite
 * danach sagt — vor allem, dass die OU bei unpassender Kontoart bleibt.
 */
/* @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";

import { ZielgruppeAssign } from "./ZielgruppeAssign";

const fetchMock = vi.fn();

beforeAll(async () => {
  await i18n.changeLanguage("de");
});

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    headers: { "content-type": "application/json" },
  });
}

function withClient(node: ReactNode): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

const templates = [
  {
    id: 3,
    name: "Schüler:in Zyklus 3",
    description: null,
    kind: "student_zyklus3",
    ad_groups: ["CN=Z3"],
    school_ids: [1],
    status: "active",
    created_at: "2026-10-19T00:00:00Z",
    updated_at: "2026-10-19T00:00:00Z",
    password_profile: "readable",
    force_change: true,
    cannot_change_password: false,
    password_never_expires: false,
    store_password: false,
  },
];

describe("ZielgruppeAssign", () => {
  it("schickt Konten, Zielgruppe und Einstellungs-Schalter und meldet bleibende OU", async () => {
    fetchMock.mockImplementation((url: string) => {
      if (String(url).includes("/assign")) {
        return Promise.resolve(
          json([
            {
              ad_object_guid: "g1",
              ok: true,
              error: null,
              added: ["CN=Z3"],
              removed: ["CN=Z2"],
              failed: [],
              ou_unchanged: false,
            },
            {
              ad_object_guid: "g2",
              ok: true,
              error: null,
              added: ["CN=Z3"],
              removed: [],
              failed: [],
              ou_unchanged: true,
            },
          ]),
        );
      }
      return Promise.resolve(json(templates));
    });

    withClient(<ZielgruppeAssign guids={["g1", "g2"]} schoolId={1} />);
    const user = userEvent.setup();
    await screen.findByRole("option", { name: "Schüler:in Zyklus 3" });
    await user.selectOptions(screen.getByLabelText("Zielgruppe"), "3");
    await user.click(screen.getByLabelText(/Konto-Einstellungen der Zielgruppe/));
    await user.click(screen.getByRole("button", { name: "2 Konten zuordnen" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) => String(c[0]).includes("/assign"));
      expect(call).toBeTruthy();
      expect(String(call![0])).toBe("/api/admin/group-templates/3/assign");
      expect(JSON.parse((call![1] as RequestInit).body as string)).toEqual({
        ad_object_guids: ["g1", "g2"],
        apply_settings: false,
      });
    });
    expect(
      await screen.findByText("Zugeordnet: 2, fehlgeschlagen: 0, Gruppen entfernt: 1."),
    ).toBeInTheDocument();
    expect(screen.getByText(/es bleibt in seiner bisherigen OU/)).toBeInTheDocument();
  });

  it("nennt Fehler je Konto in Worten", async () => {
    fetchMock.mockImplementation((url: string) =>
      Promise.resolve(
        String(url).includes("/assign")
          ? json([
              {
                ad_object_guid: "g1",
                ok: false,
                error: "not_for_school",
                added: [],
                removed: [],
                failed: [],
                ou_unchanged: false,
              },
            ])
          : json(templates),
      ),
    );
    withClient(<ZielgruppeAssign guids={["g1"]} currentTemplateId={3} schoolId={1} />);
    const user = userEvent.setup();
    await screen.findByRole("option", { name: "Schüler:in Zyklus 3" });
    await user.click(screen.getByRole("button", { name: "Zuordnen" }));
    expect(
      await screen.findByText("Die Zielgruppe ist am Standort des Kontos nicht verfügbar."),
    ).toBeInTheDocument();
  });
});
