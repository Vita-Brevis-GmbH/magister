import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  getTenant,
  resumeProvisioning,
  rotateRolePassword,
  suspendTenant,
  unsuspendTenant,
  type Tenant,
} from "../api/tenants";
import { StatusBadge } from "../components/Badge";
import { ErrorBox } from "../components/ErrorBox";
import { ProvisioningLog } from "../components/ProvisioningLog";
import { SecretOnce } from "../components/SecretOnce";
import { go, href, type TenantTab } from "../lib/nav";
import { TenantBackups } from "./TenantBackups";
import { TenantConnector } from "./TenantConnector";
import { TenantOperatorAccess } from "./TenantOperatorAccess";
import { TenantOffboarding } from "./TenantOffboarding";

const TABS: { id: TenantTab; label: string }[] = [
  { id: "uebersicht", label: "Übersicht" },
  { id: "sicherungen", label: "Sicherungen" },
  { id: "connector", label: "AD-Connector" },
  { id: "zugriff", label: "Zugriff" },
  { id: "offboarding", label: "Kündigung" },
];

function Facts({ tenant }: { tenant: Tenant }) {
  const rows: [string, string][] = [
    ["Kürzel", tenant.slug],
    ["Hostname", tenant.hostname],
    ["Kundennummer", tenant.customer_no ?? "—"],
    ["Profil", tenant.profile],
    ["Trennung", tenant.isolation_mode],
    ["Schema", tenant.schema_name],
    ["Anmelderolle", tenant.db_role],
    // Ein Verweis, kein DSN. Was hier steht, gibt niemandem Datenbankzugang
    // (ADR-0013 D4) — die Datenebene löst ihn aus ihrem eigenen
    // Geheimnisspeicher auf.
    ["DSN-Verweis", tenant.dsn_ref],
    ["Schema-Stand", tenant.schema_version ?? "unbekannt"],
    ["Schlüssel-Id", tenant.audit_key_id ?? "—"],
    ["Angelegt", new Date(tenant.created_at).toLocaleString()],
  ];
  return (
    <dl className="grid grid-cols-[10rem_1fr] gap-x-4 gap-y-1 text-sm">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-slate-500">{label}</dt>
          <dd className="font-mono text-xs">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Overview({ tenantId }: { tenantId: string }) {
  const qc = useQueryClient();
  const [suspendReason, setSuspendReason] = useState("");
  const [newRolePassword, setNewRolePassword] = useState<string | null>(null);

  const detailQ = useQuery({
    queryKey: ["tenant", tenantId],
    queryFn: () => getTenant(tenantId),
    retry: false,
  });

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["tenant", tenantId] });
    void qc.invalidateQueries({ queryKey: ["tenants"] });
  };

  const resumeM = useMutation({ mutationFn: () => resumeProvisioning(tenantId), onSuccess: invalidate });
  const suspendM = useMutation({
    mutationFn: () => suspendTenant(tenantId, suspendReason),
    onSuccess: () => {
      setSuspendReason("");
      invalidate();
    },
  });
  const unsuspendM = useMutation({ mutationFn: () => unsuspendTenant(tenantId), onSuccess: invalidate });
  const rotateM = useMutation({
    mutationFn: () => rotateRolePassword(tenantId),
    onSuccess: (result) => {
      setNewRolePassword(result.role_password);
      invalidate();
    },
  });

  if (detailQ.isLoading) return <p className="text-sm text-slate-500">Lade…</p>;
  if (detailQ.isError) return <ErrorBox error={detailQ.error} />;
  if (!detailQ.data) return null;

  const { tenant, job, next_step } = detailQ.data;
  const suspended = tenant.status === "suspended";

  return (
    <div className="space-y-6">
      {newRolePassword && (
        <SecretOnce
          label="Neues Rollenpasswort"
          value={newRolePassword}
          destination="Passwortspeicher; danach die Datenebene neu starten"
          consequence="Bis der neue Wert dort liegt, kommt die Datenebene nicht mehr an dieses Schema — der Kunde antwortet mit einem Fehler."
          onAcknowledged={() => setNewRolePassword(null)}
        />
      )}

      <section className="rounded border bg-white p-4">
        <h2 className="mb-3 font-semibold">Stammdaten</h2>
        <Facts tenant={tenant} />
      </section>

      <section className="rounded border bg-white p-4">
        <ProvisioningLog job={job} nextStep={next_step} />
        {next_step && (
          <div className="mt-3">
            <button
              type="button"
              onClick={() => resumeM.mutate()}
              disabled={resumeM.isPending}
              className="rounded bg-amber-600 px-3 py-1 text-sm text-white disabled:opacity-50"
            >
              {resumeM.isPending ? "Läuft…" : `Weiter ab „${next_step}“`}
            </button>
            <p className="mt-1 text-xs text-slate-500">
              Macht ab der Abbruchstelle weiter, nicht von vorn. Jeder Schritt ist
              idempotent — ein zweiter Lauf über einen bereits geglückten Schritt
              schadet nicht.
            </p>
          </div>
        )}
        {resumeM.isError && <div className="mt-3">
          <ErrorBox error={resumeM.error} />
        </div>}
      </section>

      <section className="rounded border bg-white p-4">
        <h2 className="mb-3 font-semibold">Bedienung</h2>
        {suspended ? (
          <div>
            <p className="mb-2 text-sm">
              Gesperrt seit{" "}
              {tenant.suspended_at ? new Date(tenant.suspended_at).toLocaleString() : "—"}
              {tenant.suspended_reason && <>: „{tenant.suspended_reason}“</>}
            </p>
            <button
              type="button"
              onClick={() => unsuspendM.mutate()}
              disabled={unsuspendM.isPending}
              className="rounded bg-slate-900 px-3 py-1 text-sm text-white disabled:opacity-50"
            >
              Entsperren
            </button>
            {unsuspendM.isError && <div className="mt-3"><ErrorBox error={unsuspendM.error} /></div>}
          </div>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              suspendM.mutate();
            }}
          >
            <label className="mb-2 block text-sm">
              <span className="mb-1 block text-slate-600">Begründung (Pflicht)</span>
              <input
                required
                minLength={3}
                value={suspendReason}
                onChange={(e) => setSuspendReason(e.target.value)}
                placeholder="Zahlungsverzug, Ticket 1234"
                className="w-full rounded border px-2 py-1"
              />
            </label>
            <p className="mb-2 text-xs text-slate-500">
              Sperren ist eine Aussage über die Bedienung, nicht über den Bestand:
              Rolle, Schema und Daten bleiben stehen. Sonst wäre Entsperren eine
              Wiederherstellung.
            </p>
            <button
              type="submit"
              disabled={suspendM.isPending}
              className="rounded border border-amber-500 px-3 py-1 text-sm text-amber-800 disabled:opacity-50"
            >
              Sperren
            </button>
            {suspendM.isError && <div className="mt-3"><ErrorBox error={suspendM.error} /></div>}
          </form>
        )}
      </section>

      <section className="rounded border bg-white p-4">
        <h2 className="mb-2 font-semibold">Rollenpasswort drehen</h2>
        <p className="mb-2 text-xs text-slate-500">
          Setzt ein neues Passwort für die Anmelderolle und zeigt es genau einmal.
          Der Kundenschlüssel bleibt davon unberührt — der lässt sich nicht drehen,
          nur umschlüsseln.
        </p>
        <button
          type="button"
          onClick={() => rotateM.mutate()}
          disabled={rotateM.isPending}
          className="rounded border px-3 py-1 text-sm disabled:opacity-50"
        >
          {rotateM.isPending ? "Läuft…" : "Neues Rollenpasswort"}
        </button>
        {rotateM.isError && <div className="mt-3"><ErrorBox error={rotateM.error} /></div>}
      </section>
    </div>
  );
}

export function TenantDetail({ tenantId, tab }: { tenantId: string; tab: TenantTab }) {
  // Nur für Kopfzeile und Titel — die Ansichten holen sich, was sie brauchen.
  const headQ = useQuery({
    queryKey: ["tenant", tenantId],
    queryFn: () => getTenant(tenantId),
    retry: false,
  });
  const tenant = headQ.data?.tenant;

  return (
    <div>
      <div className="mb-4">
        <a href={href({ view: "tenants" })} className="text-sm text-slate-500 hover:underline">
          ← Kunden
        </a>
      </div>

      <div className="mb-4 flex items-baseline gap-3">
        <h1 className="text-xl font-semibold">{tenant?.name ?? tenantId}</h1>
        {tenant && <span className="font-mono text-sm text-slate-500">{tenant.slug}</span>}
        {tenant && <StatusBadge status={tenant.status} />}
      </div>

      <nav className="mb-6 flex gap-1 border-b">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => go({ view: "tenant", id: tenantId, tab: t.id })}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${
              t.id === tab
                ? "border-slate-900 font-medium"
                : "border-transparent text-slate-500 hover:text-slate-800"
            }`}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {tab === "uebersicht" && <Overview tenantId={tenantId} />}
      {tab === "sicherungen" && <TenantBackups tenantId={tenantId} />}
      {tab === "connector" && <TenantConnector tenantId={tenantId} />}
      {tab === "zugriff" && <TenantOperatorAccess tenantId={tenantId} />}
      {tab === "offboarding" && (
        <TenantOffboarding tenantId={tenantId} tenantSlug={tenant?.slug ?? ""} />
      )}
    </div>
  );
}
