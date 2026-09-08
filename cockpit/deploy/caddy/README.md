# Konsolen-Listener

Site-Block für die Management-Adresse (ADR-0015 D1). Voraussetzungen, alle
zwingend — ohne sie startet Caddy nicht, und das ist beabsichtigt:

| Datei im `/certs`-Volume | Woher |
|---|---|
| `platform-ca.pem` | Root- plus Intermediate-Zertifikat der Plattform-CA (öffentlicher Teil), siehe [`docs/runbooks/platform-ca.md`](../../../docs/runbooks/platform-ca.md) |
| `console.pem` / `console-key.pem` | Serverzertifikat für den Hostnamen der Konsole, ausgestellt vom Operator-Intermediate |

Operator-Zertifikate werden aus demselben Intermediate ausgestellt und im
Browser installiert. Ohne eines kommt der TLS-Handshake nicht zustande.

Das Marker-Verfahren: dieser Block setzt `X-Magister-Management` auf den Wert
von `COCKPIT_MANAGEMENT_MARKER`; die Anwendung weist alles ohne diesen Wert mit
`404` ab. Der Marker ist **keine** Zugangsberechtigung — er belegt nur, dass
die Anfrage durch diesen Block gelaufen ist. Beide Seiten müssen denselben Wert
haben, sonst startet die Anwendung nicht (bei leerem Marker) oder antwortet
durchgehend mit 404 (bei abweichendem).
