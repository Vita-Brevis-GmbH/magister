import { ApiError, authHeaders, get } from "./client";

/**
 * Ein gebautes Paket des Connector-Agenten (ADR-0014).
 *
 * `sha256` kommt aus derselben Quelle wie die Datei — die Konsole rechnet die
 * Prüfsumme beim Auflisten über den Inhalt. Sie beantwortet „ist die Datei
 * heil angekommen?", nicht „kommt sie von Vita Brevis": das sagt die
 * Paketsignatur (Entscheid E18).
 */
export interface AgentPackage {
  filename: string;
  size_bytes: number;
  sha256: string;
  modified_at: string;
}

export function listAgentPackages(): Promise<AgentPackage[]> {
  return get("/api/agent-packages");
}

/**
 * Ein Paket herunterladen.
 *
 * Wie beim Export geht ein einfacher `<a href>` nicht: der Endpunkt hängt am
 * `Authorization`-Header, und eine Navigation des Browsers schickt keinen mit
 * — sie endete in einem 401, das wie ein fehlendes Paket aussieht.
 */
export async function downloadAgentPackage(filename: string): Promise<void> {
  const response = await fetch(`/api/agent-packages/${encodeURIComponent(filename)}`, {
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new ApiError(response.status, (await response.text()).slice(0, 500));
  }
  const url = URL.createObjectURL(await response.blob());
  try {
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** Grösse in der Einheit, die ein Mensch liest. */
export function readableSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

/** Windows, Debian oder unbekannt — nach der Endung, mehr weiss die API nicht. */
export function platformOf(filename: string): string {
  const lower = filename.toLowerCase();
  if (lower.endsWith(".msi") || lower.endsWith(".exe")) return "Windows";
  if (lower.endsWith(".deb")) return "Debian/Ubuntu";
  return "—";
}

/** Ein Betriebssystem mit seinem aktuellen Paket — und dem, was davor kam. */
export interface PlattformGruppe {
  plattform: string;
  aktuell: AgentPackage;
  aeltere: AgentPackage[];
}

/** Reihenfolge der Gruppen. Was nicht drinsteht, kommt hinten nach Namen. */
const PLATTFORM_ORDNUNG = ["Windows", "Debian/Ubuntu"];

/**
 * Die Pakete nach Betriebssystem bündeln, je Gruppe das neueste zuerst.
 *
 * Warum überhaupt: das Paketverzeichnis sammelt jeden CI-Lauf an. Nach einer
 * Woche standen dort sieben Dateien in einer flachen Liste, und wer den Agenten
 * installieren will, muss raten, welche die richtige ist. Die Frage beim
 * Onboarding lautet „welches Paket für diesen Server?" — also wird genau das
 * beantwortet, und die älteren Stände bleiben erreichbar, statt zu
 * verschwinden: ein Rückschritt auf die vorige Fassung ist ein legitimer
 * Schritt, wenn eine neue beim Kunden Ärger macht.
 *
 * Aussortiert wird nichts. Das Löschen alter Pakete gehört auf den Server
 * (Aufbewahrung im Aufbau-Skript), nicht in eine Oberfläche, die sie nur
 * anzeigt.
 */
export function nachPlattform(pakete: AgentPackage[]): PlattformGruppe[] {
  const gruppen = new Map<string, AgentPackage[]>();
  for (const paket of pakete) {
    const schluessel = platformOf(paket.filename);
    const liste = gruppen.get(schluessel);
    if (liste) liste.push(paket);
    else gruppen.set(schluessel, [paket]);
  }

  const aus: PlattformGruppe[] = [];
  for (const [plattform, liste] of gruppen) {
    // Nach Zeit, neueste zuerst. Bei gleichem Zeitstempel — zwei Dateien aus
    // demselben CI-Lauf — entscheidet der Name absteigend, damit die höhere
    // Version oben steht und die Reihenfolge überhaupt eindeutig ist.
    const sortiert = [...liste].sort((a, b) => {
      const zeit = Date.parse(b.modified_at) - Date.parse(a.modified_at);
      return zeit !== 0 ? zeit : b.filename.localeCompare(a.filename);
    });
    aus.push({ plattform, aktuell: sortiert[0], aeltere: sortiert.slice(1) });
  }

  return aus.sort((a, b) => {
    const ra = PLATTFORM_ORDNUNG.indexOf(a.plattform);
    const rb = PLATTFORM_ORDNUNG.indexOf(b.plattform);
    if (ra !== rb) return (ra < 0 ? PLATTFORM_ORDNUNG.length : ra) - (rb < 0 ? PLATTFORM_ORDNUNG.length : rb);
    return a.plattform.localeCompare(b.plattform);
  });
}
