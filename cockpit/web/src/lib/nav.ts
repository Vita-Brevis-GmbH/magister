import { useEffect, useState } from "react";

/**
 * Navigation über den Hash — kein Router als Abhängigkeit.
 *
 * Die Konsole hat eine Handvoll Ansichten und wird von zwei Personen benutzt. Ein
 * Router (TanStack, wie in `apps/web`) bringt Datenlader, Suchparameter-Typen
 * und verschachtelte Layouts mit; nichts davon wird hier gebraucht, und jede
 * Abhängigkeit ist eine, die aktualisiert werden muss.
 *
 * Der Hash und nicht der Pfad: damit braucht das statische Ausliefern der
 * Konsole keine Server-Regel, die alle Pfade auf `index.html` umschreibt. Ein
 * Neuladen von `/tenants/<id>` wäre sonst ein 404 — der Fehler, den man erst
 * beim ersten Weiterleiten eines Links bemerkt.
 *
 * Wächst die Konsole über eine Handvoll Ansichten hinaus, ist ein Router der
 * richtige Schritt. Dieser Haken ist dann in einer Datei ersetzt.
 */

export type Route =
  | { view: "instances" }
  | { view: "templates" }
  | { view: "fleet" }
  | { view: "tenants" }
  | { view: "tenant"; id: string; tab: TenantTab };

export type TenantTab =
  | "uebersicht"
  | "sicherungen"
  | "connector"
  | "zugriff"
  | "offboarding";

const TENANT_TABS: readonly TenantTab[] = [
  "uebersicht",
  "sicherungen",
  "connector",
  "zugriff",
  "offboarding",
];

export function parseHash(hash: string): Route {
  // "#/tenants/<uuid>/sicherungen" → Teile ohne Leerstrings
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (parts[0] === "tenants" && parts[1]) {
    const tab = parts[2];
    return {
      view: "tenant",
      id: parts[1],
      tab: TENANT_TABS.includes(tab as TenantTab) ? (tab as TenantTab) : "uebersicht",
    };
  }
  if (parts[0] === "tenants") return { view: "tenants" };
  if (parts[0] === "instances") return { view: "instances" };
  if (parts[0] === "templates") return { view: "templates" };
  if (parts[0] === "fleet") return { view: "fleet" };
  // Vorgabe: die Kundenliste. Die Konsole ist für Kunden da; die Instanzen
  // sind der ältere Zweck und stehen jetzt daneben.
  return { view: "tenants" };
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export function href(route: Route): string {
  switch (route.view) {
    case "instances":
      return "#/instances";
    case "templates":
      return "#/templates";
    case "fleet":
      return "#/fleet";
    case "tenants":
      return "#/tenants";
    case "tenant":
      return `#/tenants/${route.id}/${route.tab}`;
  }
}

export function go(route: Route): void {
  window.location.hash = href(route);
}
