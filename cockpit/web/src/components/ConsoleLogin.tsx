import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  beginEnrolment,
  login,
  submitCode,
  type Enrolment,
  type Whoami,
} from "../api/consoleAuth";
import { ErrorBox } from "./ErrorBox";

/**
 * Die Anmeldung an der Konsole (ADR-0020, ADR-0023).
 *
 * Zwei Schritte, und der erste hat zwei Wege:
 *
 * - **Passwort** (ADR-0023 D1). Der Normalfall: Benutzername und Passwort,
 *   danach der Code. Vorher steht auf dieser Seite noch kein Name — der
 *   Server kennt niemanden, und die Maske soll nichts behaupten.
 * - **Client-Zertifikat** (ADR-0020 D1). Wer eines hat, ist schon erkannt,
 *   bevor diese Seite lädt; dann fehlt nur noch der Code, und das Formular
 *   erscheint gar nicht.
 *
 * Welcher Fall vorliegt, entscheidet allein die Antwort des Servers.
 */
export function ConsoleLogin({ who }: { who: Whoami }) {
  const qc = useQueryClient();
  const [upn, setUpn] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [enrolment, setEnrolment] = useState<Enrolment | null>(null);
  const [stored, setStored] = useState(false);

  const enrolM = useMutation({
    mutationFn: beginEnrolment,
    onSuccess: (out) => setEnrolment(out),
  });
  const codeM = useMutation({
    mutationFn: () => submitCode(code.trim()),
    onSuccess: () => qc.invalidateQueries(),
    // Auch beim Fehlschlag den Stand neu holen: der Zwischenstand zwischen
    // Passwort und Code gilt zehn Minuten (ADR-0023 D2). Läuft er ab, ist
    // die Antwort dieselbe 401 wie bei einem falschen Code — und die Maske
    // behauptete weiter, es fehle nur der Code. Nach dem Nachfragen steht
    // wieder das Anmeldeformular da, mit dem Hinweis unten.
    onError: () => qc.invalidateQueries(),
  });
  const loginM = useMutation({
    // Nach dem Passwort ist man NICHT angemeldet, sondern beim zweiten
    // Schritt. `invalidateQueries` holt den neuen Stand, und der sagt, ob
    // jetzt der Code oder die Einrichtung dran ist.
    mutationFn: () => login(upn.trim(), password),
    onSuccess: () => {
      setPassword("");
      void qc.invalidateQueries();
    },
  });

  return (
    <div className="mx-auto max-w-xl p-6">
      <h1 className="mb-1 text-lg font-semibold">Vita Brevis Cockpit</h1>
      <p className="mb-6 text-sm text-slate-600">
        Anmeldung mit Benutzername, Passwort und zweitem Faktor.
      </p>

      {who.stage === "unknown_certificate" && (
        <form
          className="space-y-3 text-sm"
          onSubmit={(e) => {
            e.preventDefault();
            loginM.mutate();
          }}
        >
          {loginM.isError && (
            <p className="rounded border border-red-300 bg-red-50 p-2 text-red-900">
              Anmeldung nicht möglich. Benutzername, Passwort oder eine Sperre —
              welches davon, sagt diese Seite absichtlich nicht.
            </p>
          )}
          {codeM.isError && !loginM.isError && (
            <p className="rounded border border-amber-300 bg-amber-50 p-2 text-amber-900">
              Der zweite Schritt ist abgelaufen — zwischen Passwort und Code
              liegen zehn Minuten. Bitte neu anmelden.
            </p>
          )}
          <label className="block">
            <span className="mb-1 block text-slate-600">Benutzername</span>
            <input
              value={upn}
              onChange={(e) => setUpn(e.target.value)}
              autoComplete="username"
              autoFocus
              placeholder="vorname.nachname@vitabrevis.ch"
              className="w-full rounded border px-2 py-1"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-slate-600">Passwort</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              className="w-full rounded border px-2 py-1"
            />
          </label>
          <button
            type="submit"
            disabled={loginM.isPending || upn.trim().length < 3 || password.length === 0}
            className="rounded bg-slate-900 px-3 py-1 text-white disabled:opacity-50"
          >
            {loginM.isPending ? "Prüfe…" : "Weiter"}
          </button>
          <NoAccountHint />
        </form>
      )}

      {who.stage === "locked" && (
        <div className="rounded border border-red-300 bg-red-50 p-4 text-sm text-red-900">
          <p className="font-medium">Zu viele Fehlversuche.</p>
          <p>
            Die Anmeldung ist für eine Viertelstunde gesperrt. Die Sperre läuft von
            selbst ab; es gibt keinen Knopf dafür.
          </p>
        </div>
      )}

      {(who.stage === "enrolment_required" || who.stage === "totp_required") && (
        <div className="space-y-4 text-sm">
          <p className="rounded border bg-slate-50 p-3">
            Angemeldet als{" "}
            <strong>{who.name ?? who.upn}</strong>
            {who.name && who.upn && (
              <span className="text-slate-600"> ({who.upn})</span>
            )}
          </p>

          {who.stage === "enrolment_required" && !enrolment && (
            <div className="space-y-3">
              <p className="text-slate-600">
                Für dieses Konto ist noch kein zweiter Faktor eingerichtet. Er wird
                jetzt eingerichtet — von Ihnen, nicht von jemandem, der Sie
                eingetragen hat.
              </p>
              {enrolM.isError && <ErrorBox error={enrolM.error} />}
              <button
                type="button"
                onClick={() => enrolM.mutate()}
                disabled={enrolM.isPending}
                className="rounded bg-slate-900 px-3 py-1 text-white disabled:opacity-50"
              >
                {enrolM.isPending ? "Einen Moment…" : "Zweiten Faktor einrichten"}
              </button>
            </div>
          )}

          {enrolment && (
            <EnrolmentOffer
              enrolment={enrolment}
              stored={stored}
              onStored={() => setStored(true)}
            />
          )}

          {(who.stage === "totp_required" || enrolment) && (
            <form
              className="space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                codeM.mutate();
              }}
            >
              {codeM.isError && (
                <p className="rounded border border-red-300 bg-red-50 p-2 text-red-900">
                  Der Code stimmt nicht. Jeder Code gilt einmal — bei einem erneuten
                  Versuch den nächsten abwarten. Passt auch der nächste nicht, geht
                  meist die Uhr des Servers falsch; das ordnet{" "}
                  <code className="font-mono text-xs">
                    python -m cockpit_api.cli.totp_probe --upn … --code …
                  </code>{" "}
                  auf dem Konsolen-Host ein.
                </p>
              )}
              <label className="block">
                <span className="mb-1 block text-slate-600">
                  Code aus der Authenticator-App (oder ein Wiederherstellungscode)
                </span>
                <input
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  inputMode="text"
                  autoComplete="one-time-code"
                  autoFocus
                  placeholder="123456"
                  className="w-40 rounded border px-2 py-1 font-mono tracking-widest"
                />
              </label>
              <button
                type="submit"
                disabled={
                  codeM.isPending || code.trim().length < 6 || (enrolment !== null && !stored)
                }
                className="rounded bg-slate-900 px-3 py-1 text-white disabled:opacity-50"
              >
                {codeM.isPending ? "Prüfe…" : "Anmelden"}
              </button>
              {enrolment && !stored && (
                <p className="text-xs text-slate-500">
                  Erst die Wiederherstellungscodes wegschreiben und bestätigen.
                </p>
              )}
            </form>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Warum hier nicht steht, welcher der Gründe zutrifft.
 *
 * Unbekannter Benutzer, falsches Passwort und Sperre sehen gleich aus. Die
 * Unterscheidung wäre eine Auskunft darüber, welche Konten es gibt — an
 * eine Stelle, die noch niemanden angemeldet hat.
 */
function NoAccountHint() {
  return (
    <p className="pt-2 text-xs text-slate-500">
      Noch kein Zugang? Ein Operator wird auf dem Konsolen-Host eingetragen:{" "}
      <code className="font-mono">
        python -m cockpit_api.cli.add_operator --upn … --name … --set-password
      </code>
      . Ein Client-Zertifikat bleibt möglich (ADR-0020) und ist dann der erste
      Faktor statt des Passworts.
    </p>
  );
}

/**
 * Geheimnis und Wiederherstellungscodes — genau einmal.
 *
 * Der QR-Code kommt als `data:`-URI vom Server. Das ist kein Umweg, sondern
 * spart eine QR-Bibliothek im Bündel und eine Lockerung der CSP.
 */
function EnrolmentOffer({
  enrolment,
  stored,
  onStored,
}: {
  enrolment: Enrolment;
  stored: boolean;
  onStored: () => void;
}) {
  return (
    <div className="space-y-3 rounded border-2 border-amber-500 bg-amber-50 p-4">
      <h2 className="font-semibold text-amber-900">
        Einrichten — die Wiederherstellungscodes kommen genau einmal
      </h2>
      <p className="text-sm text-amber-900">
        <strong>Nur eine App einrichten.</strong> Das Geheimnis bleibt dasselbe,
        solange es nicht bestätigt ist — ein zweiter Klick zeigt also denselben
        QR-Code. Passt der Code trotzdem nicht, ordnet{" "}
        <code className="font-mono text-xs">plattform-aufbau.sh totp --upn … --code …</code>{" "}
        auf dem Konsolen-Host ein, ob es die Uhr oder das Geheimnis ist.
      </p>

      <div className="flex flex-wrap items-start gap-4">
        <img
          src={enrolment.qr_data_uri}
          alt="QR-Code für die Authenticator-App"
          className="h-40 w-40 bg-white p-2"
        />
        <div className="text-sm text-amber-900">
          <p className="mb-1">Scannen, oder das Geheimnis von Hand eintragen:</p>
          <code className="select-all break-all rounded border border-amber-300 bg-white px-2 py-1 font-mono text-xs">
            {enrolment.secret}
          </code>
        </div>
      </div>

      <div className="text-sm text-amber-900">
        <p className="mb-1 font-medium">
          Wiederherstellungscodes — je einmal verwendbar, für den Fall ohne Telefon:
        </p>
        <ul className="grid grid-cols-2 gap-x-6 font-mono text-xs sm:grid-cols-3">
          {enrolment.recovery_codes.map((c) => (
            <li key={c} className="select-all">
              {c}
            </li>
          ))}
        </ul>
      </div>

      <button
        type="button"
        onClick={onStored}
        disabled={stored}
        className="rounded bg-amber-700 px-3 py-1 text-sm font-medium text-white disabled:opacity-50"
      >
        {stored ? "Bestätigt" : "Sind im Passwortspeicher"}
      </button>
    </div>
  );
}
