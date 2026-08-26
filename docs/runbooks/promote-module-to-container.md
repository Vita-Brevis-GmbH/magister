# Runbook: ein Modul in einen eigenen Container promoten (ADR-0008 D5)

**Wann:** Nur *bei Bedarf* — der Default ist und bleibt der Ein-Container-
Monolith (`magister-api` + `magister-web`). Greif erst zu, wenn eines dieser
Kriterien real wird (ADR-0008 D5):

- **eigene Skalierung** — ein Modul erzeugt so viel Last, dass es unabhängig
  skalieren soll;
- **Fehler-Isolation** — ein Modul darf die übrigen nicht mitreissen;
- **eigener Release-Takt / eigenes Team** — ein Modul wird getrennt
  ausgeliefert;
- **getrennte Auslieferung / Lizenzierung** — ein Modul geht an andere Kunden.

Es gibt **zwei Achsen** (D5), nicht verwechseln:

| Achse | Was | Mechanismus |
|------|-----|-------------|
| **Schieber** (Runtime) | Modul für eine Instanz an/aus | Profil + Overrides, `Einstellungen → Module` → 404 `module_disabled` |
| **Container** (Deployment) | welches Image welche Module *mountet* | `MAGISTER_CONTAINER_MODULES` bzw. `git subtree split` |

Beide sind unabhängig. Der Schieber zwingt **nicht** zu Containern.

> **Wichtig (D5):** Ein Modul-Container ist ein **Deployment-Split, kein
> Daten-Split.** Alle Container teilen dieselbe DB, denselben `SESSION_SECRET`,
> `CSRF_SECRET` und `AUDIT_KEY` (identische `MAGISTER_*`-Env). Das ist ein
> *verteiltes System mit geteiltem Secret*, kein isolierter Dienst — die
> Trennung ist betrieblich (Prozess/Skalierung), nicht sicherheitstechnisch.

---

## Variante A — leichter Split: gleiches Image, modul-skalierter Container

Kein Code-Fork. Dasselbe `magister-api`-Image läuft ein zweites Mal, mountet
aber via `MAGISTER_CONTAINER_MODULES` nur ein Modul (plus die immer aktive
`platform`-Basis, damit Auth/Session/`/me` funktionieren). Ein Path-Routing im
Reverse-Proxy schickt die Modul-Requests dorthin.

### 1. Modul-Container hochziehen

Die Overlay-Datei `deploy/compose/docker-compose.split.yml` ist bereits im Repo
(Beispiel: `departments`). Sie referenziert dieselben `.env`-Secrets wie der
Haupt-Container.

```bash
cd /opt/magister/deploy/compose
docker compose -f docker-compose.yml -f docker-compose.split.yml up -d
docker compose ps            # magister-api-departments = Up (healthy)
```

Prüfen, dass der Container nur sein Modul mountet:

```bash
docker compose logs magister-api-departments | grep -i "entrypoint\|uvicorn"
# und intern:
docker compose exec magister-api-departments \
  python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/openapi.json').read()[:0] or 'ok')"
```

Ein Request an ein *nicht* gemountetes Modul (z. B. `/classes`) liefert in
diesem Container **404** — genau richtig, dafür ist er nicht zuständig.

### 2. Reverse-Proxy: das Modul-Präfix umleiten

Der Haupt-`Caddyfile` schickt `/api/*` an `magister-api`. Für den Split leitest
du das Modul-Präfix **davor** an den Modul-Container. In den `Caddyfile`
(Produktion: `deploy/caddy/Caddyfile`, Dev: `deploy/caddy/Caddyfile.dev`) VOR
den bestehenden `handle_path /api/*`-Block einfügen:

```caddy
	# Departments-Modul läuft in einem eigenen Container.
	handle_path /api/departments* {
		reverse_proxy magister-api-departments:8000 {
			header_up X-Forwarded-Host {host}
			header_up X-Forwarded-Proto {scheme}
		}
	}
```

> Reihenfolge zählt: der spezifische `/api/departments*`-Block muss **vor** dem
> generischen `/api/*` stehen, sonst greift der allgemeine zuerst.

Caddy neu laden:

```bash
docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile
# (dev: --config /etc/caddy/Caddyfile.dev)
```

Das Frontend bleibt unverändert: es ruft weiter `/api/departments` — nur der
Proxy entscheidet jetzt, welcher Container antwortet. `GET /me/modules` (die
Nav) läuft weiter über den Haupt-Container und zeigt die logisch aktivierten
Module; der Klick landet über den Proxy im Modul-Container.

### 3. Rückbau

```bash
docker compose -f docker-compose.yml -f docker-compose.split.yml stop magister-api-departments
docker compose -f docker-compose.yml -f docker-compose.split.yml rm -f magister-api-departments
# Caddy-Block wieder entfernen + caddy reload
```

Nichts an den Daten ändert sich — der Haupt-Container serviert das Modul sofort
wieder mit.

---

## Variante B — echter Split: `git subtree split` in ein eigenes Repo

Wenn das Modul wirklich getrennt ausgeliefert/lizenziert wird, wandert sein Code
mechanisch in ein eigenes Repo — der Weg, den `cockpit/` (ADR-0003) vorzeichnet.
Möglich, weil die Module mit sauberen Grenzen gebaut sind (Modul-Vertrags-CI,
ADR-0008 D8): ein Modul ist ein `modules/<id>.py`-Manifest über
`routers/…`-Paketen, ohne Quer-Importe zwischen Fachmodulen.

Grober Ablauf (einmalig, mit Org-Permissions):

```bash
# 1. Den Modul-Teilbaum als eigene History extrahieren
git subtree split --prefix=apps/api/magister_api/routers <branch> -b split-departments
# (bzw. die konkreten Modul-Dateien: modules/departments.py + routers/departments*,
#  services/department_people*, repositories/department*, models/department*,
#  schemas/department* — siehe Modul-Grenzen)

# 2. In das neue Repo pushen
git push git@github.com:vita-brevis-gmbh/magister-departments.git split-departments:main
```

Danach im neuen Repo einen schlanken FastAPI-Einstieg bauen, der NUR die
Modul-Router plus eine dünne Auth-/Session-Schicht mountet, und weiterhin auf
dieselbe Magister-DB + dieselben Secrets zeigt (D5). Konventionen (uv, ruff,
pyright, Alembic, Caddy) identisch zu Magister übernehmen — Onboarding-Reibung
minimal, wie bei `cockpit/`.

**Bevor du B nimmst, prüfe ehrlich, ob A reicht.** A liefert eigene Skalierung
und Fehler-Isolation ohne zweite Codebase; B lohnt nur bei echt getrenntem
Release/Team/Lizenz — sonst zahlst du den Cross-Repo-Versions-Bump-Preis
(ADR-0003 „Negativ") ohne Gegenwert.
