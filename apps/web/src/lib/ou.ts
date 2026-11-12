// Ziel-OU (Distinguished Name) prüfen — dieselben Regeln wie im Backend
// (schemas/group_templates.py, ad/ou.py).

/** Ein DN unterhalb einer Domäne, z. B. OU=Sonstige,OU=KÜRZEL,DC=schule,DC=local. */
export const OU_DN_RE = /^(OU|CN)=[^,]+(,(OU|CN)=[^,]+)*(,DC=[^,]+)+$/i;

/** Leerzeichen um die Kommas entfernen, wie das Backend es tut. */
export function cleanOu(ou: string): string {
  return ou
    .split(",")
    .map((p) => p.trim())
    .join(",")
    .trim();
}

/** Leer ist erlaubt; sonst muss es ein vollständiger Pfad sein. */
export function ouValid(ou: string): boolean {
  const c = cleanOu(ou);
  return c === "" || OU_DN_RE.test(c);
}

/**
 * Liegt die OU im Standort? Regel des AD-Abgleichs: OU=<Kürzel> kommt im Pfad
 * vor. Sonst ordnet er das Konto keinem Standort zu.
 */
export function ouInUnit(ou: string, scopeShort: string): boolean {
  return cleanOu(ou).toUpperCase().includes(`OU=${scopeShort.toUpperCase()}`);
}
