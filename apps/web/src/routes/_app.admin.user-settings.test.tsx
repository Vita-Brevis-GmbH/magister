/* @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";
import type { AdGroupOut, AdUserSettingsOut } from "@/api/types";
import { UserSettingsForm } from "./_app.admin.user-settings";

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

function makeData(overrides: Partial<AdUserSettingsOut> = {}): AdUserSettingsOut {
  return {
    version: 1,
    ad_ou_students_zyklus3: null,
    ad_ou_students_other: null,
    ad_ou_teachers: null,
    zyklus1_max_grade: 2,
    zyklus2_max_grade: 6,
    password_store_enabled: false,
    ad_groups_search_base: null,
    ad_groups_teacher: [],
    ad_groups_student_zyklus1: [],
    ad_groups_student_zyklus2: [],
    ad_groups_student_zyklus3: [],
    ...overrides,
  };
}

const GROUPS: AdGroupOut[] = [
  {
    ad_object_guid: "g1",
    distinguished_name: "CN=Lehrer,OU=Groups,DC=x",
    cn: "Lehrer",
    sam_account_name: "Lehrer",
    description: null,
  },
];

function renderForm(data: AdUserSettingsOut, groups: AdGroupOut[] = GROUPS): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <UserSettingsForm data={data} groups={groups} />
    </QueryClientProvider>,
  );
}

describe("UserSettingsForm", () => {
  it("checks the already-selected group DN from props", () => {
    renderForm(makeData({ ad_groups_teacher: ["CN=Lehrer,OU=Groups,DC=x"] }));
    const checkboxes = screen.getAllByRole("checkbox", { name: /Lehrer/i });
    // The teacher-groups picker row is checked.
    expect(checkboxes.some((c) => (c as HTMLInputElement).checked)).toBe(true);
  });

  it("sends the toggled group DN on save", async () => {
    fetchMock.mockResolvedValue(jsonResponse(makeData({ version: 2 })));
    renderForm(makeData());
    const user = userEvent.setup();

    // The catalog group renders as a checkbox in the teacher picker (first one).
    const box = screen.getAllByRole("checkbox", { name: /Lehrer/i })[0]!;
    await user.click(box);
    await user.click(screen.getByRole("button", { name: /speichern/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    expect(fetchMock.mock.calls[0]![0]).toBe("/api/admin/user-settings");
    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    expect(init.method).toBe("PUT");
    const payload = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(payload.ad_groups_teacher).toEqual(["CN=Lehrer,OU=Groups,DC=x"]);
  });
});
