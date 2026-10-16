import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  getConnectorSettings,
  putConnectorSettings,
  type ConnectorSettings,
} from "../api/agents";
import { ErrorBox } from "./ErrorBox";

function lines(text: string): string[] {
  return text
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l !== "");
}

/**
 * OU-Freigabe und zusätzliche geschützte Gruppen des AD-Connectors.
 *
 * Seit der Agent auf dem Domänencontroller läuft, steht auf dem DC nur noch
 * der Weg zur Plattform; alles andere wird hier gepflegt und vom Agenten
 * geholt (höchstens fünf Minuten). Die ganze Domäne, Domain Controllers,
 * Builtin, System … lehnt die Konsole ab — und der Agent noch einmal selbst.
 * Die eingebauten geschützten Gruppen (Domänen-Admins und Verwandte) und
 * Konten mit adminCount=1 bleiben immer gesperrt; hier kommen nur weitere
 * dazu.
 */
export function ConnectorSettingsSection({ tenantId }: { tenantId: string }) {
  const q = useQuery({
    queryKey: ["connector-settings", tenantId],
    queryFn: () => getConnectorSettings(tenantId),
    retry: false,
  });

  return (
    <section className="rounded border bg-white p-4">
      <h2 className="mb-1 font-semibold">Freigabe im AD</h2>
      <p className="mb-3 text-sm text-slate-600">
        Wo der Agent auf dem Domänencontroller arbeiten darf. Er holt diese
        Angaben selbst (spätestens nach fünf Minuten); auf dem DC wird nichts
        eingestellt. Domänencontroller und Suchbasen stehen unter Einstellungen
        → Active Directory.
      </p>
      {q.isError && <ErrorBox error={q.error} />}
      {q.data && (
        // Neu aufgebaut, wenn eine andere Fassung kommt — statt die Felder in
        // einem Effekt nachzuziehen.
        <SettingsForm
          key={q.data.updated_at ?? "neu"}
          tenantId={tenantId}
          initial={q.data}
        />
      )}
    </section>
  );
}

function SettingsForm({
  tenantId,
  initial,
}: {
  tenantId: string;
  initial: ConnectorSettings;
}) {
  const qc = useQueryClient();
  const [ous, setOus] = useState(initial.allowed_ous.join("\n"));
  const [groups, setGroups] = useState(initial.protected_groups.join("\n"));

  const m = useMutation({
    mutationFn: () =>
      putConnectorSettings(tenantId, {
        allowed_ous: lines(ous),
        protected_groups: lines(groups),
      }),
    onSuccess: (data) => {
      qc.setQueryData(["connector-settings", tenantId], data);
    },
  });

  return (
    <form
      className="grid max-w-3xl gap-3 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        m.mutate();
      }}
    >
      <label className="grid gap-1">
        <span className="font-medium">Freigegebene OUs</span>
        <textarea
          className="min-h-28 rounded border px-2 py-1 font-mono text-xs"
          value={ous}
          onChange={(e) => setOus(e.target.value)}
          placeholder={
            "OU=Schueler,OU=Magister,DC=gemeinde,DC=local\nOU=Lehrer,OU=Magister,DC=gemeinde,DC=local"
          }
        />
        <span className="text-xs text-slate-500">
          Eine OU je Zeile, als Distinguished Name. Leer heisst: keine
          Verzeichnisaufträge — nicht „alles“. Nicht zulässig: die ganze Domäne,
          Domain Controllers, Builtin, System, Configuration. Für den Abgleich
          gehören auch die OUs der Gruppen und Computer hierher. Liegt eine
          Such-Basis darüber (etwa die ganze Domäne), liest der Agent nur die
          freigegebenen OUs darunter.
        </span>
      </label>
      <label className="grid gap-1">
        <span className="font-medium">Weitere geschützte Gruppen</span>
        <textarea
          className="min-h-16 rounded border px-2 py-1 font-mono text-xs"
          value={groups}
          onChange={(e) => setGroups(e.target.value)}
          placeholder="Schulleitung"
        />
        <span className="text-xs text-slate-500">
          Gruppenname (CN) je Zeile. Kommt zur eingebauten Liste dazu
          (Domänen-Admins, Administratoren, Organisations-Admins …), ersetzt sie
          nicht. Konten mit adminCount=1 fasst der Agent nie an.
        </span>
      </label>
      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={m.isPending}
          className="rounded bg-slate-900 px-3 py-1 text-white disabled:opacity-50"
        >
          Speichern
        </button>
        {initial.updated_at && (
          <span className="text-xs text-slate-500">
            Zuletzt {new Date(initial.updated_at).toLocaleString()} ·{" "}
            {initial.updated_by}
          </span>
        )}
      </div>
      {m.isError && <ErrorBox error={m.error} />}
    </form>
  );
}
