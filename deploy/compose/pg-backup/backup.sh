#!/usr/bin/env bash
# Tägliche Sicherung einer Einzelinstallation (ADR-0016 D9).
#
#     pg_dump --format=custom  →  age -r <öffentlicher Schlüssel>  →  Volume
#
# Zwei Änderungen gegenüber der ersten Fassung, beide aus ADR-0016:
#
# 1. **Verschlüsselt.** Ein Dump mit Personendaten von Minderjährigen liegt
#    nicht im Klartext auf einem Volume, das jemand auf einen Backup-Host
#    rsyncen soll. Verschlüsselt wird mit dem *öffentlichen* age-Schlüssel des
#    Betreibers: dieser Container kann damit schreiben, aber nichts lesen —
#    wer ihn übernimmt, bekommt keine alten Sicherungen entschlüsselt.
# 2. **--format=custom statt plain|gzip.** Damit lässt sich der Dump mit
#    pg_restore einzeln und selektiv einspielen (eine Tabelle, ein Schema),
#    und `magister-cli backup verify` kann ihn prüfen.
#
# MAGISTER_BACKUP_AGE_RECIPIENT ist **Pflicht**. Fehlt er, bricht der Lauf ab,
# statt unverschlüsselt zu schreiben — eine Warnung im Container-Log liest
# niemand, und die Datei läge trotzdem da.
#
# Der PRIVATE Schlüssel gehört NICHT auf diese Maschine. Er wird getrennt
# verwahrt; ohne ihn ist keine Wiederherstellung möglich, also gehört er in
# denselben Ablauf wie jedes andere Notfallgeheimnis.
set -euo pipefail

: "${POSTGRES_HOST:?}"
: "${POSTGRES_USER:?}"
: "${POSTGRES_PASSWORD:?}"
: "${POSTGRES_DB:?}"
: "${BACKUP_RETENTION_DAYS:=14}"

if [[ -z "${MAGISTER_BACKUP_AGE_RECIPIENT:-}" ]]; then
    echo "[pg-backup] FEHLER: MAGISTER_BACKUP_AGE_RECIPIENT ist nicht gesetzt." >&2
    echo "[pg-backup] Ohne öffentlichen age-Schlüssel würde unverschlüsselt auf" >&2
    echo "[pg-backup] das Volume geschrieben. Das wird nicht gemacht." >&2
    echo "[pg-backup] Erzeugen: age-keygen -o backup-identity.txt (auf dem" >&2
    echo "[pg-backup] Backup-Host, NICHT hier), dann den 'Public key' hier setzen." >&2
    exit 1
fi
if [[ ! "$MAGISTER_BACKUP_AGE_RECIPIENT" =~ ^age1[0-9a-z]{58}$ ]]; then
    echo "[pg-backup] FEHLER: MAGISTER_BACKUP_AGE_RECIPIENT ist kein age-Schlüssel." >&2
    exit 1
fi

BACKUP_DIR=/var/backups/magister
mkdir -p "$BACKUP_DIR"

stamp=$(date -u +%Y%m%dT%H%M%SZ)
out="${BACKUP_DIR}/${POSTGRES_DB}-${stamp}.dump.age"
# Erst unter einem Arbeitsnamen: sonst liegt bei einem Abbruch eine halbe
# Datei da, die aussieht wie eine Sicherung.
partial="${out}.partial"

export PGPASSWORD="$POSTGRES_PASSWORD"
echo "[pg-backup] Sicherung startet: ${out}"

# pipefail ist gesetzt: scheitert pg_dump, scheitert die Kette.
pg_dump --host="$POSTGRES_HOST" --username="$POSTGRES_USER" \
        --dbname="$POSTGRES_DB" --no-owner --no-privileges --format=custom \
    | age -r "$MAGISTER_BACKUP_AGE_RECIPIENT" -o "$partial"

if [[ ! -s "$partial" ]]; then
    rm -f "$partial"
    echo "[pg-backup] FEHLER: die Sicherung ist leer." >&2
    exit 1
fi

mv "$partial" "$out"
# Prüfsumme über die VERSCHLÜSSELTE Datei: damit lässt sich später feststellen,
# ob das Volume sie unverändert hält, ohne sie entschlüsseln zu müssen.
sha256sum "$out" | sed "s| .*/| |" >> "${BACKUP_DIR}/PRUEFSUMMEN.sha256"

echo "[pg-backup] geschrieben: $(du -h "$out" | cut -f1)"

# Aufbewahrung, best effort. Auf einer Einzelinstallation liegt das Löschrecht
# hier — anders als in der gehosteten Variante (ADR-0016 D2), wo es
# ausdrücklich auf einer anderen Maschine liegt.
find "$BACKUP_DIR" -type f -name "*.dump.age" -mtime "+${BACKUP_RETENTION_DAYS}" -print -delete
find "$BACKUP_DIR" -type f -name "*.dump.age.partial" -mtime +1 -print -delete
# Reste der alten, unverschlüsselten Fassung: einmalig melden, nicht löschen.
if compgen -G "${BACKUP_DIR}/*.sql.gz" >/dev/null; then
    echo "[pg-backup] HINWEIS: es liegen noch unverschlüsselte *.sql.gz aus der" >&2
    echo "[pg-backup] vorherigen Fassung im Volume. Prüfen und entfernen." >&2
fi

echo "[pg-backup] fertig"
