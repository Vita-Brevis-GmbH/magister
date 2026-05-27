/* @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";
import type { AdUserOut } from "@/api/types";
import { ResetPasswordModal } from "./ResetPasswordModal";

beforeAll(async () => {
  // Pin to DE so the regex assertions stay deterministic regardless of the
  // jsdom-detected navigator.language.
  await i18n.changeLanguage("de");
});

const STUDENT: AdUserOut = {
  ad_object_guid: "11111111-2222-3333-4444-555555555555",
  school_id: 1,
  upn: "anna.muster@schule.example.ch",
  sam_account_name: null,
  given_name: "Anna",
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

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    ...init,
    headers: { "content-type": "application/json", ...(init.headers ?? {}) },
  });
}

function renderModal(props: { student?: AdUserOut | null; onClose?: () => void }): {
  onClose: ReturnType<typeof vi.fn>;
} {
  const onClose = vi.fn(props.onClose);
  // Each test gets a fresh QueryClient so mutation state doesn't leak between cases.
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ResetPasswordModal student={props.student ?? STUDENT} onClose={onClose} />
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

describe("ResetPasswordModal", () => {
  it("submits generate mode and reveals the one-time password", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ mode: "generate", force_change: true, temp_password: "Tmp-abc-12345" }),
    );

    renderModal({});
    const user = userEvent.setup();

    expect(await screen.findByText(/Anna Muster/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /passwort zurücksetzen/i }));

    expect(await screen.findByText("Tmp-abc-12345")).toBeInTheDocument();
    expect(screen.getByText(/wird nicht erneut angezeigt/i)).toBeInTheDocument();

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0]![0]).toBe(
      "/api/students/11111111-2222-3333-4444-555555555555/password-reset",
    );
    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ mode: "generate", force_change: true });
  });

  it("disables submit in manual mode until the password is long enough", async () => {
    renderModal({});
    const user = userEvent.setup();

    await user.click(screen.getByLabelText(/manuell setzen/i));
    const submit = screen.getByRole("button", { name: /passwort zurücksetzen/i });
    expect(submit).toBeDisabled();

    await user.type(screen.getByLabelText(/neues passwort/i), "shortpw");
    expect(submit).toBeDisabled();

    await user.type(screen.getByLabelText(/neues passwort/i), "-long-enough");
    expect(submit).toBeEnabled();
  });

  it("maps a 503 ad_unavailable response to the i18n banner", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "ad_unavailable" }, { status: 503 }));

    renderModal({});
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /passwort zurücksetzen/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/active directory/i);
    });
  });
});
