/**
 * Was auf einer verwalteten Installation an die Stelle der Fläche tritt
 * (ADR-0017 D1).
 *
 * Geprüft wird nicht, dass ein Kasten erscheint — das wäre eine Tautologie.
 * Geprüft wird die Unterscheidung, auf die es ankommt: bei den **Rechten**
 * verschwindet nur die Matrix, die Rollen*zuweisung* bleibt. Sie ist die eine
 * Fläche, die der Kunde behält (Entscheid E2), und ein Test ist der einzige
 * Grund, aus dem sie beim nächsten Umbau nicht mitverschwindet.
 */
/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";

import i18n from "@/i18n";

import { ManagedByPlatform } from "./ManagedByPlatform";

beforeAll(async () => {
  await i18n.changeLanguage("de");
});

describe("ManagedByPlatform", () => {
  it("nennt bei den Einstellungen, wer sie verwaltet", () => {
    render(<ManagedByPlatform area="settings" />);
    // Der Name des Betreibers, nicht „nicht verfügbar": wer hier landet, soll
    // wissen, an wen er sich wendet. Er steht mehrfach — im Titel und im Text —,
    // deshalb `getAllByText`.
    expect(screen.getAllByText(/Vita Brevis/).length).toBeGreaterThan(0);
    expect(screen.getByText(/zentral gepflegt/)).toBeInTheDocument();
  });

  it("sagt bei den Rechten ausdrücklich, dass die Zuweisung beim Kunden bleibt", () => {
    render(<ManagedByPlatform area="roles" />);
    // „Wer welche Rolle hat, bestimmen Sie weiterhin selbst" — der Satz ist
    // der Unterschied zwischen einer verständlichen und einer beunruhigenden
    // Seite.
    expect(screen.getByText(/bestimmen Sie weiterhin selbst/)).toBeInTheDocument();
  });

  it("verweist auf das Audit-Protokoll, wo der geltende Stand steht", () => {
    render(<ManagedByPlatform area="settings" />);
    expect(screen.getByText(/platform_settings_reconciled/)).toBeInTheDocument();
  });
});
