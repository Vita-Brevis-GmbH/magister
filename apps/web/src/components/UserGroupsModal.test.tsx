/* @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";
import type { AdUserOut } from "@/api/types";
import { UserGroupsModal } from "./UserGroupsModal";

beforeAll(async () => {
  await i18n.changeLanguage("de");
});

const G_A = "CN=GroupA,OU=Groups,DC=x";
const G_B = "CN=GroupB,OU=Groups,DC=x";

const USER: AdUserOut = {
  ad_object_guid: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
  school_id: 1,
  upn: "max@schule.example.ch",
  sam_account_name: "max",
  given_name: "Max",
  surname: "Muster",
  display_name: null,
  mail: null,
  kind: "student",
  enabled: true,
  last_sync_at: null,
  street_address: null,
  locality: null,
  postal_code: null,
  country: null,
  device_name: null,
  temp_device_name: null,
  jahrgangsstufe: null,
  password_never_expires: false,
  cannot_change_password: false,
  store_password: false,
  ad_groups: [G_A],
};

const CATALOG = [
  {
    ad_object_guid: "g1",
    distinguished_name: G_A,
    cn: "GroupA",
    sam_account_name: null,
    description: null,
  },
  {
    ad_object_guid: "g2",
    distinguished_name: G_B,
    cn: "GroupB",
    sam_account_name: null,
    description: null,
  },
];

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

function renderModal(): { onClose: ReturnType<typeof vi.fn> } {
  const onClose = vi.fn();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <UserGroupsModal user={USER} onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onClose };
}

describe("UserGroupsModal", () => {
  it("sends the updated membership and closes on success", async () => {
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (typeof url === "string" && url.includes("/admin/ad-groups")) {
        return Promise.resolve(jsonResponse(CATALOG));
      }
      if (typeof url === "string" && url.includes("/groups") && init?.method === "PUT") {
        return Promise.resolve(
          jsonResponse({ added: [G_B], removed: [], failed: [], groups: [G_A, G_B] }),
        );
      }
      return Promise.resolve(jsonResponse({}));
    });

    const { onClose } = renderModal();
    const user = userEvent.setup();

    // GroupB checkbox appears once the catalog loads; add it.
    const boxB = await screen.findByRole("checkbox", { name: /GroupB/i });
    await user.click(boxB);
    await user.click(screen.getByRole("button", { name: /speichern/i }));

    await waitFor(() => {
      const putCall = fetchMock.mock.calls.find(
        (c) => typeof c[0] === "string" && c[0].includes("/groups") && c[1]?.method === "PUT",
      );
      expect(putCall).toBeDefined();
      const payload = JSON.parse((putCall![1] as RequestInit).body as string);
      expect(payload.groups).toEqual([G_A, G_B]);
    });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("keeps the modal open and warns when some group writes fail", async () => {
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (typeof url === "string" && url.includes("/admin/ad-groups")) {
        return Promise.resolve(jsonResponse(CATALOG));
      }
      if (typeof url === "string" && url.includes("/groups") && init?.method === "PUT") {
        return Promise.resolve(
          jsonResponse({ added: [], removed: [], failed: [G_B], groups: [G_A] }),
        );
      }
      return Promise.resolve(jsonResponse({}));
    });

    const { onClose } = renderModal();
    const user = userEvent.setup();

    const boxB = await screen.findByRole("checkbox", { name: /GroupB/i });
    await user.click(boxB);
    await user.click(screen.getByRole("button", { name: /speichern/i }));

    expect(await screen.findByText(/konnten nicht geändert werden/i)).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });
});
