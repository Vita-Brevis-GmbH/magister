/**
 * Der Balken während eines Operator-Zugriffs (ADR-0019 D6).
 *
 * Geprüft wird nicht, dass ein Kasten erscheint, sondern **was** er sagt: wer
 * zusieht, warum und bis wann. Und die zweite Fassung für den Operator selbst
 * — sie ist kein Hinweis für den Kunden, sondern einer gegen den Irrtum, man
 * sei gerade im eigenen Fenster.
 */
/* @vitest-environment jsdom */
import {
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeAll, describe, expect, it } from "vitest";

import type { CurrentUserOut } from "@/api/types";
import i18n from "@/i18n";

import { OperatorAccessBanner } from "./OperatorAccessBanner";

beforeAll(async () => {
  await i18n.changeLanguage("de");
});

/**
 * Der Balken enthält einen `Link`; der braucht einen Router um sich.
 *
 * `RouterProvider` rendert erst, wenn der Router geladen hat — der erste
 * Entwurf prüfte synchron und sah einen leeren Körper. Deshalb der Anker
 * `bereit`: auf ihn wird gewartet, und danach steht der Balken (oder er
 * steht nachweislich nicht da).
 */
async function withRouter(node: ReactElement) {
  const root = createRootRoute({
    component: () => (
      <>
        <span>bereit</span>
        {node}
      </>
    ),
  });
  const index = createRoute({ getParentRoute: () => root, path: "/", component: () => null });
  const accesses = createRoute({
    getParentRoute: () => root,
    path: "/operator-accesses",
    component: () => null,
  });
  const router = createRouter({
    routeTree: root.addChildren([index, accesses]),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const view = render(<RouterProvider router={router as any} />);
  await screen.findByText("bereit");
  return view;
}

const base: CurrentUserOut = {
  ad_object_guid: "00000000-0000-0000-0000-0000000000a1",
  upn: "sl-a@example.ch",
  given_name: null,
  surname: null,
  display_name: "Anna Meier",
  is_admin: false,
  kind: "teacher",
  school_scope: [1],
  roles: ["schulleitung"],
  expires_at: "2026-09-11T18:00:00Z",
  is_operator: false,
  operator_active: null,
};

const access = {
  operator: "matthias.hadorn@vitabrevis.ch",
  reason: "Klassenlehrerin sieht die Klasse 4a nicht.",
  ticket: "4711",
  until: "2026-09-11T10:30:00Z",
};

describe("OperatorAccessBanner", () => {
  it("zeigt nichts, wenn kein Zugriff läuft", async () => {
    await withRouter(<OperatorAccessBanner me={base} />);
    // Der Normalfall. Ein Balken „niemand sieht zu“ wäre Rauschen, das man
    // nach zwei Tagen nicht mehr liest.
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("nennt dem Kunden Person, Grund und Frist", async () => {
    await withRouter(<OperatorAccessBanner me={{ ...base, operator_active: access }} />);
    expect(screen.getByText(/Vita Brevis sieht zu/)).toBeInTheDocument();
    expect(screen.getByText(/matthias\.hadorn@vitabrevis\.ch/)).toBeInTheDocument();
    expect(screen.getByText(/4711/)).toBeInTheDocument();
  });

  it("sagt dem Operator, dass er in einer fremden Installation ist", async () => {
    await withRouter(
      <OperatorAccessBanner me={{ ...base, is_operator: true, operator_active: access }} />,
    );
    expect(screen.getByText(/Fremde Installation/)).toBeInTheDocument();
    // Nicht die Kundenfassung: „Vita Brevis sieht zu“ an den Operator selbst
    // gerichtet wäre eine Auskunft über ihn, die er nicht braucht.
    expect(screen.queryByText(/Vita Brevis sieht zu/)).not.toBeInTheDocument();
  });

  it("führt zur Liste", async () => {
    await withRouter(<OperatorAccessBanner me={{ ...base, operator_active: access }} />);
    const link = screen.getByRole("link", { name: /Zugriffe ansehen/ });
    expect(link).toHaveAttribute("href", "/operator-accesses");
  });
});
