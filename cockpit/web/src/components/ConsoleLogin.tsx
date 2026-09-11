import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { beginEnrolment, submitCode, type Enrolment, type Whoami } from "../api/consoleAuth";
import { ErrorBox } from "./ErrorBox";

/**
 * Die Anmeldung an der Konsole (ADR-0020).
 *
 * Sie fragt **nicht**, wer man ist. Das steht schon fest, bevor diese Seite
 * lädt: der Reverse Proxy hat ein Client-Zertifikat gegen die Plattform-CA
 * geprüft, und der Server hat daraus die Zeile gefunden. Ein Feld
 * „Benutzername“ wäre eine Eingabe für etwas Bekanntes — und die Stelle, an
 * der man sich vertippt, statt sich anzumelden.
 *
 * Was bleibt, ist der zweite Faktor: ein Code aus der Authenticator-App oder
 * einer der zehn Wiederherstellungscodes.
 */
export function ConsoleLogin({ who }: { who: Whoami }) {
  const qc = useQueryClient();
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
  });

  return (
    <div className="mx-auto max-w-xl p-6">
      <h1 className="mb-1 text-lg font-semibold">Vita Brevis Cockpit</h1>
      <p className="mb-6 text-sm text-slate-600">
        Anmeldung mit Client-Zertifikat und zweitem Faktor.
      </p>

      {who.stage === "unknown_certificate" && <UnknownCertificate />}

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
            Zertifikat erkannt:{" "}
            <strong>{who.name ?? who.upn}</strong>
            {who.name && who.upn && (
              <span className="text-slate-600"> ({who.upn})</span>
            )}
          </p>

          {who.stage === "enrolment_required" && !enrolment && (
            <div className="space-y-3">
              <p className="text-slate-600">
                Für dieses Zertifikat ist noch kein zweiter Faktor eingerichtet. Er
                wird jetzt eingerichtet — von Ihnen, nicht von jemandem, der Sie
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
                  Versuch den nächsten abwarten.
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
 * Warum hier nicht steht, ob das Zertifikat bekannt wäre.
 *
 * Kein Zertifikat und ein unbekanntes Zertifikat sehen gleich aus. Die
 * Unterscheidung wäre eine Auskunft darüber, welche Zertifikate es gibt — an
 * eine Stelle, die noch niemanden angemeldet hat.
 */
function UnknownCertificate() {
  return (
    <div className="space-y-3 rounded border bg-slate-50 p-4 text-sm">
      <p className="font-medium">Kein gültiges Client-Zertifikat.</p>
      <p className="text-slate-600">
        Der Browser hat kein Zertifikat der Plattform-CA vorgelegt, oder das
        vorgelegte gehört zu keinem eingetragenen Operator. Beides sieht hier
        gleich aus.
      </p>
      <ul className="list-disc space-y-1 pl-5 text-slate-600">
        <li>Ist das Zertifikat im Zertifikatsspeicher dieses Geräts installiert?</li>
        <li>Hat der Browser beim Öffnen nach einem Zertifikat gefragt?</li>
        <li>
          Ist der Operator eingetragen? Das macht{" "}
          <code className="font-mono">python -m cockpit_api.cli.add_operator</code> auf
          dem Konsolen-Host.
        </li>
      </ul>
    </div>
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
        Einrichten — diese Angaben kommen genau einmal
      </h2>

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
