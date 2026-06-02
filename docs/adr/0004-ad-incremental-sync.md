# ADR 0004: AD-Diff-Sync (incremental sync via `whenChanged`)

**Status:** Akzeptiert · 2026-06-02
**Kontext:** M4 — Scale & Operations Maturity, Performance-Block

## Problem

Bei wachsender Userzahl (mehrere Schulträger × bis zu ~5k User) wird der wiederkehrende Full-Sync teuer: jeder Tick zieht den gesamten Userverzeichnis-Subtree aus AD, parst alles, schreibt alles upsert. Für die meisten Ticks ändert sich genau ein Bruchteil. Belastet AD-DC, Magister-DB-Connection-Pool und die Audit-Tabelle.

## Entscheidung

Wir führen einen zweiten Sync-Modus ein: `incremental`. Cursor ist der LDAP-Attribut `whenChanged` (Generalized Time, repliziert über alle DCs).

**Mechanik:**

1. `AdSyncState` (Singleton-Row) speichert `last_when_changed`
2. `AdClient.search_users(changed_since=...)` ergänzt den LDAP-Filter um `(whenChanged>=<ts>)`
3. `AdSyncService.sync_all(mode='incremental')` nutzt den Cursor, falls vorhanden — sonst fällt es automatisch auf `full` zurück
4. Nach erfolgreichem Sync wird `last_when_changed = max(records.when_changed)` persistiert
5. `last_full_sync_at` wird nur beim Full-Modus gesetzt

**Pflicht-Garantie:** Der Scheduler muss in einem definierten Intervall (z.B. wöchentlich) einen Full-Sync ausführen, weil…

## Konsequenzen

**Positiv:**
- Schnellere Ticks: nur geänderte User werden gezogen (typisch < 1% pro Tick)
- DC-Last sinkt drastisch — wichtig bei Off-Site-DCs mit schmaler Leitung
- Audit-Events kleiner

**Negativ — bewusst akzeptiert:**
- **Deletion-Blindness**: `whenChanged` zeigt keine Tombstones. Gelöschte AD-User bleiben im `ad_user_cache` bis zum nächsten Full-Sync. Mitigation: wöchentlicher Full-Sync.
- **Computer-OU-Walk** läuft nur beim Full-Sync. Bei einer Diff-Iteration kann ein neu erfasstes Device am User-Record stale sein. Akzeptiert (Devices ändern sich selten).
- **Clock-Skew DC↔Magister**: Falls Uhren auseinanderlaufen, könnten Records knapp am Cursor verpasst werden. Mitigation: ein 60-Sekunden-Sicherheitsfenster (Cursor wird im nächsten Tick beim Schreiben um 60s zurückversetzt) — *in M4.future als Folge-Optimierung*.

## Alternativen verworfen

- **DirSync-Control** (LDAP_SERVER_DIRSYNC_OID): präziser, liefert auch Deletions, braucht aber `DS-Replication-Get-Changes` Privilege. Operativ schwer durchzusetzen bei Schul-AD.
- **uSNChanged**: per-DC, nicht repliziert. Würde bei Multi-DC-Setups falsche Ergebnisse liefern.
- **Webhook von AD nach Magister**: AD bietet das nicht standardisiert; Workarounds via ETW oder Event-Subscriptions sind brüchig.

## Migration

`0010_ad_sync_state` — singleton-Tabelle mit `CHECK (id = 1)`.

## Rollout-Plan

1. Deploy mit `mode='full'` als Default (Verhalten unverändert)
2. Scheduler manuell auf `incremental` umstellen (Settings-Update)
3. Beobachten: Cursor-Drift, Synced-Count pro Tick, Audit-Event-Größe
4. Wenn stabil: Default-Mode für Scheduler auf `incremental` setzen, Full-Sync 1× pro Woche per Cron
