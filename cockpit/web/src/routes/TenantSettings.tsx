import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { getTenant } from "../api/tenants";
import { listSealedSecrets, putSealedSecret, type SealedSecret } from "../api/operations";
import {
  getPlatformSettings,
  getTenantSettings,
  putTenantSettings,
} from "../api/tenantSettings";
import { ErrorBox } from "../components/ErrorBox";
import { LocalAdminSection } from "../components/LocalAdminSection";

type Kind = "text" | "lines" | "number" | "bool";

interface Field {
  key: string;
  label: string;
  kind: Kind;
  hint?: string;
  placeholder?: string;
}

const AD_FIELDS: Field[] = [
  {
    key: "ad_users_search_base",
    label: "Such-Basis Benutzer",
    kind: "text",
    placeholder: "OU=Benutzer,DC=schule,DC=local",
    hint: "Pflicht für den AD-Abgleich. Ohne sie läuft kein Sync.",
  },
  { key: "ad_computers_search_base", label: "Such-Basis Computer", kind: "text" },
  {
    key: "ad_groups_search_base",
    label: "Such-Basis Gruppen",
    kind: "text",
    hint: "Leer = Such-Basis der Benutzer.",
  },
  { key: "ad_ou_teachers", label: "OU Lehrpersonen / Mitarbeitende", kind: "text" },
  { key: "ad_ou_students_other", label: "OU übrige Schüler:innen", kind: "text" },
  {
    key: "ad_groups_teacher",
    label: "Gruppen der Lehrpersonen",
    kind: "lines",
    hint: "Eine DN je Zeile.",
  },
  {
    key: "ad_sync_interval_minutes",
    label: "Abgleich alle … Minuten",
    kind: "number",
    placeholder: "15",
  },
  {
    key: "ad_dcs",
    label: "Domänencontroller",
    kind: "lines",
    hint:
      "Nur für den direkten LDAP-Weg. Über den AD-Connector kennt der Agent die DCs " +
      "selbst — dann leer lassen.",
  },
];

const ACCESS_FIELDS: Field[] = [
  {
    key: "bootstrap_admins",
    label: "Erste Administratoren (UPN)",
    kind: "lines",
    hint:
      "Wer sich mit diesem UPN über Entra anmeldet, ist Admin — so kommt die erste " +
      "Person in eine neue Installation. Ein UPN je Zeile.",
  },
  {
    key: "mail_domains",
    label: "Mail-Domänen",
    kind: "lines",
    hint: "Stehen im Benutzerformular für UPN und Mail zur Auswahl. Eine je Zeile.",
  },
];

const NINJA_FIELDS: Field[] = [
  { key: "ninja_enabled", label: "NinjaOne eingeschaltet", kind: "bool" },
  { key: "ninja_region", label: "Region", kind: "text", placeholder: "eu" },
  { key: "ninja_client_id", label: "Client-Id", kind: "text" },
];

const ALL_FIELDS = [...ACCESS_FIELDS, ...AD_FIELDS, ...NINJA_FIELDS];

const ENTRA_ISSUER = /^https:\/\/login\.microsoftonline\.com\/([0-9a-fA-F-]{36})\/v2\.0\/?$/;

function toText(value: unknown, kind: Kind): string {
  if (value === undefined || value === null) return "";
  if (kind === "lines" && Array.isArray(value)) return value.map(String).join("\n");
  if (kind === "bool") return value ? "true" : "";
  return String(value);
}

function fromText(text: string, kind: Kind): unknown {
  const t = text.trim();
  if (kind === "lines") {
    const lines = t
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean);
    return lines.length ? lines : undefined;
  }
  if (kind === "number") return t ? Number(t) : undefined;
  if (kind === "bool") return t === "true" ? true : undefined;
  return t || undefined;
}

function SecretField({
  tenantId,
  secret,
  label,
}: {
  tenantId: string;
  secret: SealedSecret | undefined;
  label: string;
}) {
  const qc = useQueryClient();
  const [value, setValue] = useState("");
  const m = useMutation({
    mutationFn: () => putSealedSecret(tenantId, secret?.name ?? "", value),
    onSuccess: (data) => {
      setValue("");
      qc.setQueryData(["sealed-secrets", tenantId], data);
    },
  });
  if (!secret) return null;
  const state = !secret.sealed
    ? "nicht gesetzt"
    : secret.key_current === false
      ? "veraltet — die Installation hat einen neuen Schlüssel, bitte neu setzen"
      : secret.present_in_tenant
        ? `gesetzt und bei der Installation angekommen (${secret.updated_by ?? "?"})`
        : "versiegelt — wartet auf den nächsten Abgleich";
  return (
    <div className="space-y-1">
      <span className="block text-sm text-slate-600">{label}</span>
      <p
        className={`text-xs ${secret.key_current === false ? "text-red-700" : "text-slate-500"}`}
      >
        {state}
      </p>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          m.mutate();
        }}
      >
        <input
          type="password"
          autoComplete="off"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={secret.sealed ? "neuen Wert eingeben" : "Wert eingeben"}
          className="w-80 rounded border px-2 py-1 text-sm"
        />
        <button
          type="submit"
          disabled={!value || m.isPending}
          className="rounded border px-3 py-1 text-sm disabled:opacity-50"
        >
          Versiegeln
        </button>
      </form>
      {m.isError && <ErrorBox error={m.error} />}
    </div>
  );
}

/**
 * Systemeinstellungen eines Kunden (ADR-0017, ADR-0024).
 *
 * Gehostet stehen diese Einstellungen nicht mehr im Kundenportal — sie
 * werden hier gepflegt und beim nächsten Abgleich in die Installation
 * geschrieben. Leer heisst: es gilt die Plattform-Vorgabe.
 *
 * Geheimnisse (Entra-Client-Secret, NinjaOne-Secret) werden **versiegelt**:
 * mit dem öffentlichen Schlüssel der Installation verschlüsselt, sodass die
 * Konsole sie danach selbst nicht mehr lesen kann.
 */
export function TenantSettings({ tenantId }: { tenantId: string }) {
  const tenantQ = useQuery({ queryKey: ["tenant", tenantId], queryFn: () => getTenant(tenantId) });
  const settingsQ = useQuery({
    queryKey: ["tenant-settings", tenantId],
    queryFn: () => getTenantSettings(tenantId),
    retry: false,
  });
  const platformQ = useQuery({
    queryKey: ["platform-settings"],
    queryFn: getPlatformSettings,
    retry: false,
  });
  const sealedQ = useQuery({
    queryKey: ["sealed-secrets", tenantId],
    queryFn: () => listSealedSecrets(tenantId),
    retry: false,
  });

  if (settingsQ.isLoading || tenantQ.isLoading) {
    return <p className="text-sm text-slate-500">Lade…</p>;
  }
  if (settingsQ.isError) return <ErrorBox error={settingsQ.error} />;
  if (!settingsQ.data) return null;
  return (
    <div className="space-y-6">
      <LocalAdminSection tenantId={tenantId} />
      <SettingsForm
        // Neu aufbauen, wenn gespeichert wurde: der Formularzustand beginnt
        // dann beim gespeicherten Stand statt ihn per Effekt nachzuziehen.
        key={settingsQ.data.updated_at ?? "neu"}
        tenantId={tenantId}
        overrides={settingsQ.data.overrides}
        hostname={tenantQ.data?.tenant.hostname ?? ""}
        defaults={platformQ.data?.defaults ?? {}}
        sealed={sealedQ.data ?? []}
      />
    </div>
  );
}

function SettingsForm({
  tenantId,
  overrides,
  hostname,
  defaults,
  sealed: sealedList,
}: {
  tenantId: string;
  overrides: Record<string, unknown>;
  hostname: string;
  defaults: Record<string, unknown>;
  sealed: SealedSecret[];
}) {
  const qc = useQueryClient();
  const [form, setForm] = useState<Record<string, string>>(() => {
    const next: Record<string, string> = {};
    for (const f of ALL_FIELDS) next[f.key] = toText(overrides[f.key], f.kind);
    return next;
  });
  const [entraTenant, setEntraTenant] = useState(
    () => ENTRA_ISSUER.exec(String(overrides.oidc_issuer ?? ""))?.[1] ?? "",
  );
  const [clientId, setClientId] = useState(String(overrides.oidc_client_id ?? ""));
  const [scopes, setScopes] = useState(
    Array.isArray(overrides.oidc_scopes) ? overrides.oidc_scopes.join(" ") : "",
  );
  const [saved, setSaved] = useState(false);
  const redirectUri = hostname ? `https://${hostname}/api/auth/callback` : "";

  const saveM = useMutation({
    mutationFn: () => {
      const next: Record<string, unknown> = { ...overrides };
      for (const f of ALL_FIELDS) {
        const value = fromText(form[f.key] ?? "", f.kind);
        if (value === undefined) delete next[f.key];
        else next[f.key] = value;
      }
      const tid = entraTenant.trim();
      if (tid) {
        next.oidc_issuer = `https://login.microsoftonline.com/${tid}/v2.0`;
        next.oidc_redirect_uri = redirectUri;
      } else {
        delete next.oidc_issuer;
        delete next.oidc_redirect_uri;
      }
      if (clientId.trim()) next.oidc_client_id = clientId.trim();
      else delete next.oidc_client_id;
      const scopeList = scopes.split(/[\s,]+/).filter(Boolean);
      if (scopeList.length) next.oidc_scopes = scopeList;
      else delete next.oidc_scopes;
      return putTenantSettings(tenantId, next);
    },
    onSuccess: (data) => {
      qc.setQueryData(["tenant-settings", tenantId], data);
      setSaved(true);
    },
  });

  const sealed = (name: string) => sealedList.find((s) => s.name === name);

  const renderField = (f: Field) => {
    const fallback = defaults[f.key];
    const placeholder =
      fallback !== undefined && fallback !== null && fallback !== ""
        ? `Vorgabe: ${toText(fallback, f.kind).replace(/\n/g, ", ")}`
        : f.placeholder;
    const value = form[f.key] ?? "";
    const set = (v: string) => {
      setForm({ ...form, [f.key]: v });
      setSaved(false);
    };
    return (
      <label key={f.key} className="block text-sm">
        <span className="mb-1 block text-slate-600">{f.label}</span>
        {f.kind === "lines" ? (
          <textarea
            rows={3}
            value={value}
            placeholder={placeholder}
            onChange={(e) => set(e.target.value)}
            className="w-full rounded border px-2 py-1 font-mono text-xs"
          />
        ) : f.kind === "bool" ? (
          <input
            type="checkbox"
            checked={value === "true"}
            onChange={(e) => set(e.target.checked ? "true" : "")}
          />
        ) : (
          <input
            type={f.kind === "number" ? "number" : "text"}
            value={value}
            placeholder={placeholder}
            onChange={(e) => set(e.target.value)}
            className="w-full rounded border px-2 py-1 font-mono text-xs"
          />
        )}
        {f.hint && <span className="mt-0.5 block text-xs text-slate-500">{f.hint}</span>}
      </label>
    );
  };

  return (
    <form
      className="space-y-6"
      onSubmit={(e) => {
        e.preventDefault();
        saveM.mutate();
      }}
    >
      <section className="rounded border bg-white p-4">
        <h2 className="mb-1 font-semibold">Entra ID (Anmeldung)</h2>
        <p className="mb-3 text-xs text-slate-500">
          In Entra eine App-Registrierung für diesen Kunden anlegen (Plattform „Web“), als
          Umleitungs-URI die Adresse unten eintragen und ein Client-Secret erzeugen. Tenant-Id
          und Client-Id stehen auf der Übersichtsseite der App-Registrierung.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="mb-1 block text-slate-600">Verzeichnis-(Tenant-)Id</span>
            <input
              value={entraTenant}
              onChange={(e) => {
                setEntraTenant(e.target.value);
                setSaved(false);
              }}
              placeholder="00000000-0000-0000-0000-000000000000"
              className="w-full rounded border px-2 py-1 font-mono text-xs"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-slate-600">Anwendungs-(Client-)Id</span>
            <input
              value={clientId}
              onChange={(e) => {
                setClientId(e.target.value);
                setSaved(false);
              }}
              placeholder="00000000-0000-0000-0000-000000000000"
              className="w-full rounded border px-2 py-1 font-mono text-xs"
            />
          </label>
          <div className="text-sm">
            <span className="mb-1 block text-slate-600">Umleitungs-URI (in Entra eintragen)</span>
            <code className="block rounded bg-slate-100 px-2 py-1 font-mono text-xs">
              {redirectUri || "—"}
            </code>
          </div>
          <label className="block text-sm">
            <span className="mb-1 block text-slate-600">Scopes</span>
            <input
              value={scopes}
              onChange={(e) => {
                setScopes(e.target.value);
                setSaved(false);
              }}
              placeholder="openid profile email"
              className="w-full rounded border px-2 py-1 font-mono text-xs"
            />
          </label>
        </div>
        <div className="mt-3">
          <SecretField
            tenantId={tenantId}
            secret={sealed("oidc_client_secret")}
            label="Client-Secret"
          />
        </div>
      </section>

      <section className="rounded border bg-white p-4">
        <h2 className="mb-3 font-semibold">Zugang</h2>
        <div className="grid gap-3 sm:grid-cols-2">{ACCESS_FIELDS.map(renderField)}</div>
      </section>

      <section className="rounded border bg-white p-4">
        <h2 className="mb-3 font-semibold">Active Directory</h2>
        <div className="grid gap-3 sm:grid-cols-2">{AD_FIELDS.map(renderField)}</div>
      </section>

      <section className="rounded border bg-white p-4">
        <h2 className="mb-3 font-semibold">NinjaOne (optional)</h2>
        <div className="grid gap-3 sm:grid-cols-3">{NINJA_FIELDS.map(renderField)}</div>
        <div className="mt-3">
          <SecretField
            tenantId={tenantId}
            secret={sealed("ninja_client_secret")}
            label="Client-Secret"
          />
        </div>
      </section>

      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={saveM.isPending}
          className="rounded bg-slate-900 px-4 py-1.5 text-sm text-white disabled:opacity-50"
        >
          {saveM.isPending ? "Speichert…" : "Einstellungen speichern"}
        </button>
        {saved && (
          <span className="text-sm text-emerald-700">
            Gespeichert. Die Installation übernimmt es beim nächsten Abgleich (Übersicht →
            Zustand).
          </span>
        )}
      </div>
      {saveM.isError && <ErrorBox error={saveM.error} />}
    </form>
  );
}
