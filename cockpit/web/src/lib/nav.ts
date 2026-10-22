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
  | { view: "platform" }
  | { view: "settings" }
  | { view: "tenants" }
  | { view: "tenant"; id: string; tab: TenantTab };

export type TenantTab =
  | "uebersicht"
  | "einstellungen"
  | "module"
  | "sicherungen"
  | "connector"
  | "zugriff"
  | "offboarding";

const TENANT_TABS: readonly TenantTab[] = [
  "uebersicht",
  "einstellungen",
  "module",
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
  if (parts[0] === "platform") return { view: "platform" };
  if (parts[0] === "settings") return { view: "settings" };
  // Vorgabe: die Kundenliste. Die Konsole ist für Kunden da; die Instanzen
  // sind der ältere Zweck und stehen jetzt daneben.
  return { view: "tenants" };
}

/**
 * Offene Einmal-Geheimnisse (Rollenpasswort, Kundenschlüssel).
 *
 * Solange eines angezeigt und nicht bestätigt ist, fragt jeder Ansichtswechsel
 * nach — ein Klick in die Seitenleiste, auf einen Reiter oder „Zurück“ —, und
 * Neuladen oder Schliessen des Tabs ebenso. Ohne das war ein Kundenschlüssel
 * mit einem einzigen Fehlklick weg (Prod, 2026-10-15).
 */
let heldSecrets = 0;

const LEAVE_MESSAGE =
  "Ein Wert, der nur einmal angezeigt wird, ist noch nicht bestätigt.\n\n" +
  "Verlassen Sie die Seite jetzt, ist er nicht mehr abrufbar. Trotzdem verlassen?";

function onBeforeUnload(event: BeforeUnloadEvent) {
  event.preventDefault();
  // Ältere Browser zeigen den Dialog nur mit gesetztem returnValue.
  event.returnValue = "";
}

/** Meldet ein offenes Geheimnis an; die Rückgabe gibt es wieder frei (mehrfach aufrufbar). */
export function holdSecret(): () => void {
  heldSecrets += 1;
  if (heldSecrets === 1) window.addEventListener("beforeunload", onBeforeUnload);
  let released = false;
  return () => {
    if (released) return;
    released = true;
    heldSecrets -= 1;
    if (heldSecrets === 0) window.removeEventListener("beforeunload", onBeforeUnload);
  };
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));
  useEffect(() => {
    let current = window.location.hash;
    const onChange = () => {
      const next = window.location.hash;
      if (next === current) return;
      if (heldSecrets > 0 && !window.confirm(LEAVE_MESSAGE)) {
        // Zurück auf die alte Adresse, ohne neues hashchange auszulösen.
        window.history.replaceState(
          null,
          "",
          current || window.location.pathname + window.location.search,
        );
        return;
      }
      current = next;
      setRoute(parseHash(next));
    };
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
    case "platform":
      return "#/platform";
    case "settings":
      return "#/settings";
    case "tenants":
      return "#/tenants";
    case "tenant":
      return `#/tenants/${route.id}/${route.tab}`;
  }
}

export function go(route: Route): void {
  window.location.hash = href(route);
}
