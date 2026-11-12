/**
 * Zielgruppen: die Ziel-OU steht unter den Standorten. Sichtbar bei freier
 * Kontoart oder ohne Standort; ohne Standort Pflicht. "Passwortstärke".
 */
/* @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";

const { GroupTemplatesPage } = await import("./_app.admin.group-templates");

const fetchMock = vi.fn();
const SCHOOLS = [
  { id: 1, name: "Schule A", kuerzel: "A", scope_short: "A" },
  { id: 2, name: "Schule B", kuerzel: "B", scope_short: "B" },
];

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { headers: { "content-type": "application/json" } });
}

beforeAll(async () => {
  await i18n.changeLanguage("de");
});

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockImplementation((url: string) => {
    const u = String(url);
    if (u.endsWith("/api/schools")) return Promise.resolve(json(SCHOOLS));
    if (u.endsWith("/api/me/modules"))
      return Promise.resolve(json({ profile: "school", modules: [] }));
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
      <GroupTemplatesPage />
    </QueryClientProvider>,
  );
}

const follows = (a: Element, b: Element): boolean =>
  Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

describe("Zielgruppe — Ziel-OU", () => {
  it("steht unter den Standorten und ist ohne Standort Pflicht", async () => {
    renderPage();
    const user = userEvent.setup();
    const schoolA = await screen.findByRole("checkbox", { name: "Schule A" });
    await user.type(screen.getByPlaceholderText(/Tool-X|z\. B\./i), "Sonstige");

    const ou = screen.getByLabelText("Ziel-OU");
    expect(ou).toBeRequired();
    expect(follows(schoolA, ou)).toBe(true);
    expect(follows(screen.getByLabelText("Passwortstärke"), ou)).toBe(true);
    const create = screen.getByRole("button", { name: "Zielgruppe anlegen" });
    expect(create).toBeDisabled();
    expect(screen.getByText(/ist die Ziel-OU Pflicht/)).toBeInTheDocument();

    await user.type(ou, "OU=Sonstige,DC=schule,DC=local");
    expect(create).toBeEnabled();
  });

  it("wird mit Standort optional und bei fester Kontoart ausgeblendet", async () => {
    renderPage();
    const user = userEvent.setup();
    const schoolA = await screen.findByRole("checkbox", { name: "Schule A" });
    await user.click(schoolA);
    expect(screen.getByLabelText("Ziel-OU (optional)")).not.toBeRequired();

    await user.selectOptions(screen.getByLabelText(/^Kontoart/), "teacher");
    expect(screen.queryByLabelText(/^Ziel-OU/)).not.toBeInTheDocument();

    // Standort wieder abwählen → Feld zurück, wieder Pflicht.
    await user.click(schoolA);
    expect(screen.getByLabelText("Ziel-OU")).toBeRequired();
  });
});
