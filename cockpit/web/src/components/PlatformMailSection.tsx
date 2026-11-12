import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  deletePlatformSecret,
  getPlatformSettings,
  listPlatformSecrets,
  putPlatformDefaults,
  putPlatformSecret,
} from "../api/tenantSettings";
import { ErrorBox } from "./ErrorBox";
import { MailTestBox } from "./MailTestBox";

/** Felder des Standard-Mailversands — dieselben Namen wie in der Datenebene. */
const TEXT_KEYS = [
  ["mail_from", "Absenderadresse", "noreply@vitabrevis.ch"],
  ["mail_from_name", "Absendername", "Magister"],
  ["graph_tenant_id", "Entra-Mandanten-Id (Graph)", ""],
  ["graph_client_id", "Anwendungs-Id (Graph)", ""],
  ["smtp_host", "SMTP-Server", ""],
  ["smtp_username", "SMTP-Benutzername (leer = ohne Anmeldung)", ""],
] as const;

/**
 * Der Standard-Mailversand für alle Kunden ohne eigene Anbindung.
 *
 * Die Felder sind Plattform-Vorgaben; das Geheimnis (Graph-Client-Secret
 * bzw. SMTP-Passwort) wird mit dem Plattform-Schlüssel der Datenebene
 * versiegelt — die Konsole kann es danach selbst nicht lesen. Setzt ein
 * Kunde auch nur ein Feld der Anbindung selbst, gilt für ihn seine ganze
 * eigene Anbindung, und dieses Geheimnis geht nicht an ihn.
 */
export function PlatformMailSection() {
  const qc = useQueryClient();
  const settingsQ = useQuery({ queryKey: ["platform-settings"], queryFn: getPlatformSettings });
  const secretsQ = useQuery({
    queryKey: ["platform-secrets"],
    queryFn: listPlatformSecrets,
    retry: false,
  });

  if (settingsQ.isLoading) return <p className="text-sm text-slate-500">Lade…</p>;
  if (settingsQ.isError) return <ErrorBox error={settingsQ.error} />;
  if (!settingsQ.data) return null;
  return (
    <MailForm
      key={settingsQ.data.updated_at}
      defaults={settingsQ.data.defaults}
      onSaved={() => qc.invalidateQueries({ queryKey: ["platform-settings"] })}
      secrets={secretsQ.data}
      secretsError={secretsQ.error}
    />
  );
}

function MailForm({
  defaults,
  onSaved,
  secrets,
  secretsError,
}: {
  defaults: Record<string, unknown>;
  onSaved: () => void;
  secrets: Awaited<ReturnType<typeof listPlatformSecrets>> | undefined;
  secretsError: unknown;
}) {
  const qc = useQueryClient();
  const text = (k: string) => (defaults[k] == null ? "" : String(defaults[k]));
  const [form, setForm] = useState<Record<string, string>>(() => ({
    mail_transport: text("mail_transport") || "off",
    smtp_port: defaults.smtp_port ? String(defaults.smtp_port) : "",
    smtp_security: text("smtp_security") || "starttls",
    expiry_notice_days: Array.isArray(defaults.expiry_notice_days)
      ? defaults.expiry_notice_days.join(", ")
      : "14, 7, 1",
    ...Object.fromEntries(TEXT_KEYS.map(([k]) => [k, text(k)])),
  }));
  const [noticeOn, setNoticeOn] = useState(defaults.expiry_notice_enabled === true);
  const [secret, setSecret] = useState("");
  const [saved, setSaved] = useState(false);
  const set = (k: string, v: string) => {
    setForm({ ...form, [k]: v });
    setSaved(false);
  };

  const saveM = useMutation({
    mutationFn: () => {
      const next: Record<string, unknown> = { ...defaults };
      for (const [k] of TEXT_KEYS) {
        if (form[k]?.trim()) next[k] = form[k].trim();
        else delete next[k];
      }
      next.mail_transport = form.mail_transport;
      next.smtp_security = form.smtp_security;
      if (form.smtp_port?.trim()) next.smtp_port = Number(form.smtp_port);
      else delete next.smtp_port;
      next.expiry_notice_enabled = noticeOn;
      next.expiry_notice_days = (form.expiry_notice_days ?? "")
        .split(/[\s,]+/)
        .filter(Boolean)
        .map(Number);
      return putPlatformDefaults(next);
    },
    onSuccess: () => {
      setSaved(true);
      onSaved();
    },
  });
  const sealM = useMutation({
    mutationFn: () => putPlatformSecret("mail_secret", secret),
    onSuccess: (data) => {
      setSecret("");
      qc.setQueryData(["platform-secrets"], data);
    },
  });
  const clearM = useMutation({
    mutationFn: () => deletePlatformSecret("mail_secret"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["platform-secrets"] }),
  });

  const sealed = secrets?.secrets.find((s) => s.name === "mail_secret");
  const transport = form.mail_transport;
  const state = !secrets
    ? "—"
    : !secrets.platform_key_reported
      ? "Keine Installation meldet einen Plattform-Schlüssel (MAGISTER_PLATFORM_SECRETS_KEY)."
      : !sealed?.sealed
        ? "nicht gesetzt"
        : sealed.key_current === false
          ? "veraltet — der Plattform-Schlüssel hat gewechselt, bitte neu setzen"
          : `versiegelt (${sealed.updated_by ?? "?"})`;

  return (
    <section className="rounded border bg-white p-4">
      <h2 className="mb-1 font-semibold">Mailversand (Standard für alle Kunden)</h2>
      <p className="mb-3 text-xs text-slate-500">
        Für die Erinnerung vor dem Passwort-Ablauf. Gilt für jeden Kunden ohne eigene Anbindung
        (Kunde → Einstellungen → Mailversand). Microsoft 365: App-Registrierung mit der
        Anwendungsberechtigung Mail.Send, beschränkt auf das Absender-Postfach.
      </p>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          saveM.mutate();
        }}
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="mb-1 block text-slate-600">Versand über</span>
            <select
              value={transport}
              onChange={(e) => set("mail_transport", e.target.value)}
              className="w-full rounded border px-2 py-1 text-sm"
            >
              <option value="off">aus</option>
              <option value="graph">Microsoft 365 (Graph)</option>
              <option value="smtp">SMTP-Server</option>
            </select>
          </label>
          {TEXT_KEYS.filter(
            ([k]) =>
              !(
                (transport !== "graph" && k.startsWith("graph_")) ||
                (transport !== "smtp" && k.startsWith("smtp_"))
              ),
          ).map(([k, label, placeholder]) => (
            <label key={k} className="block text-sm">
              <span className="mb-1 block text-slate-600">{label}</span>
              <input
                value={form[k] ?? ""}
                placeholder={placeholder}
                onChange={(e) => set(k, e.target.value)}
                className="w-full rounded border px-2 py-1 font-mono text-xs"
              />
            </label>
          ))}
          {transport === "smtp" && (
            <>
              <label className="block text-sm">
                <span className="mb-1 block text-slate-600">Port (leer = 587 bzw. 465)</span>
                <input
                  type="number"
                  value={form.smtp_port ?? ""}
                  onChange={(e) => set("smtp_port", e.target.value)}
                  className="w-full rounded border px-2 py-1 font-mono text-xs"
                />
              </label>
              <label className="block text-sm">
                <span className="mb-1 block text-slate-600">Verschlüsselung</span>
                <select
                  value={form.smtp_security}
                  onChange={(e) => set("smtp_security", e.target.value)}
                  className="w-full rounded border px-2 py-1 text-sm"
                >
                  <option value="starttls">STARTTLS (587)</option>
                  <option value="tls">TLS (465)</option>
                </select>
              </label>
            </>
          )}
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={noticeOn}
              onChange={(e) => {
                setNoticeOn(e.target.checked);
                setSaved(false);
              }}
            />
            Erinnerung vor dem Passwort-Ablauf (Vorgabe für alle Kunden)
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-slate-600">Tage vorher (mit Komma)</span>
            <input
              value={form.expiry_notice_days ?? ""}
              onChange={(e) => set("expiry_notice_days", e.target.value)}
              className="w-full rounded border px-2 py-1 font-mono text-xs"
            />
          </label>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={saveM.isPending}
            className="rounded bg-slate-900 px-4 py-1.5 text-sm text-white disabled:opacity-50"
          >
            Standard speichern
          </button>
          {saved && <span className="text-sm text-emerald-700">Gespeichert.</span>}
        </div>
        {saveM.isError && <ErrorBox error={saveM.error} />}
      </form>

      {transport !== "off" && (
        <div className="mt-4 space-y-1 border-t pt-3">
          <span className="block text-sm text-slate-600">
            {transport === "graph" ? "Client-Secret" : "SMTP-Passwort"} (Plattform)
          </span>
          <p className="text-xs text-slate-500">{state}</p>
          <div className="flex gap-2">
            <input
              type="password"
              autoComplete="off"
              value={secret}
              onChange={(e) => setSecret(e.target.value)}
              placeholder={sealed?.sealed ? "neuen Wert eingeben" : "Wert eingeben"}
              className="w-80 rounded border px-2 py-1 text-sm"
            />
            <button
              type="button"
              onClick={() => sealM.mutate()}
              disabled={!secret || sealM.isPending}
              className="rounded border px-3 py-1 text-sm disabled:opacity-50"
            >
              Versiegeln
            </button>
            {sealed?.sealed && (
              <button
                type="button"
                onClick={() => clearM.mutate()}
                disabled={clearM.isPending}
                className="rounded border px-3 py-1 text-sm text-red-700 disabled:opacity-50"
              >
                Entfernen
              </button>
            )}
          </div>
          {sealM.isError && <ErrorBox error={sealM.error} />}
          {secretsError != null && <ErrorBox error={secretsError} />}
        </div>
      )}

      <div className="mt-4 border-t pt-3">
        <MailTestBox />
        <p className="mt-1 text-xs text-slate-500">
          Gesendet wird mit dem gespeicherten Standard (vorher speichern und versiegeln) über einen
          Kunden, der ihn verwendet.
        </p>
      </div>
    </section>
  );
}
