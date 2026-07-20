# Runbook: Webserver-TLS-Zertifikat importieren

Magister terminiert HTTPS über den Caddy-Reverse-Proxy. Standardmässig stellt
Caddy ein **selbstsigniertes** Zertifikat aus seiner internen CA aus (kein ACME,
funktioniert offline). Für den Produktivbetrieb kann ein **gültiges** Zertifikat
importiert werden — sobald eines hinterlegt ist, serviert Caddy dieses statt des
selbstsignierten.

## Wie es funktioniert

- Der Admin importiert ein Zertifikat unter **Einstellungen → System →
  TLS-Zertifikat (Webserver)** — entweder als PEM (Zertifikatskette + privater
  Schlüssel) oder als PFX/PKCS#12 (Base64) mit optionalem Passwort.
- Die API validiert, dass der Schlüssel zum Leaf-Zertifikat passt, speichert die
  Kette (öffentlich) und den Schlüssel (pgcrypto-verschlüsselt) und **schreibt**
  Zertifikat + Schlüssel in das gemeinsame Volume `web_certs` (`/certs`):
  `tls.pem`, `tls.key` (0600) sowie das Caddy-Snippet `tls.caddy`.
- Ist kein Zertifikat hinterlegt, schreibt die API stattdessen `tls internal` in
  `tls.caddy` und entfernt eventuell vorhandene `tls.pem`/`tls.key` →
  selbstsignierter Fallback.
- Der Caddyfile bindet dieses Snippet ein (`import /certs/tls.caddy`). Der
  Caddy-Container wartet beim Start, bis die API das Snippet geschrieben hat.

## Änderung anwenden

Ein neu importiertes (oder entferntes) Zertifikat wird von Caddy erst nach einem
Reload übernommen:

```bash
docker compose -f deploy/compose/docker-compose.yml restart caddy
```

(Die API aktualisiert die Dateien sofort; nur Caddy muss neu laden.)

## Formate

- **PEM**: Feld „Zertifikat" = vollständige Kette (Leaf zuerst, danach
  Intermediate/Root), Feld „Privater Schlüssel" = unverschlüsselter PEM-Key
  (`-----BEGIN PRIVATE KEY-----`).
- **PFX/PKCS#12**: Datei Base64-kodieren (`base64 -w0 cert.pfx`) und einfügen,
  Passwort separat angeben. Kette und Schlüssel werden serverseitig extrahiert.

## Fehlerbilder

| Symptom (HTTP 422) | Ursache |
|---|---|
| `invalid_certificate` | Zertifikats-PEM nicht lesbar |
| `invalid_private_key` | Schlüssel-PEM nicht lesbar (oder passwortgeschützt) |
| `key_cert_mismatch` | Schlüssel passt nicht zum Zertifikat |
| `cert_and_key_required` | Nur eines von beiden gesendet |
| `invalid_pfx` | PFX/Base64/Passwort falsch |

## Sicherheit

- Der private Schlüssel wird nie geloggt, nie im Audit-Payload gespeichert und
  nie über die API zurückgegeben (`GET /admin/app-settings` liefert nur das Flag
  `web_tls_cert_set`).
- `tls.key` wird mit `0600` geschrieben und liegt nur im internen `web_certs`
  Volume (kein Host-Mount, kein öffentlicher Port).
