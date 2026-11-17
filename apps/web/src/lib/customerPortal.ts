/**
 * Rücklink zum Kundenportal (Front-Proxy von Automato).
 *
 * Hinter dem Front-Proxy läuft Magister unter `<kunde>-um.<domain>`; die
 * Startseite des Kunden mit den Kacheln seiner Werkzeuge liegt unter
 * `<kunde>.<domain>`. Das ist die feste Namensregel des Front-Proxys
 * (Automato ADR 0044 Nachtrag und 0053), keine Einstellung: deshalb reicht der
 * Name, unter dem Magister aufgerufen wird.
 *
 * Nur wenn das erste Label auf `-um` endet und Kurzname und Domain wie im
 * Front-Proxy gültig sind, gibt es eine Adresse; unter jedem anderen Namen
 * (eigene Installation, interne Adresse, `localhost`) `null` – dann zeigt die
 * Kopfzeile keinen Link.
 */

// Kurzname eines Kunden wie im Front-Proxy (DNS-Label, höchstens 42 Zeichen)
const SHORT_NAME = /^[a-z0-9]([a-z0-9-]{0,40}[a-z0-9])?$/;
// Namen, die der Front-Proxy selbst braucht – nie ein Kunde
const RESERVED = new Set(["start", "www", "proxy", "alle", "konfig", "mgmt", "konsole", "connect"]);
// Endungen der Werkzeuge eines Kunden – kein Kurzname endet so
const TOOL_SUFFIXES = ["-nb", "-doc", "-um", "-cmdb"];
const LABEL = /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$/;

export function customerPortalUrl(hostname: string): string | null {
  const host = hostname.trim().toLowerCase().replace(/\.$/, "");
  const [first = "", ...domain] = host.split(".");
  if (!first.endsWith("-um") || domain.length < 2 || !domain.every((l) => LABEL.test(l))) {
    return null;
  }
  const kunde = first.slice(0, -"-um".length);
  if (
    !SHORT_NAME.test(kunde) ||
    RESERVED.has(kunde) ||
    TOOL_SUFFIXES.some((s) => kunde.endsWith(s))
  ) {
    return null;
  }
  return `https://${kunde}.${domain.join(".")}`;
}
