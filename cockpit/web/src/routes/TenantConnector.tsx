import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  certificateIsWorrying,
  createEnrollment,
  daysUntilExpiry,
  listAgents,
  listConnectorJobs,
  revokeAgent,
  type Agent,
  type Enrollment,
} from "../api/agents";
import { Badge, StatusBadge } from "../components/Badge";
import { ErrorBox } from "../components/ErrorBox";

/**
 * Das Einmal-Token für die Anmeldung.
 *
 * Kein `SecretOnce`: das ist ein anderer Fall. Ein Rollenpasswort verliert man
 * und muss es drehen; dieses Token **soll** weitergegeben werden — an die
 * IT-Person beim Kunden, über einen Kanal, der nicht die Mailbox ist. Es lebt
 * 24 Stunden und gilt einmal.
 */
function EnrollmentCard({ enrollment, onDone }: { enrollment: Enrollment; onDone: () => void }) {
  return (
    <div className="mb-4 rounded border-2 border-blue-400 bg-blue-50 p-4">
      <h3 className="mb-2 font-semibold text-blue-900">
        Einmal-Token für „{enrollment.agent_name}“
      </h3>
      <code className="mb-3 block select-all break-all rounded border border-blue-200 bg-white px-2 py-1 font-mono text-sm">
        {enrollment.token}
      </code>
      <ul className="mb-3 list-disc pl-5 text-sm text-blue-900">
        <li>
          Gültig bis {new Date(enrollment.expires_at).toLocaleString()} — danach ein neues
          bestellen.
        </li>
        <li>Gilt genau einmal. Wer sich damit anmeldet, ist der Agent.</li>
        <li>
          Nicht per E-Mail und nicht ins Ticket: über Telefon, Signal oder persönlich. Der
          Agent nimmt es über <span className="font-mono">stdin</span> — dann steht es
          auch nicht in der Prozessliste.
        </li>
        <li>
          Nach der Anmeldung nennt der Agent seinen SPKI-Fingerprint. Er muss mit der
          Anzeige unten übereinstimmen; weicht er ab, hat sich jemand anders angemeldet.
        </li>
      </ul>
      <button type="button" onClick={onDone} className="rounded border border-blue-400 px-3 py-1 text-sm">
        Ausblenden
      </button>
    </div>
  );
}

function AgentRow({
  agent,
  asOf,
  onRevoke,
}: {
  agent: Agent;
  /** Zeitpunkt des Datenabrufs — nicht „jetzt", siehe TenantBackups. */
  asOf: number;
  onRevoke: (agent: Agent) => void;
}) {
  const reference = new Date(asOf);
  const days = daysUntilExpiry(agent, reference);
  const worrying = certificateIsWorrying(agent, reference);
  return (
    <tr className="border-b">
      <td className="p-2">
        <span className="font-medium">{agent.name}</span>
        <br />
        <span className="font-mono text-xs text-slate-400">{agent.agent_version ?? "—"}</span>
      </td>
      <td className="p-2">
        <StatusBadge status={agent.status} />
        {agent.revoked_reason && (
          <span className="ml-2 text-xs text-slate-500">{agent.revoked_reason}</span>
        )}
      </td>
      <td className="p-2 font-mono text-xs">
        {agent.spki_sha256.slice(0, 16)}…
        {agent.previous_spki_sha256 && (
          <span className="ml-2" title="Erneuerungsfenster: beide Fingerprints gelten">
            <Badge tone="busy">erneuert</Badge>
          </span>
        )}
      </td>
      <td className="p-2 text-xs">
        {new Date(agent.certificate_not_after).toLocaleDateString()}
        <br />
        <span className={worrying ? "text-red-700" : days <= 30 ? "text-slate-500" : ""}>
          {days < 0 ? "abgelaufen" : `${days} Tage`}
          {!worrying && days <= 30 && " (erneuert sich selbst)"}
        </span>
      </td>
      <td className="p-2 text-xs">
        {agent.last_seen_at ? new Date(agent.last_seen_at).toLocaleString() : "nie"}
      </td>
      <td className="p-2">
        {agent.status !== "revoked" && (
          <button
            type="button"
            onClick={() => onRevoke(agent)}
            className="rounded border border-red-300 px-2 py-1 text-xs text-red-700"
          >
            Widerrufen
          </button>
        )}
      </td>
    </tr>
  );
}

export function TenantConnector({ tenantId }: { tenantId: string }) {
  const qc = useQueryClient();
  const [agentName, setAgentName] = useState("");
  const [enrollment, setEnrollment] = useState<Enrollment | null>(null);
  const [revoking, setRevoking] = useState<{ agent: Agent; reason: string } | null>(null);

  const agentsQ = useQuery({
    queryKey: ["agents", tenantId],
    queryFn: () => listAgents(tenantId),
    retry: false,
    refetchInterval: 30_000,
  });
  const jobsQ = useQuery({
    queryKey: ["connector-jobs", tenantId],
    queryFn: () => listConnectorJobs(tenantId),
    retry: false,
    refetchInterval: 15_000,
  });

  const enrollM = useMutation({
    mutationFn: () => createEnrollment(tenantId, agentName),
    onSuccess: (result) => {
      setEnrollment(result);
      setAgentName("");
      void qc.invalidateQueries({ queryKey: ["agents", tenantId] });
    },
  });
  const revokeM = useMutation({
    mutationFn: ({ agent, reason }: { agent: Agent; reason: string }) =>
      revokeAgent(tenantId, agent.id, reason),
    onSuccess: () => {
      setRevoking(null);
      void qc.invalidateQueries({ queryKey: ["agents", tenantId] });
    },
  });

  return (
    <div className="space-y-6">
      {enrollment && (
        <EnrollmentCard enrollment={enrollment} onDone={() => setEnrollment(null)} />
      )}

      <section className="rounded border bg-white p-4">
        <h2 className="mb-3 font-semibold">Agenten</h2>
        {agentsQ.isError && <ErrorBox error={agentsQ.error} />}
        {agentsQ.data && (
          <table className="mb-4 w-full border-collapse text-sm">
            <thead>
              <tr className="border-b bg-slate-100 text-left">
                <th className="p-2">Agent</th>
                <th className="p-2">Zustand</th>
                <th className="p-2">SPKI</th>
                <th className="p-2">Zertifikat</th>
                <th className="p-2">Zuletzt gesehen</th>
                <th className="p-2"></th>
              </tr>
            </thead>
            <tbody>
              {agentsQ.data.map((a) => (
                <AgentRow
                  key={a.id}
                  agent={a}
                  asOf={agentsQ.dataUpdatedAt}
                  onRevoke={(agent) => setRevoking({ agent, reason: "" })}
                />
              ))}
              {agentsQ.data.length === 0 && (
                <tr>
                  <td colSpan={6} className="p-4 text-center text-slate-500">
                    Kein Agent angemeldet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}

        {revoking && (
          <form
            className="mb-4 rounded border border-red-300 bg-red-50 p-3"
            onSubmit={(e) => {
              e.preventDefault();
              revokeM.mutate(revoking);
            }}
          >
            <p className="mb-2 text-sm text-red-900">
              „{revoking.agent.name}“ widerrufen. Der Widerruf gilt sofort: die nächste
              Anfrage dieses Agenten wird abgewiesen, und er kann sich auch nicht mehr
              erneuern. Zurück geht es nur über eine neue Anmeldung mit Einmal-Token.
            </p>
            <label className="mb-2 block text-sm">
              <span className="mb-1 block text-red-800">Begründung (Pflicht)</span>
              <input
                required
                minLength={3}
                value={revoking.reason}
                onChange={(e) => setRevoking({ ...revoking, reason: e.target.value })}
                className="w-full rounded border px-2 py-1"
              />
            </label>
            {revokeM.isError && <ErrorBox error={revokeM.error} />}
            <div className="flex gap-2">
              <button
                type="submit"
                disabled={revokeM.isPending}
                className="rounded bg-red-700 px-3 py-1 text-sm text-white disabled:opacity-50"
              >
                Widerrufen
              </button>
              <button
                type="button"
                onClick={() => setRevoking(null)}
                className="rounded border px-3 py-1 text-sm"
              >
                Abbrechen
              </button>
            </div>
          </form>
        )}

        <form
          className="flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            enrollM.mutate();
          }}
        >
          <label className="text-sm">
            <span className="mb-1 block text-slate-600">Neuer Agent</span>
            <input
              required
              value={agentName}
              onChange={(e) => setAgentName(e.target.value)}
              placeholder="dc01.schule.local"
              className="w-72 rounded border px-2 py-1"
            />
          </label>
          <button
            type="submit"
            disabled={enrollM.isPending}
            className="rounded bg-slate-900 px-3 py-1 text-sm text-white disabled:opacity-50"
          >
            Einmal-Token erzeugen
          </button>
        </form>
        {enrollM.isError && <div className="mt-3"><ErrorBox error={enrollM.error} /></div>}
        <p className="mt-3 text-xs text-slate-500">
          <span className="font-medium">Offene Einmal-Token stehen hier nicht.</span> Die
          API bietet keine Liste dafür — bewusst nicht den Token-Wert, aber auch nicht die
          blosse Tatsache, dass eines aussteht. Wer eines erzeugt und weglegt, sieht es
          nirgends mehr; es verfällt nach 24 Stunden von selbst. Ein Endpunkt, der
          ausstehende Anmeldungen ohne ihren Wert nennt, wäre die Abhilfe und fehlt.
        </p>
      </section>

      <section className="rounded border bg-white p-4">
        <h2 className="mb-3 font-semibold">Aufträge</h2>
        <p className="mb-3 text-xs text-slate-500">
          Nur Methode und Zustand — die Nutzlast steht hier nicht. Sie wird nach
          Ausführung gelöscht (<span className="font-mono">payload_purged_at</span>), denn
          darin steht, wessen Passwort gesetzt wurde.
        </p>
        {jobsQ.data && jobsQ.data.length > 0 ? (
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b bg-slate-100 text-left">
                <th className="p-2">Erfasst</th>
                <th className="p-2">Methode</th>
                <th className="p-2">Zustand</th>
                <th className="p-2">Versuche</th>
                <th className="p-2">Nutzlast</th>
                <th className="p-2">Fehler</th>
              </tr>
            </thead>
            <tbody>
              {jobsQ.data.slice(0, 50).map((j) => (
                <tr key={j.id} className="border-b">
                  <td className="p-2 text-xs">{new Date(j.created_at).toLocaleString()}</td>
                  <td className="p-2 font-mono text-xs">{j.method}</td>
                  <td className="p-2">
                    <StatusBadge status={j.state} />
                  </td>
                  <td className="p-2 text-xs">{j.attempts}</td>
                  <td className="p-2 text-xs text-slate-500">
                    {j.payload_purged_at ? "gelöscht" : "vorhanden"}
                  </td>
                  <td className="p-2 text-xs text-red-700">{j.error ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-sm text-slate-500">Kein Auftrag.</p>
        )}
      </section>
    </div>
  );
}
