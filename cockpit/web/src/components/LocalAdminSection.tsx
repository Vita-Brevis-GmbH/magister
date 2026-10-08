import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  getTenantStatus,
  listMaintenance,
  setupLocalAdmin,
} from "../api/operations";
import { ErrorBox } from "./ErrorBox";

/**
 * Lokales Administrationskonto im Portal des Kunden (ADR-0024, Nachtrag).
 *
 * Der Weg hinein, solange Entra ID nicht eingerichtet ist — und der Notzugang,
 * wenn Entra ausfällt. Das Passwort wird hier eingegeben, sofort für die
 * Installation dieses Kunden versiegelt und genau einmal angewandt; die
 * Konsole kann es danach nicht mehr lesen. Den zweiten Faktor (TOTP) richtet
 * die Person bei der ersten Anmeldung im Portal selbst ein: QR-Code scannen,
 * Code bestätigen, Wiederherstellungscodes aufbewahren.
 */
export function LocalAdminSection({ tenantId }: { tenantId: string }) {
  const qc = useQueryClient();
  const statusQ = useQuery({
    queryKey: ["tenant-status", tenantId],
    queryFn: () => getTenantStatus(tenantId),
    retry: false,
  });
  const ordersQ = useQuery({
    queryKey: ["maintenance", tenantId],
    queryFn: () => listMaintenance(tenantId),
    refetchInterval: (q) =>
      q.state.data?.some(
        (r) => r.action === "local_admin_setup" && r.state === "requested",
      )
        ? 5000
        : false,
  });
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [resetMfa, setResetMfa] = useState(false);

  const m = useMutation({
    mutationFn: () =>
      setupLocalAdmin(tenantId, { username, password, reset_mfa: resetMfa }),
    onSuccess: () => {
      setPassword("");
      setRepeat("");
      setResetMfa(false);
      void qc.invalidateQueries({ queryKey: ["maintenance", tenantId] });
    },
  });

  const la = statusQ.data?.report?.local_admin ?? null;
  const reported = Boolean(statusQ.data?.report);
  const keyReady = Boolean(statusQ.data?.report?.sealed_public_key);
  const last = ordersQ.data?.find((r) => r.action === "local_admin_setup");
  const mismatch = password !== "" && repeat !== "" && password !== repeat;
  const tooShort = password !== "" && password.length < 12;
  const canSubmit =
    keyReady &&
    !m.isPending &&
    password.length >= 12 &&
    password === repeat &&
    username !== "";

  return (
    <section className="rounded border bg-white p-4">
      <h2 className="mb-1 font-semibold">Lokales Administrationskonto</h2>
      <p className="mb-3 text-sm text-slate-600">
        Anmeldung im Portal mit Benutzername, Passwort und Einmalcode (TOTP) —
        der Weg hinein, solange Entra ID nicht eingerichtet ist, und der
        Notzugang, wenn Entra ausfällt. Das Passwort wird für die Installation
        dieses Kunden versiegelt und einmal angewandt; die Konsole kann es
        danach nicht mehr lesen. Den Einmalcode richtet die Person bei der
        ersten Anmeldung im Portal selbst ein.
      </p>

      <dl className="mb-4 grid grid-cols-[12rem_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="text-slate-500">Im Portal</dt>
        <dd>
          {!reported
            ? "unbekannt — die Installation hat sich noch nicht gemeldet"
            : la === null
              ? "unbekannt — die Installation meldet es noch nicht (älterer Stand)"
              : !la.exists
                ? "kein lokales Konto"
                : `${la.username ?? "?"} · ${la.enabled ? "aktiv" : "deaktiviert"}${
                    la.locked ? " · gesperrt (Fehlversuche)" : ""
                  }`}
        </dd>
        {la?.exists && (
          <>
            <dt className="text-slate-500">Einmalcode (TOTP)</dt>
            <dd className={la.mfa_enrolled ? "" : "text-amber-700"}>
              {la.mfa_enrolled
                ? "eingerichtet"
                : "noch nicht eingerichtet — wird bei der ersten Anmeldung verlangt"}
            </dd>
          </>
        )}
        {last && (
          <>
            <dt className="text-slate-500">Letzter Auftrag</dt>
            <dd
              className={
                last.state === "failed"
                  ? "text-red-700"
                  : last.state === "done"
                    ? "text-emerald-700"
                    : "text-slate-700"
              }
            >
              {last.state === "requested"
                ? "wartet auf den nächsten Abgleich (höchstens eine Minute)"
                : last.state === "done"
                  ? `angewandt${last.result?.created ? " (neu angelegt)" : " (Passwort gesetzt)"}${
                      last.result?.mfa_reset ? ", Einmalcode zurückgesetzt" : ""
                    }`
                  : last.state === "failed"
                    ? `gescheitert: ${String(last.result?.error ?? "?")}`
                    : "zurückgezogen"}
              {" · "}
              {new Date(last.requested_at).toLocaleString()} ·{" "}
              {last.requested_by}
            </dd>
          </>
        )}
      </dl>

      {!keyReady && (
        <p className="mb-3 rounded border border-amber-400 bg-amber-50 p-2 text-sm text-amber-900">
          Erst wenn sich die Installation meldet, lässt sich ein Passwort
          versiegeln. Falls das Portal mit 503 antwortet: Übersicht → Anbindung
          an die Datenebene.
        </p>
      )}

      <form
        className="grid max-w-xl gap-2 text-sm"
        onSubmit={(e) => {
          e.preventDefault();
          if (
            window.confirm(
              la?.exists
                ? `Passwort von „${username}" neu setzen${resetMfa ? " und den Einmalcode zurücksetzen" : ""}?`
                : `Lokales Konto „${username}" im Portal anlegen?`,
            )
          ) {
            m.mutate();
          }
        }}
      >
        <label>
          <span className="block text-slate-600">Benutzername</span>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value.trim().toLowerCase())}
            autoComplete="off"
            className="w-full rounded border px-2 py-1 font-mono text-xs"
          />
        </label>
        <label>
          <span className="block text-slate-600">
            Passwort (mindestens 12 Zeichen)
          </span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            className="w-full rounded border px-2 py-1 font-mono text-xs"
          />
        </label>
        <label>
          <span className="block text-slate-600">Passwort wiederholen</span>
          <input
            type="password"
            value={repeat}
            onChange={(e) => setRepeat(e.target.value)}
            autoComplete="new-password"
            className="w-full rounded border px-2 py-1 font-mono text-xs"
          />
        </label>
        {la?.exists && (
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={resetMfa}
              onChange={(e) => setResetMfa(e.target.checked)}
            />
            <span>
              Einmalcode zurücksetzen (Handy verloren) — die nächste Anmeldung
              verlangt eine neue Einrichtung
            </span>
          </label>
        )}
        {(mismatch || tooShort) && (
          <p className="text-red-700">
            {tooShort
              ? "Mindestens 12 Zeichen."
              : "Die beiden Passwörter stimmen nicht überein."}
          </p>
        )}
        {m.isError && <ErrorBox error={m.error} />}
        <div>
          <button
            type="submit"
            disabled={!canSubmit}
            className="rounded border px-3 py-1 text-sm disabled:opacity-50"
          >
            {la?.exists ? "Passwort setzen" : "Konto einrichten"}
          </button>
        </div>
      </form>
    </section>
  );
}
