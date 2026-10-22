import { PlatformMailSection } from "../components/PlatformMailSection";

/**
 * Einstellungen der Plattform — Vorgaben für alle Kunden.
 *
 * Getrennt vom Reiter „Plattform“: dort steht der Betrieb (Neustart,
 * Update, Sicherungen), hier, was für jeden Kunden gilt, solange er nichts
 * Eigenes hat. Abweichungen eines Kunden stehen bei ihm unter Einstellungen.
 */
export function PlatformSettings() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Einstellungen</h1>
        <p className="text-sm text-slate-500">
          Standards für alle Kunden. Ein Kunde mit eigener Einstellung (Kunde →
          Einstellungen) verwendet seine eigene.
        </p>
      </div>
      <PlatformMailSection />
    </div>
  );
}
