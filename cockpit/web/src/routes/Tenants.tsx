import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { createTenant, listTenants, type Tenant, type TenantCreate } from "../api/tenants";
import { StatusBadge } from "../components/Badge";
import { ErrorBox } from "../components/ErrorBox";
import { SecretOnce } from "../components/SecretOnce";
import { go } from "../lib/nav";

const EMPTY: TenantCreate = {
  slug: "",
  name: "",
  hostname: "",
  customer_no: "",
  profile: "school",
  isolation_mode: "schema",
};

interface PendingSecrets {
  tenantId: string;
  ref: string;
  role?: string;
  key?: string;
}

function NewTenantForm({ onDone }: { onDone: () => void }) {
  const [form, setForm] = useState<TenantCreate>(EMPTY);
  const [secrets, setSecrets] = useState<PendingSecrets | null>(null);
  const qc = useQueryClient();

  const createM = useMutation({
    mutationFn: () =>
      createTenant({
        ...form,
        customer_no: form.customer_no?.trim() ? form.customer_no.trim() : null,
      }),
    onSuccess: (result) => {
      void qc.invalidateQueries({ queryKey: ["tenants"] });
      // Die zwei Geheimnisse bleiben stehen, bis sie bestätigt sind — erst
      // danach springt die Ansicht auf den Kunden. Umgekehrt wäre der
      // Kundenschlüssel weg, bevor jemand ihn gesehen hat.
      if (result.role_password || result.data_key) {
        setSecrets({
          tenantId: result.tenant.id,
          ref: result.tenant.slug.toUpperCase(),
          role: result.role_password ?? undefined,
          key: result.data_key ?? undefined,
        });
      } else {
        go({ view: "tenant", id: result.tenant.id, tab: "uebersicht" });
        onDone();
      }
    },
  });

  // Sobald das letzte Geheimnis bestätigt ist, springt die Ansicht zum Kunden.
  // Kein „Fertig"-Knopf: er wäre entweder überflüssig oder — wie im ersten
  // Entwurf — dauerhaft ausgegraut.
  function acknowledge(which: "role" | "key") {
    setSecrets((current) => {
      if (!current) return null;
      const next = { ...current, [which]: undefined };
      if (!next.role && !next.key) {
        go({ view: "tenant", id: current.tenantId, tab: "uebersicht" });
        onDone();
        return null;
      }
      return next;
    });
  }

  if (secrets) {
    return (
      <div className="mb-6 rounded border bg-white p-4">
        <h2 className="mb-3 text-lg font-semibold">Kunde angelegt</h2>
        <p className="mb-3 text-sm text-slate-600">
          Diese Werte kommen genau einmal. Beide bestätigen — danach geht es zum
          Kunden.
        </p>
        {secrets.role && (
          <SecretOnce
            label="Rollenpasswort"
            value={secrets.role}
            destination="Passwortspeicher; die Datenebene löst es über dsn_ref auf"
            consequence="Verloren ist kein Schaden — es lässt sich neu setzen (Rollenpasswort drehen)."
            onAcknowledged={() => acknowledge("role")}
          />
        )}
        {secrets.key && (
          <SecretOnce
            label="Kundenschlüssel"
            value={secrets.key}
            destination={`Umgebung des Anwendungsservers als MAGISTER_TENANT_AUDIT_KEY_${secrets.ref}`}
            consequence="Verloren ist teuer: damit sind die Audit-Payloads und gespeicherten Passwörter dieses Kunden verschlüsselt. Ein Wechsel verlangt eine Umschlüsselung aller Zeilen, kein Neusetzen. Bis der Wert gesetzt ist, antwortet der Mandant mit 503."
            onAcknowledged={() => acknowledge("key")}
          />
        )}
      </div>
    );
  }

  return (
    <form
      className="mb-6 rounded border bg-white p-4"
      onSubmit={(e) => {
        e.preventDefault();
        createM.mutate();
      }}
    >
      <h2 className="mb-3 text-lg font-semibold">Kunde erfassen</h2>
      <div className="mb-3 grid grid-cols-2 gap-3 text-sm">
        <label className="block">
          <span className="mb-1 block text-slate-600">Kürzel (slug)</span>
          <input
            required
            value={form.slug}
            onChange={(e) => setForm({ ...form, slug: e.target.value })}
            placeholder="bern_west"
            className="w-full rounded border px-2 py-1 font-mono"
          />
          <span className="mt-1 block text-xs text-slate-500">
            Aus dem Kürzel werden Schema- und Rollenname. Kleinbuchstaben, Ziffern und
            Unterstrich, 2–31 Zeichen, beginnt mit einem Buchstaben.
          </span>
        </label>
        <label className="block">
          <span className="mb-1 block text-slate-600">Name</span>
          <input
            required
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="Gemeinde Bern West"
            className="w-full rounded border px-2 py-1"
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-slate-600">Hostname</span>
          <input
            required
            value={form.hostname}
            onChange={(e) => setForm({ ...form, hostname: e.target.value })}
            placeholder="bern-west.magister.ch"
            className="w-full rounded border px-2 py-1 font-mono"
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-slate-600">Kundennummer (optional)</span>
          <input
            value={form.customer_no ?? ""}
            onChange={(e) => setForm({ ...form, customer_no: e.target.value })}
            className="w-full rounded border px-2 py-1"
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-slate-600">Profil</span>
          <select
            value={form.profile}
            onChange={(e) =>
              setForm({ ...form, profile: e.target.value as TenantCreate["profile"] })
            }
            className="w-full rounded border px-2 py-1"
          >
            <option value="school">Schule</option>
            <option value="municipality">Gemeinde</option>
            <option value="demo">Demo</option>
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-slate-600">Trennung</span>
          <select
            value={form.isolation_mode}
            onChange={(e) =>
              setForm({
                ...form,
                isolation_mode: e.target.value as TenantCreate["isolation_mode"],
              })
            }
            className="w-full rounded border px-2 py-1"
          >
            <option value="schema">eigenes Schema</option>
            <option value="database">eigene Datenbank</option>
            <option value="cluster">eigener Cluster</option>
          </select>
        </label>
      </div>

      {createM.isError && <ErrorBox error={createM.error} />}

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={createM.isPending}
          className="rounded bg-slate-900 px-3 py-1 text-sm text-white disabled:opacity-50"
        >
          {createM.isPending ? "Wird bereitgestellt…" : "Anlegen und bereitstellen"}
        </button>
        <button type="button" onClick={onDone} className="rounded border px-3 py-1 text-sm">
          Abbrechen
        </button>
      </div>
    </form>
  );
}

export function Tenants() {
  const [showForm, setShowForm] = useState(false);
  const tenantsQ = useQuery({
    queryKey: ["tenants"],
    queryFn: listTenants,
    retry: false,
    refetchInterval: 30_000,
  });

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Kunden</h1>
        {!showForm && (
          <button
            type="button"
            onClick={() => setShowForm(true)}
            className="rounded bg-slate-900 px-3 py-1 text-sm text-white"
          >
            Kunde erfassen
          </button>
        )}
      </div>

      {showForm && <NewTenantForm onDone={() => setShowForm(false)} />}

      {tenantsQ.isLoading && <p className="text-sm text-slate-500">Lade…</p>}
      {tenantsQ.isError && <ErrorBox error={tenantsQ.error} />}

      {tenantsQ.data && (
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b bg-slate-100 text-left">
              <th className="p-2">Kunde</th>
              <th className="p-2">Hostname</th>
              <th className="p-2">Zustand</th>
              <th className="p-2">Schema</th>
              <th className="p-2">Stand</th>
              <th className="p-2">Schlüssel-Id</th>
            </tr>
          </thead>
          <tbody>
            {tenantsQ.data.map((t: Tenant) => (
              <tr
                key={t.id}
                className="cursor-pointer border-b hover:bg-slate-50"
                onClick={() => go({ view: "tenant", id: t.id, tab: "uebersicht" })}
              >
                <td className="p-2">
                  <span className="font-medium">{t.name}</span>{" "}
                  <span className="font-mono text-xs text-slate-500">{t.slug}</span>
                  {t.customer_no && (
                    <span className="ml-2 text-xs text-slate-400">#{t.customer_no}</span>
                  )}
                </td>
                <td className="p-2 font-mono text-xs">{t.hostname}</td>
                <td className="p-2">
                  <StatusBadge status={t.status} />
                  {t.suspended_reason && (
                    <span className="ml-2 text-xs text-slate-500">{t.suspended_reason}</span>
                  )}
                </td>
                <td className="p-2 font-mono text-xs">{t.schema_name}</td>
                <td className="p-2 font-mono text-xs">{t.schema_version ?? "—"}</td>
                <td className="p-2 font-mono text-xs">{t.audit_key_id ?? "—"}</td>
              </tr>
            ))}
            {tenantsQ.data.length === 0 && (
              <tr>
                <td colSpan={6} className="p-6 text-center text-slate-500">
                  Kein Kunde erfasst.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
