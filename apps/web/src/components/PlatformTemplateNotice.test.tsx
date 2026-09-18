/**
 * Die drei Lagen aus ADR-0018, wie sie auf der Seite ankommen.
 *
 * Der Satz, um den es geht, ist der bei der Sperre: „Ihr eigener Text bleibt
 * gespeichert." Er ist der Unterschied zwischen einer Seite, die erklärt, und
 * einer, die nach Datenverlust aussieht — und er entspricht dem Entscheid D3,
 * dass eine Sperre den Vorrang umkehrt und nichts löscht.
 */
/* @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeAll, describe, expect, it } from "vitest";

import type { DocumentTemplateOut, PlatformTemplateOut } from "@/api/types";
import i18n from "@/i18n";

import { PlatformTemplateNotice } from "./PlatformTemplateNotice";

beforeAll(async () => {
  await i18n.changeLanguage("de");
});

function withClient(node: ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

const platform: PlatformTemplateOut = {
  key: "enrollment",
  language: "de",
  subject: "Eintritt",
  body_html: "<p>Fassung des Betreibers</p>",
  may_override: true,
  version: 2,
  delivered_at: "2026-09-10T06:00:00Z",
};

const own: DocumentTemplateOut = {
  id: 7,
  key: "enrollment",
  language: "de",
  school_id: null,
  subject: "Eigener Betreff",
  body_html: "<p>Selbst geschrieben</p>",
  is_active: true,
  updated_by: "admin@example.ch",
  updated_at: "2026-09-01T06:00:00Z",
  platform_version_ack: null,
  platform_update_available: true,
  superseded_by_platform: false,
};

describe("PlatformTemplateNotice", () => {
  it("zeigt nichts, wenn der Betreiber nichts geliefert hat", () => {
    // Der Fall der Einzelinstallation: dort gibt es keinen Betreiber ausser
    // dem Kunden, und ein Kasten „nichts geliefert“ wäre nur Rauschen.
    const { container } = withClient(<PlatformTemplateNotice platform={undefined} own={own} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("nennt bei einer neuen Fassung die Nummer und bietet „Gesehen“ an", () => {
    withClient(<PlatformTemplateNotice platform={platform} own={own} />);
    expect(screen.getByText(/Fassung 2/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Gesehen" })).toBeInTheDocument();
  });

  it("sagt bei einer Sperre ausdrücklich, dass der eigene Text bleibt", () => {
    withClient(
      <PlatformTemplateNotice
        platform={{ ...platform, may_override: false }}
        own={{ ...own, superseded_by_platform: true }}
      />,
    );
    expect(screen.getByText(/bleibt gespeichert/)).toBeInTheDocument();
    // Kein „Gesehen“: zu quittieren ist eine neue Fassung, nicht eine Sperre.
    expect(screen.queryByRole("button", { name: "Gesehen" })).not.toBeInTheDocument();
  });

  it("erklärt ohne eigenen Text, woher der Brief kommt", () => {
    withClient(<PlatformTemplateNotice platform={platform} own={undefined} />);
    expect(screen.getByText(/keinen eigenen Text/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Gesehen" })).not.toBeInTheDocument();
  });
});
