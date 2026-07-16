# Runbook: Server auf den kompletten aktuellen `main`-Stand bringen

**Wann:** Wenn ein Teammitglied „seine" Änderungen im Deployment nicht sieht,
obwohl alles in `main` liegt. Ursache ist praktisch immer ein **veraltetes
Deployment** (altes Image / alter Checkout), nicht ein fehlender Merge.

**Stand, der ausgerollt werden soll:** `main` @ `ffe5730` (enthält den
kompletten Installer aus PR #49/#50 **und** die letzten sechs Fixes:
Audit-Log-Endpoint, Geräte-Namensauflösung, Benutzerverwaltung im Top-Menü,
Lehrer-Import-Härtung, selbstsigniertes Caddy-TLS).

> **Wichtig zuerst:** Es gibt nichts zu mergen. `main` ist die einzige
> Quelle der Wahrheit und vollständig. Beide Personen ziehen einfach denselben
> `main` und deployen neu — dann sehen beide alles.

---

## 0. Vorbedingung (einmal pro Person, lokal)

Prüfen, dass ihr wirklich auf demselben Commit seid:

```bash
git fetch origin
git checkout main
git pull --ff-only origin main
git log --oneline -1        # muss ffe5730 (oder neuer) zeigen
```

Sehen beide dieselbe Commit-ID → ihr habt garantiert denselben Code.

---

## 1. Auf dem Server: Backup (Pflicht)

```bash
cd /opt/magister/deploy/compose          # Pfad eurer Installation

sudo mkdir -p /backup
sudo chown "$(id -un)":"$(id -gn)" /backup
docker compose exec postgres pg_dump -U magister magister \
  | gzip > /backup/magister-$(date +%Y%m%d-%H%M).sql.gz
ls -lh /backup/                           # Datei da und > 0 Byte?
```

---

## 2. Neuesten `main` auf den Server holen

```bash
cd /opt/magister
sudo git fetch origin
sudo git checkout main
sudo git pull --ff-only origin main
git log --oneline -1                      # ffe5730 – gleicher Commit wie lokal
```

---

## 3. Images aktualisieren

**Variante A – Images von GHCR ziehen** (wenn CI die Tags gebaut hat):

```bash
cd /opt/magister/deploy/compose
docker compose pull magister-api magister-web
```

**Variante B – Images auf dem Server selbst bauen** (immer verlässlich, auch
ohne GHCR):

```bash
cd /opt/magister/deploy/compose
docker compose -f docker-compose.yml -f docker-compose.build.yml \
  build --no-cache magister-api magister-web
```

> `--no-cache` erzwingt einen frischen Build – so kann kein alter Layer den
> alten Frontend-/Backend-Stand „festhalten". Genau dieser Cache ist meist der
> Grund, warum jemand seine Änderungen nicht sieht.

---

## 4. Datenbank-Migrationen (bis `0028`)

```bash
cd /opt/magister/deploy/compose
docker compose run --rm magister-api alembic upgrade head
```

Erwartete Endzeile: `... -> 0028_device_is_loan`. Alle Migrationen sind
additiv; der Container-Entrypoint führt `alembic upgrade head` beim Start
ohnehin automatisch aus – dieser Schritt ist die kontrollierte Variante vorab.

---

## 5. Stack neu starten

```bash
cd /opt/magister/deploy/compose
docker compose up -d
docker compose ps                         # api, web, caddy, postgres = Up
```

---

## 6. TLS-Hinweis (neu: immer selbstsigniert)

Caddy nutzt jetzt **immer** ein selbstsigniertes Zertifikat (`tls internal`,
kein ACME/Let's-Encrypt). Folgen daraus:

- `MAGISTER_ACME_EMAIL` in der `.env` wird **nicht mehr gebraucht** (kann drin
  bleiben, wird ignoriert).
- `MAGISTER_PUBLIC_HOSTNAME` muss auf den **exakten Host oder die IP** zeigen,
  über die ihr den Server erreicht – damit das Zertifikats-Subject passt.
- Beim ersten Aufruf zeigt der Browser eine einmalige
  „Zertifikat nicht vertrauenswürdig"-Warnung → einmal manuell akzeptieren.

Kein separates `-f docker-compose.selfsigned.yml` nötig – der normale
`docker-compose.yml` ist jetzt schon selbstsigniert.

---

## 7. Verifikation (beide prüfen dasselbe)

```bash
# Health
curl -skf https://<host-oder-ip>/api/healthz && echo OK

# Die neuen Fixes sichtbar?
```

Im Browser (als Admin/Schulleitung/SMI) einloggen und prüfen:

- **Benutzerverwaltung** liegt oben in der Navileiste (nicht mehr unter
  „Einstellungen ▾").
- **Audit-Log** (Einstellungen → Audit-Log) lädt Daten statt „Etwas ist
  schiefgelaufen".
- **Geräte → Zuweisen**: die aktuell zugewiesene Person erscheint mit **Name**,
  nicht als GUID.
- **Lehrer-Bulk-Import** läuft ohne Fehlermeldung durch; die Lehrpersonen
  erscheinen sofort in Magister.

Zeigt der Browser noch Altes: **Hard-Reload** (Strg/Cmd+Shift+R) – der
Service-Worker/HTTP-Cache im Browser hält sonst das alte SPA-Bundle.

---

## Wenn wirklich mal etwas nicht in `main` sein sollte

Schnellcheck, ob ein bestimmter Commit schon in `main` steckt:

```bash
git merge-base --is-ancestor <commit-sha> origin/main && echo "IN main" || echo "FEHLT"
```

Und um zu sehen, ob ein Branch echte, noch nicht gemergte Arbeit hat (nicht nur
älteren Stand):

```bash
git log --oneline origin/main..origin/<branch-name>     # zeigt NUR unmerged Commits
git cherry origin/main origin/<branch-name>             # '-' = inhaltlich schon in main
```
