import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import {
  deletePlatformTemplate,
  listPlatformTemplates,
  savePlatformTemplate,
  type PlatformTemplate,
  type TemplateAudience,
} from "../api/templates";
import { listTenants, type Tenant, type TenantProfile } from "../api/tenants";
import { ErrorBox } from "../components/ErrorBox";

const KEY_LABELS: Record<string, string> = {
  enrollment: "Eintritt",
  class_change: "Klassenwechsel",
  password_handout: "Passwort-Übergabe",
};

const PROFILE_LABELS: Record<TenantProfile, string> = {
  school: "Schule",
  company: "Firma",
  neutral: "Neutral",
};

const AUDIENCE_LABELS: Record<TemplateAudience, string> = {
  all: "Alle Kunden",
  profile: "Ein Profil",
  selection: "Eine Auswahl",
};

/**
 * Die globalen Vorlagen pflegen (ADR-0018).
 *
 * Eine Fläche für den Betreiber, nicht für den Kunden. Was hier gespeichert
 * wird, holt die Datenebene beim nächsten Abgleich ab; von hier wird nie in
 * ein Kundenschema geschrieben.
 *
 * Drei Dinge sagt die Seite ausdrücklich, weil sie sonst niemand beim Klicken
 * erfährt:
 *
 * * Die **Fassungsnummer** steigt nur bei einer inhaltlichen Änderung. Wer
 *   nur die Zielgruppe umstellt, soll wissen, dass beim Kunden kein Hinweis
 *   aufleuchtet.
 * * **Ausschalten** ist nicht **Löschen**: Ausschalten behält die
 *   Fassungsnummer und damit die Quittungen der Kunden.
 * * Eine **Sperre** nimmt dem Kunden seinen Text nicht weg.
 */
export function Templates() {
  const qc = useQueryClient();
  const listQ = useQuery({
    queryKey: ["platform-templates"],
    queryFn: listPlatformTemplates,
    retry: false,
  });
  // Nur für die Auswahl gebraucht. `enabled` wäre eine Optimierung, die den
  // ersten Klick auf „Eine Auswahl“ mit einem Ladezustand bestraft.
  const tenantsQ = useQuery({ queryKey: ["tenants"], queryFn: listTenants, retry: false });

  const [chosen, setChosen] = useState<{ key: string; language: string } | null>(null);
  // Wer speichert, ist eine Eigenschaft der Sitzung und nicht der Vorlage.
  // Stand vorher im Formular — und war nach jedem Speichern leer, weil das
  // Formular neu aufgebaut wird. Wer zwei Vorlagen pflegt, tippt seine Adresse
  // sonst zweimal. `sessionStorage` wie beim Token: weg, wenn der Tab zugeht.
  const [actor, setActor] = useState(() => sessionStorage.getItem("cockpit_actor") ?? "");
  // Zählt hoch, wenn eine Vorlage entfernt wurde: dann muss das Formular leer
  // sein, und ein Neuaufbau ist der ehrlichste Weg dorthin.
  const [nonce, setNonce] = useState(0);

  const keys = listQ.data?.keys ?? [];
  const languages = listQ.data?.languages ?? [];

  // Abgeleitet und nicht in einem Effekt gesetzt: „noch nichts gewählt“ heisst
  // „das erste nehmen“, und das ist eine Rechnung, kein Zustand.
  const key = chosen?.key ?? keys[0] ?? "";
  const language = chosen?.language ?? "de";

  const existing: PlatformTemplate | undefined = useMemo(
    () => listQ.data?.items.find((t) => t.key === key && t.language === language),
    [listQ.data, key, language],
  );

  const deleteM = useMutation({
    mutationFn: () => deletePlatformTemplate(key, language),
    onSuccess: async () => {
      // Erst neu laden, dann neu aufbauen. Umgekehrt (und so war der erste
      // Entwurf) baut das Formular mit dem **alten** `existing` neu auf und
      // steht nach dem Entfernen mit dem entfernten Text da — im Browser
      // nachgestellt: „Rumpf nach dem Entfernen leer: False“.
      await qc.invalidateQueries({ queryKey: ["platform-templates"] });
      setNonce((n) => n + 1);
    },
  });

  return (
    <div>
      <h1 className="mb-1 text-xl font-semibold">Globale Vorlagen</h1>
      <p className="mb-4 max-w-3xl text-sm text-slate-600">
        Diese Texte holen die Kunden beim nächsten Abgleich ab. Ein Kunde mit eigener
        Fassung behält sie — er sieht nur den Hinweis, dass es eine neue globale gibt. Wer
        eine Fassung <em>verbindlich</em> machen will, nimmt „nicht überschreibbar“; der
        eigene Text des Kunden bleibt dabei gespeichert und gilt wieder, sobald die Sperre
        fällt.
      </p>

      {listQ.isLoading && <p>Lade…</p>}
      {listQ.isError && <ErrorBox error={listQ.error} />}
      {deleteM.isError && <ErrorBox error={deleteM.error} />}

      {listQ.data && (
        <div className="grid gap-6 lg:grid-cols-[20rem_1fr]">
          <section>
            <h2 className="mb-2 text-sm font-medium text-slate-600">Vorhanden</h2>
            {listQ.data.items.length === 0 ? (
              <p className="text-sm text-slate-500">
                Noch keine. Ein neuer Kunde startet damit mit den eingebauten Texten.
              </p>
            ) : (
              <ul className="space-y-1 text-sm">
                {listQ.data.items.map((item) => (
                  <li key={`${item.key}/${item.language}`}>
                    <button
                      type="button"
                      onClick={() => setChosen({ key: item.key, language: item.language })}
                      className={`w-full rounded px-2 py-1 text-left ${
                        item.key === key && item.language === language
                          ? "bg-slate-200 font-medium"
                          : "hover:bg-slate-100"
                      }`}
                    >
                      {KEY_LABELS[item.key] ?? item.key} · {item.language.toUpperCase()}
                      <span className="ml-1 text-xs text-slate-500">
                        Fassung {item.version}
                        {item.may_override ? "" : " · gesperrt"}
                        {item.is_active ? "" : " · aus"}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="space-y-3 text-sm">
            <div className="flex flex-wrap gap-3">
              <label className="block">
                <span className="mb-1 block text-slate-600">Vorlage</span>
                <select
                  value={key}
                  onChange={(e) => setChosen({ key: e.target.value, language })}
                  className="rounded border px-2 py-1"
                >
                  {keys.map((k) => (
                    <option key={k} value={k}>
                      {KEY_LABELS[k] ?? k}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="mb-1 block text-slate-600">Sprache</span>
                <select
                  value={language}
                  onChange={(e) => setChosen({ key, language: e.target.value })}
                  className="rounded border px-2 py-1"
                >
                  {languages.map((l) => (
                    <option key={l} value={l}>
                      {l.toUpperCase()}
                    </option>
                  ))}
                </select>
              </label>
              <div className="self-end text-xs text-slate-500">
                {existing
                  ? `Fassung ${existing.version} · geändert ${new Date(
                      existing.updated_at,
                    ).toLocaleString("de-CH")}${
                      existing.updated_by ? ` von ${existing.updated_by}` : ""
                    }`
                  : "neu — noch nicht ausgeliefert"}
              </div>
            </div>

            {/*
              `key` erzwingt einen Neuaufbau, sobald eine andere Vorlage gewählt
              oder eine entfernt wurde. Das ist der Grund, aus dem das Formular
              seinen Zustand aus den Eigenschaften vorbelegen darf, ohne ihn in
              einem Effekt nachzuziehen: React baut die Komponente neu, statt
              zwei Wahrheiten aneinander anzugleichen.

              Ausdrücklich **nicht** bei jeder neuen Fassung: der erste Entwurf
              hatte `updated_at` im Schlüssel, und damit war nach jedem
              Speichern das Formular neu — die Erfolgsmeldung weg und das Feld
              „Wer speichert“ leer. Der geltende Stand steht in der Zeile
              darüber; das Formular zeigt, was der Betreiber gerade tippt.
            */}
            <TemplateForm
              key={`${key}/${language}/${nonce}`}
              templateKey={key}
              language={language}
              existing={existing}
              tenants={tenantsQ.data ?? []}
              tenantsError={tenantsQ.isError ? tenantsQ.error : null}
              actor={actor}
              onActorChange={(value) => {
                setActor(value);
                sessionStorage.setItem("cockpit_actor", value);
              }}
              onSaved={() => void qc.invalidateQueries({ queryKey: ["platform-templates"] })}
            />

            {existing && (
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => deleteM.mutate()}
                  disabled={deleteM.isPending}
                  className="rounded border px-3 py-1 disabled:opacity-50"
                >
                  Ganz entfernen
                </button>
                <span className="text-xs text-slate-500">
                  Entfernen verwirft die Fassungsnummer. „Ausgeliefert“ abzuschalten
                  behält sie — und damit die Quittungen der Kunden.
                </span>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

function TemplateForm({
  templateKey,
  language,
  existing,
  tenants,
  tenantsError,
  actor,
  onActorChange,
  onSaved,
}: {
  templateKey: string;
  language: string;
  existing: PlatformTemplate | undefined;
  tenants: Tenant[];
  tenantsError: unknown;
  actor: string;
  onActorChange: (value: string) => void;
  onSaved: () => void;
}) {
  const [subject, setSubject] = useState(existing?.subject ?? "");
  const [body, setBody] = useState(existing?.body_html ?? "");
  const [mayOverride, setMayOverride] = useState(existing?.may_override ?? true);
  const [audience, setAudience] = useState<TemplateAudience>(existing?.audience ?? "all");
  const [profile, setProfile] = useState<TenantProfile>(existing?.audience_profile ?? "school");
  const [selection, setSelection] = useState<string[]>(existing?.tenant_ids ?? []);
  const [isActive, setIsActive] = useState(existing?.is_active ?? true);

  const saveM = useMutation({
    mutationFn: () =>
      savePlatformTemplate(templateKey, language, {
        subject: subject || null,
        body_html: body,
        may_override: mayOverride,
        audience,
        audience_profile: audience === "profile" ? profile : null,
        // Bei einer anderen Zielgruppe ausdrücklich `[]` und nicht `null`:
        // `null` heisst „Auswahl nicht anfassen“, und eine liegengebliebene
        // Auswahl würde beim Zurückschalten stillschweigend wieder gelten.
        tenant_ids: audience === "selection" ? selection : [],
        is_active: isActive,
        actor,
      }),
    onSuccess: onSaved,
  });

  function toggleTenant(id: string): void {
    setSelection((current) =>
      current.includes(id) ? current.filter((t) => t !== id) : [...current, id],
    );
  }

  return (
    <div className="space-y-3">
      {saveM.isError && <ErrorBox error={saveM.error} />}

      <label className="block">
        <span className="mb-1 block text-slate-600">Betreff</span>
        <input
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          maxLength={512}
          className="w-full rounded border px-2 py-1"
        />
      </label>

      <label className="block">
        <span className="mb-1 block text-slate-600">
          Rumpf (HTML, Platzhalter wie <code>{"{{ student.display_name }}"}</code>)
        </span>
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={14}
          className="w-full rounded border p-2 font-mono text-xs"
        />
      </label>

      <fieldset className="space-y-2 rounded border p-3">
        <legend className="px-1 text-slate-600">Zielgruppe</legend>
        {(["all", "profile", "selection"] as const).map((value) => (
          <label key={value} className="flex items-center gap-2">
            <input
              type="radio"
              name="audience"
              checked={audience === value}
              onChange={() => setAudience(value)}
            />
            <span>{AUDIENCE_LABELS[value]}</span>
          </label>
        ))}

        {audience === "profile" && (
          <select
            value={profile}
            onChange={(e) => setProfile(e.target.value as TenantProfile)}
            className="rounded border px-2 py-1"
          >
            {(Object.keys(PROFILE_LABELS) as TenantProfile[]).map((p) => (
              <option key={p} value={p}>
                {PROFILE_LABELS[p]}
              </option>
            ))}
          </select>
        )}

        {audience === "selection" && (
          <div className="max-h-40 space-y-1 overflow-y-auto rounded border p-2">
            {tenantsError !== null && <ErrorBox error={tenantsError} />}
            {tenants.length === 0 && <p className="text-slate-500">Noch keine Kunden erfasst.</p>}
            {tenants.map((tenant) => (
              <label key={tenant.id} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={selection.includes(tenant.id)}
                  onChange={() => toggleTenant(tenant.id)}
                />
                <span>
                  {tenant.name} <span className="text-xs text-slate-500">({tenant.slug})</span>
                </span>
              </label>
            ))}
          </div>
        )}
      </fieldset>

      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={!mayOverride}
          onChange={(e) => setMayOverride(!e.target.checked)}
        />
        <span>
          Nicht überschreibbar — gilt beim Kunden auch dann, wenn er eine eigene Fassung hat
        </span>
      </label>

      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={isActive}
          onChange={(e) => setIsActive(e.target.checked)}
        />
        <span>Ausgeliefert (ausgeschaltet verschwindet sie beim Kunden)</span>
      </label>

      <label className="block">
        <span className="mb-1 block text-slate-600">Wer speichert (fürs Protokoll)</span>
        <input
          value={actor}
          onChange={(e) => onActorChange(e.target.value)}
          placeholder="vorname.nachname@vitabrevis.ch"
          className="w-full rounded border px-2 py-1"
        />
      </label>

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => saveM.mutate()}
          disabled={saveM.isPending || !body.trim() || !actor.trim() || !templateKey}
          className="rounded bg-slate-900 px-3 py-1 text-white disabled:opacity-50"
        >
          {saveM.isPending ? "Speichere…" : "Speichern"}
        </button>
        {saveM.isSuccess && (
          <span className="text-emerald-700">Gespeichert — Fassung {saveM.data.version}</span>
        )}
      </div>

      <p className="max-w-2xl text-xs text-slate-500">
        Die Fassungsnummer steigt nur, wenn sich Betreff, Rumpf oder die Sperre ändern —
        eine andere Zielgruppe löst beim Kunden keinen Hinweis aus.
      </p>
    </div>
  );
}
