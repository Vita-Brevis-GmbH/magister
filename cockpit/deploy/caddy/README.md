# Konsolen-Listener

Site-Block für die Management-Adresse (ADR-0015 D1). Voraussetzungen, alle
zwingend — ohne sie startet Caddy nicht, und das ist beabsichtigt:

| Datei im `/certs`-Volume | Woher |
|---|---|
| `platform-ca.pem` | **Nur** das Operator-Intermediate der Plattform-CA (öffentlicher Teil), siehe [`docs/runbooks/platform-ca.md`](../../../docs/runbooks/platform-ca.md) |
| `console.pem` / `console-key.pem` | Serverzertifikat für den Hostnamen der Konsole, ausgestellt vom Operator-Intermediate |

Operator-Zertifikate werden aus demselben Intermediate ausgestellt und im
Browser installiert. Ohne eines kommt der TLS-Handshake nicht zustande.

**Warum nur das Intermediate und nicht die Wurzel:** was im Trust-Pool liegt,
ist ein Vertrauensanker. Läge die Wurzel darin, genügte dem Listener jedes
Zertifikat, das irgendwo unter ihr hängt — auch eines aus dem
Connector-Zweig, und davon hat jeder Kunde eines auf seinem Agenten-Server.
Die Anwendung wiese es danach ab (unbekanntes Zertifikat, keine Sitzung),
aber die zweite von drei Schichten hätte nicht gehalten. Nachgemessen mit
`openssl verify`: mit der Wurzel im Pool geht ein Agentenzertifikat durch,
mit nur dem Operator-Intermediate nicht.

Das Marker-Verfahren: dieser Block setzt `X-Magister-Management` auf den Wert
von `COCKPIT_MANAGEMENT_MARKER`; die Anwendung weist alles ohne diesen Wert mit
`404` ab. Der Marker ist **keine** Zugangsberechtigung — er belegt nur, dass
die Anfrage durch diesen Block gelaufen ist. Beide Seiten müssen denselben Wert
haben, sonst startet die Anwendung nicht (bei leerem Marker) oder antwortet
durchgehend mit 404 (bei abweichendem).
