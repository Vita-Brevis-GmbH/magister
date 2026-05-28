/* @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";
import type { AdUserOut } from "@/api/types";
import { UserStatusModal } from "./UserStatusModal";

beforeAll(async () => {
  await i18n.changeLanguage("de");
});

const ENABLED_USER: AdUserOut = {
  ad_object_guid: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
  school_id: 1,
  upn: "tom.muster@schule.example.ch",
  sam_account_name: null,
  given_name: "Tom",
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
};

const DISABLED_USER: AdUserOut = { ...ENABLED_USER, enabled: false };

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    ...init,
    headers: { "content-type": "application/json", ...(init.headers ?? {}) },
  });
}

function renderModal(props: { user?: AdUserOut | null; onClose?: () => void }): {
  onClose: ReturnType<typeof vi.fn>;
} {
  const onClose = vi.fn(props.onClose);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <UserStatusModal user={props.user ?? ENABLED_USER} onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onClose };
}

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  document.cookie = "";
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("UserStatusModal", () => {
  it("submits a disable request with the typed reason and closes on success", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ...ENABLED_USER, enabled: false }));

    const { onClose } = renderModal({});
    const user = userEvent.setup();

    expect(await screen.findByText(/Account deaktivieren/)).toBeInTheDocument();
    expect(screen.getByText(/kann sich nicht mehr anmelden/i)).toBeInTheDocument();

    await user.type(screen.getByLabelText(/Begründung/i), "Schulaustritt 2026");
    await user.click(screen.getByRole("button", { name: /^Deaktivieren$/ }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    expect(fetchMock.mock.calls[0]![0]).toBe(`/api/users/${ENABLED_USER.ad_object_guid}/status`);
    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body as string)).toEqual({
      enabled: false,
      reason: "Schulaustritt 2026",
    });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("submits an enable request when the user is currently disabled", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ...DISABLED_USER, enabled: true }));

    renderModal({ user: DISABLED_USER });
    const user = userEvent.setup();

    expect(await screen.findByText(/Account aktivieren/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Aktivieren$/ }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({ enabled: true });
  });

  it("omits the reason when the input is left blank", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ...ENABLED_USER, enabled: false }));

    renderModal({});
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Deaktivieren$/ }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    const body = JSON.parse((fetchMock.mock.calls[0]![1] as RequestInit).body as string);
    expect(body).toEqual({ enabled: false });
    expect(body).not.toHaveProperty("reason");
  });

  it("shows the cannot-disable-self message when the backend returns 400", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "cannot_disable_self" }, { status: 400 }));

    const { onClose } = renderModal({});
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Deaktivieren$/ }));

    expect(await screen.findByText(/eigenen Account nicht deaktivieren/i)).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("shows the ad-unavailable message on 503", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "ad_unavailable" }, { status: 503 }));

    renderModal({});
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Deaktivieren$/ }));

    expect(await screen.findByText(/Active Directory ist nicht erreichbar/i)).toBeInTheDocument();
  });
});
