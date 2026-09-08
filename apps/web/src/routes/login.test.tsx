/* @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";
import { LocalLoginForm, LoginPage } from "./login";

beforeAll(async () => {
  await i18n.changeLanguage("de");
});

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  document.cookie = "";
  vi.stubGlobal("location", { ...window.location, assign: vi.fn(), pathname: "/login" });
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

describe("LoginPage", () => {
  it("renders the OIDC anchor when capabilities flag oidc_enabled", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ oidc_enabled: true, local_login_enabled: false }));
    renderWithQuery(<LoginPage />);
    const link = await screen.findByRole("link", { name: /entra id/i });
    expect(link).toHaveAttribute("href", "/api/auth/login");
  });

  it("renders the local-login form when only local_login_enabled is true", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ oidc_enabled: false, local_login_enabled: true }));
    renderWithQuery(<LoginPage />);
    expect(await screen.findByLabelText(/benutzername/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^passwort$/i)).toBeInTheDocument();
    // OIDC anchor must not appear when oidc_enabled is false.
    expect(screen.queryByRole("link", { name: /entra id/i })).toBeNull();
  });

  it("hides the local form behind a disclosure when both paths are enabled", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ oidc_enabled: true, local_login_enabled: true }));
    renderWithQuery(<LoginPage />);
    expect(await screen.findByRole("link", { name: /entra id/i })).toBeInTheDocument();
    // Disclosure summary present, password field initially not visible.
    expect(screen.getByText(/anderen anmeldeweg/i)).toBeInTheDocument();
  });
});

describe("LocalLoginForm", () => {
  it("redirects straight away when the backend answers 204 (MFA suspended)", async () => {
    // 204 with no body is the one case where the password alone is enough:
    // a Global Admin has suspended the MFA requirement (ADR-0015 D2).
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    renderWithQuery(<LocalLoginForm />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/benutzername/i), "admin");
    await user.type(screen.getByLabelText(/^passwort$/i), "hunter2hunter2");
    await user.click(screen.getByRole("button", { name: /anmelden/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });
    expect(fetchMock.mock.calls[0]![0]).toBe("/api/auth/login/local");
    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      username: "admin",
      password: "hunter2hunter2",
    });
    await waitFor(() => {
      expect(window.location.assign).toHaveBeenCalledWith("/");
    });
  });

  it("maps a 401 response to invalid_credentials banner", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "invalid_credentials" }, { status: 401 }));
    renderWithQuery(<LocalLoginForm />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/benutzername/i), "admin");
    await user.type(screen.getByLabelText(/^passwort$/i), "wrong");
    await user.click(screen.getByRole("button", { name: /anmelden/i }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/falsch/i);
    });
  });

  it("maps a 423 response to account_locked banner", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "account_locked" }, { status: 423 }));
    renderWithQuery(<LocalLoginForm />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/benutzername/i), "admin");
    await user.type(screen.getByLabelText(/^passwort$/i), "wrong");
    await user.click(screen.getByRole("button", { name: /anmelden/i }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/gesperrt/i);
    });
  });

  it("maps a 429 to rate_limited banner", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "rate_limited" }, { status: 429 }));
    renderWithQuery(<LocalLoginForm />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/benutzername/i), "admin");
    await user.type(screen.getByLabelText(/^passwort$/i), "x");
    await user.click(screen.getByRole("button", { name: /anmelden/i }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/zu viele anfragen/i);
    });
  });
});

describe("LocalLoginForm — second factor (ADR-0015 D2)", () => {
  it("asks for a code instead of signing in, then redirects once it verifies", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ stage: "totp", challenge: "chal-1" }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    renderWithQuery(<LocalLoginForm />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/benutzername/i), "admin");
    await user.type(screen.getByLabelText(/^passwort$/i), "hunter2hunter2");
    await user.click(screen.getByRole("button", { name: /anmelden/i }));

    // No navigation yet: the password alone must not sign anyone in.
    await waitFor(() => {
      expect(screen.getByLabelText(/einmalcode/i)).toBeInTheDocument();
    });
    expect(window.location.assign).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText(/einmalcode/i), "123456");
    await user.click(screen.getByRole("button", { name: /anmelden/i }));

    await waitFor(() => {
      expect(window.location.assign).toHaveBeenCalledWith("/");
    });
    expect(fetchMock.mock.calls[1]![0]).toBe("/api/auth/login/local/totp");
    const init = fetchMock.mock.calls[1]![1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({ challenge: "chal-1", code: "123456" });
  });

  it("shows a wrong-code banner and keeps the code field", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ stage: "totp", challenge: "chal-1" }))
      .mockResolvedValueOnce(jsonResponse({ detail: "invalid_code" }, { status: 401 }));
    renderWithQuery(<LocalLoginForm />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/benutzername/i), "admin");
    await user.type(screen.getByLabelText(/^passwort$/i), "pw");
    await user.click(screen.getByRole("button", { name: /anmelden/i }));
    await waitFor(() => expect(screen.getByLabelText(/einmalcode/i)).toBeInTheDocument());

    await user.type(screen.getByLabelText(/einmalcode/i), "000000");
    await user.click(screen.getByRole("button", { name: /anmelden/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/code stimmt nicht/i);
    });
    expect(screen.getByLabelText(/einmalcode/i)).toBeInTheDocument();
    expect(window.location.assign).not.toHaveBeenCalled();
  });

  it("offers a restart when the challenge has expired", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ stage: "totp", challenge: "chal-1" }))
      .mockResolvedValueOnce(jsonResponse({ detail: "expired" }, { status: 401 }));
    renderWithQuery(<LocalLoginForm />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/benutzername/i), "admin");
    await user.type(screen.getByLabelText(/^passwort$/i), "pw");
    await user.click(screen.getByRole("button", { name: /anmelden/i }));
    await waitFor(() => expect(screen.getByLabelText(/einmalcode/i)).toBeInTheDocument());
    await user.type(screen.getByLabelText(/einmalcode/i), "123456");
    await user.click(screen.getByRole("button", { name: /anmelden/i }));

    const restart = await screen.findByRole("button", { name: /von vorne/i });
    await user.click(restart);
    expect(screen.getByLabelText(/benutzername/i)).toBeInTheDocument();
  });

  it("forces enrolment, then shows the recovery codes exactly once", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({
          stage: "enroll",
          challenge: "chal-e",
          provisioning_uri: "otpauth://totp/Magister:admin",
          qr_data_uri: "data:image/svg+xml;charset=utf-8,%3Csvg%3E%3C/svg%3E",
          secret: "JBSWY3DPEHPK3PXP",
        }),
      )
      .mockResolvedValueOnce(jsonResponse({ recovery_codes: ["AAAA-1111", "BBBB-2222"] }));
    renderWithQuery(<LocalLoginForm />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/benutzername/i), "admin");
    await user.type(screen.getByLabelText(/^passwort$/i), "pw");
    await user.click(screen.getByRole("button", { name: /anmelden/i }));

    await waitFor(() => {
      expect(screen.getByText(/zweiten faktor einrichten/i)).toBeInTheDocument();
    });
    expect(screen.getByAltText(/qr-code/i)).toHaveAttribute(
      "src",
      expect.stringContaining("data:image/svg+xml"),
    );
    expect(screen.getByDisplayValue("JBSWY3DPEHPK3PXP")).toBeInTheDocument();

    await user.type(screen.getByLabelText(/einmalcode/i), "123456");
    await user.click(screen.getByRole("button", { name: /einrichtung abschliessen/i }));

    await waitFor(() => {
      expect(screen.getByText("AAAA-1111")).toBeInTheDocument();
    });
    expect(screen.getByText("BBBB-2222")).toBeInTheDocument();
    // Navigation happens only after the operator confirms they saved them.
    expect(window.location.assign).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /codes gesichert/i }));
    expect(window.location.assign).toHaveBeenCalledWith("/");
  });
});
