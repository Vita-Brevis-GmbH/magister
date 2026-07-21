/* @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";
import type { DeviceOut } from "@/api/types";
import { AssignDeviceModal, CreateDeviceModal } from "./_app.devices";

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

function renderWithQuery(node: React.ReactNode): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

const DEVICE: DeviceOut = {
  id: 5,
  name: "iPad-01",
  device_type: null,
  serial_number: null,
  notes: null,
  school_id: null,
  class_id: null,
  assigned_person_guid: null,
  assigned_person_name: null,
  is_loan: false,
  ad_object_guid: null,
  source: "manual",
  created_at: "2026-07-13T00:00:00+00:00",
  updated_at: "2026-07-13T00:00:00+00:00",
};

function postBody(path: string): Record<string, unknown> {
  const call = fetchMock.mock.calls.find((c) => String(c[0]) === path);
  expect(call).toBeTruthy();
  return JSON.parse((call![1] as RequestInit).body as string) as Record<string, unknown>;
}

describe("CreateDeviceModal", () => {
  it("posts name + attributes and nulls empty optional fields", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ...DEVICE, name: "Beamer" }));

    renderWithQuery(<CreateDeviceModal open={true} onClose={() => {}} />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/bezeichnung/i), "Beamer");
    await user.type(screen.getByLabelText(/^typ$/i), "Beamer");
    await user.click(screen.getByRole("button", { name: /erstellen/i }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some((c) => String(c[0]) === "/api/devices")).toBe(true);
    });
    const body = postBody("/api/devices");
    expect(body).toEqual({
      name: "Beamer",
      device_type: "Beamer",
      serial_number: null,
      notes: null,
    });
  });
});

describe("AssignDeviceModal", () => {
  it("assigning to a school posts the school_id", async () => {
    fetchMock.mockImplementation((input: string) => {
      const url = String(input);
      if (url.endsWith("/schools")) {
        return Promise.resolve(
          jsonResponse([{ id: 3, name: "Schule A", kuerzel: "A", scope_short: "A" }]),
        );
      }
      return Promise.resolve(jsonResponse({ ...DEVICE, school_id: 3 }));
    });

    renderWithQuery(
      <AssignDeviceModal
        target={DEVICE}
        schools={[
          {
            id: 3,
            name: "Schule A",
            kuerzel: "A",
            scope_short: "A",
            ad_ou_students_zyklus3: null,
            ad_ou_students_other: null,
            ad_ou_teachers: null,
            ad_ou_devices: null,
            ad_groups_teacher: [],
            ad_groups_student_zyklus1: [],
            ad_groups_student_zyklus2: [],
            ad_groups_student_zyklus3: [],
          },
        ]}
        classes={[]}
        onClose={() => {}}
      />,
    );
    const user = userEvent.setup();

    await user.selectOptions(screen.getByLabelText(/zuweisung/i), "school");
    await user.selectOptions(screen.getByLabelText(/schule/i), "3");
    await user.click(screen.getByRole("button", { name: /zuweisung speichern/i }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some((c) => String(c[0]) === "/api/devices/5/assign")).toBe(true);
    });
    const body = postBody("/api/devices/5/assign");
    expect(body).toEqual({
      assignment_type: "school",
      person_guid: null,
      class_id: null,
      school_id: 3,
      is_loan: false,
    });
  });

  it("free assignment posts assignment_type=free with null targets", async () => {
    fetchMock.mockResolvedValue(jsonResponse(DEVICE));

    renderWithQuery(
      <AssignDeviceModal
        target={{ ...DEVICE, school_id: 3 }}
        schools={[]}
        classes={[]}
        onClose={() => {}}
      />,
    );
    const user = userEvent.setup();

    await user.selectOptions(screen.getByLabelText(/zuweisung/i), "free");
    await user.click(screen.getByRole("button", { name: /zuweisung speichern/i }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some((c) => String(c[0]) === "/api/devices/5/assign")).toBe(true);
    });
    expect(postBody("/api/devices/5/assign").assignment_type).toBe("free");
  });
});
