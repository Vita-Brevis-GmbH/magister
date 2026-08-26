/* @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";
import { ModulesPage } from "./_app.admin.modules";

beforeAll(async () => {
  await i18n.changeLanguage("de");
});

const fetchMock = vi.fn();

const SCHOOL_MODULES = {
  instance_profile: "school",
  known_profiles: ["school", "company", "neutral"],
  module_overrides: {},
  modules: [
    { id: "platform", toggleable: false, enabled: true, depends_on: [], default_in_profiles: [] },
    {
      id: "classes",
      toggleable: true,
      enabled: true,
      depends_on: ["platform"],
      default_in_profiles: ["school"],
    },
    {
      id: "departments",
      toggleable: true,
      enabled: false,
      depends_on: ["platform"],
      default_in_profiles: ["company"],
    },
    {
      id: "devices",
      toggleable: true,
      enabled: true,
      depends_on: ["platform"],
      default_in_profiles: ["school", "company"],
    },
  ],
};

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

function renderWithQuery(node: React.ReactNode): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

function putCalls(): unknown[][] {
  return fetchMock.mock.calls.filter(
    (c) => String(c[0]) === "/api/admin/modules" && (c[1] as RequestInit)?.method === "PUT",
  );
}

describe("ModulesPage — safe edition switch", () => {
  it("does not switch on select; confirms via dialog with an effect preview", async () => {
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (String(url) === "/api/admin/modules" && init?.method === "PUT") {
        return Promise.resolve(jsonResponse({ ...SCHOOL_MODULES, instance_profile: "company" }));
      }
      return Promise.resolve(jsonResponse(SCHOOL_MODULES));
    });

    renderWithQuery(<ModulesPage />);
    const user = userEvent.setup();

    // The profile <select> is rendered once the GET resolves.
    const select = await screen.findByRole("combobox");

    // Picking "company" must NOT immediately PUT — it opens a confirmation.
    await user.selectOptions(select, "company");
    expect(putCalls()).toHaveLength(0);

    // The dialog previews the module delta: departments on, classes off.
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(/Abteilungen/);
    expect(dialog).toHaveTextContent(/Klassen/);

    // Confirm commits the switch.
    await user.click(screen.getByRole("button", { name: /^Umstellen$/ }));
    await waitFor(() => expect(putCalls()).toHaveLength(1));
    const body = JSON.parse((putCalls()[0][1] as RequestInit).body as string);
    expect(body.instance_profile).toBe("company");
  });
});
