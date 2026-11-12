#!/usr/bin/env bash
# Builds the *.dc.html artboards for the Global-Admin-Konsole mockup.
# The token block below is lifted verbatim from apps/web (tailwind.config.ts +
# index.css) so the mockup matches the shipped UI. Edit here, re-run, re-seed.
set -euo pipefail
cd "$(dirname "$0")"

head_block() { cat <<'EOF'
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400..700&display=swap">
  <style>
    * { box-sizing: border-box; }
    body {
      margin: 0; background: #ffffff; color: #020817;
      font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
      font-size: 14px; line-height: 20px; -webkit-font-smoothing: antialiased;
    }
    a { color: #0f172a; text-decoration: none; }
    a:hover { color: #020817; text-decoration: underline; text-underline-offset: 4px; }
    .serif { font-family: Fraunces, ui-serif, Georgia, Cambria, "Times New Roman", Times, serif; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12.5px; }
    .shell { max-width: 1280px; margin: 0 auto; padding: 0 16px; }
    .muted { color: #64748b; }
    .h1 { font-size: 24px; line-height: 32px; font-weight: 600; letter-spacing: -0.025em; margin: 0; }
    .h2 { font-size: 20px; line-height: 20px; font-weight: 600; letter-spacing: -0.025em; margin: 0; }
    .topbar { height: 56px; background: #0f172a; color: #f8fafc; }
    .navlink { padding: 6px 12px; border-radius: 6px; color: #94a3b8; font-weight: 500; }
    .navlink.active { background: rgba(248, 250, 252, 0.1); color: #f8fafc; }
    .card { border: 1px solid #e2e8f0; border-radius: 8px; background: #ffffff; box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05); }
    .btn { display: inline-flex; align-items: center; justify-content: center; gap: 8px; height: 40px; padding: 0 16px; border: 0; border-radius: 6px; font-size: 14px; font-weight: 500; white-space: nowrap; cursor: pointer; font-family: inherit; }
    .btn-primary { background: #0f172a; color: #f8fafc; }
    .btn-outline { background: #ffffff; color: #020817; border: 1px solid #e2e8f0; }
    .btn-ghost { background: transparent; color: #64748b; }
    .btn-sm { height: 36px; padding: 0 12px; }
    .input { display: flex; align-items: center; gap: 8px; height: 40px; width: 100%; border: 1px solid #e2e8f0; border-radius: 6px; background: #ffffff; padding: 8px 12px; font-size: 14px; }
    .ph { color: #64748b; }
    .label { display: block; font-size: 14px; font-weight: 500; line-height: 16px; margin-bottom: 6px; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th { height: 48px; padding: 0 16px; text-align: left; vertical-align: middle; font-weight: 500; color: #64748b; border-bottom: 1px solid #e2e8f0; }
    td { padding: 16px; vertical-align: middle; border-bottom: 1px solid #e2e8f0; }
    tbody tr:last-child td { border-bottom: 0; }
    .pill { display: inline-flex; align-items: center; border-radius: 9999px; padding: 2px 10px; font-size: 12px; line-height: 16px; font-weight: 500; }
    .pill-ok { background: #ecfdf5; color: #047857; box-shadow: inset 0 0 0 1px #a7f3d0; }
    .pill-muted { background: #f1f5f9; color: #475569; box-shadow: inset 0 0 0 1px #e2e8f0; }
    .pill-warn { background: #fffbeb; color: #b45309; box-shadow: inset 0 0 0 1px #fde68a; }
    .pill-danger { background: #fff1f2; color: #be123c; box-shadow: inset 0 0 0 1px #fecdd3; }
    .tab { padding: 10px 2px; margin-right: 24px; font-weight: 500; color: #64748b; border-bottom: 2px solid transparent; }
    .tab.active { color: #020817; border-bottom-color: #0f172a; }
    .note { border: 1px solid #e2e8f0; border-left: 3px solid #0f172a; border-radius: 6px; background: #f8fafc; padding: 12px 14px; }
    .kv { display: grid; grid-template-columns: 200px minmax(0, 1fr); gap: 10px 24px; }
  </style>
</helmet>
EOF
}

tail_block() { printf '%s\n' '</x-dc>' '</body>' '</html>'; }

emit() { local out="$1"; { head_block; cat; tail_block; } > "$out"; echo "  built $out"; }

# ---------------------------------------------------------------- Kundenliste
emit Main.dc.html <<'EOF'
<div class="topbar">
  <div class="shell" style="display: flex; height: 56px; align-items: center; justify-content: space-between;">
    <div style="display: flex; align-items: center; gap: 28px;">
      <div style="display: flex; align-items: baseline; gap: 8px;">
        <span class="serif" style="font-size: 18px; font-weight: 600; letter-spacing: -0.025em;">Magister Console</span>
        <span style="font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: #64748b;">Vita Brevis</span>
      </div>
      <nav style="display: flex; align-items: center; gap: 4px; font-size: 14px;">
        <span class="navlink active">Kunden</span>
        <span class="navlink">Vorlagen</span>
        <span class="navlink">Rechte</span>
        <span class="navlink">Module</span>
        <span class="navlink">Betrieb</span>
        <span class="navlink">Audit</span>
      </nav>
    </div>
    <div style="display: flex; align-items: center; gap: 12px;">
      <span class="pill" style="background: rgba(248, 250, 252, 0.1); color: #e2e8f0; box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.25);">Global Admin</span>
      <span style="display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px; border-radius: 9999px; background: #334155; color: #f8fafc; font-size: 11px; font-weight: 600;">MH</span>
    </div>
  </div>
</div>

<div class="shell" style="padding-top: 32px; padding-bottom: 32px;">
  <header style="display: flex; align-items: flex-start; justify-content: space-between; gap: 24px;">
    <div>
      <h1 class="serif h1">Kunden</h1>
      <p class="muted" style="margin: 6px 0 0;">8 Mandanten &middot; jede Trennung auf Datenbankebene &middot; Beispieldaten</p>
    </div>
    <div style="display: flex; gap: 8px;">
      <button class="btn btn-outline" type="button">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M3 21v-5h5"/></svg>
        Status neu laden
      </button>
      <button class="btn btn-primary" type="button">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14"/><path d="M12 5v14"/></svg>
        Kunde erfassen
      </button>
    </div>
  </header>

  <div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; margin-top: 24px;">
    <div class="card" style="padding: 16px 18px;">
      <div style="display: flex; align-items: center; justify-content: space-between;">
        <span class="muted" style="font-size: 13px; font-weight: 500;">Migration ausstehend</span>
        <span class="pill pill-warn">1</span>
      </div>
      <p style="margin: 8px 0 0; font-weight: 500;">Gemeinde Degersheim</p>
      <p class="muted mono" style="margin: 2px 0 0;">0042 &rarr; 0043</p>
    </div>
    <div class="card" style="padding: 16px 18px;">
      <div style="display: flex; align-items: center; justify-content: space-between;">
        <span class="muted" style="font-size: 13px; font-weight: 500;">AD-Sync-Fehler</span>
        <span class="pill pill-danger">1</span>
      </div>
      <p style="margin: 8px 0 0; font-weight: 500;">Toggenburg Energie AG</p>
      <p class="muted" style="margin: 2px 0 0;">Kein DC erreichbar, seit 38 Min</p>
    </div>
    <div class="card" style="padding: 16px 18px;">
      <div style="display: flex; align-items: center; justify-content: space-between;">
        <span class="muted" style="font-size: 13px; font-weight: 500;">In Bereitstellung</span>
        <span class="pill pill-muted">1</span>
      </div>
      <p style="margin: 8px 0 0; font-weight: 500;">Schulgemeinde Nesslau</p>
      <p class="muted" style="margin: 2px 0 0;">Schema anlegen &middot; Schritt 2 von 5</p>
    </div>
  </div>

  <div style="display: flex; align-items: center; gap: 8px; margin-top: 24px;">
    <div class="input" style="flex-grow: 1;">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
      <span class="ph">Kunde, Subdomain oder Schema suchen</span>
    </div>
    <div class="input" style="width: 176px; justify-content: space-between;">
      <span>Alle Status</span>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
    </div>
    <div class="input" style="width: 176px; justify-content: space-between;">
      <span>Alle Profile</span>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
    </div>
  </div>

  <div class="card" style="margin-top: 16px; overflow: hidden;">
    <table>
      <thead>
        <tr>
          <th style="width: 270px;">Kunde</th>
          <th style="width: 190px;">Zugang</th>
          <th style="width: 86px;">Profil</th>
          <th style="width: 190px;">Datenbank-Trennung</th>
          <th style="width: 96px;">Schema</th>
          <th style="width: 130px;">AD-Sync</th>
          <th style="width: 120px;">Status</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>
            <div style="font-weight: 500;">Gemeinde Wattwil</div>
            <div class="muted" style="font-size: 13px;">4 Standorte &middot; 1 284 Benutzer</div>
          </td>
          <td class="mono">wattwil.magister.ch</td>
          <td>Schule</td>
          <td>
            <div>Eigenes Schema</div>
            <div class="muted mono">t_wattwil</div>
          </td>
          <td class="mono">0043</td>
          <td class="muted">vor 4 Min</td>
          <td><span class="pill pill-ok">Aktiv</span></td>
          <td>
            <div style="display: flex; justify-content: flex-end; gap: 8px;">
              <button class="btn btn-outline btn-sm" type="button" title="Im Kundenkontext &ouml;ffnen" style="padding: 0 10px;"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg></button>
              <button class="btn btn-outline btn-sm" type="button">Verwalten</button>
            </div>
          </td>
        </tr>
        <tr>
          <td>
            <div style="font-weight: 500;">Stadt Uzwil</div>
            <div class="muted" style="font-size: 13px;">7 Standorte &middot; 2 010 Benutzer</div>
          </td>
          <td class="mono">uzwil.magister.ch</td>
          <td>Schule</td>
          <td>
            <div>Eigenes Schema</div>
            <div class="muted mono">t_uzwil</div>
          </td>
          <td class="mono">0043</td>
          <td class="muted">vor 7 Min</td>
          <td><span class="pill pill-ok">Aktiv</span></td>
          <td>
            <div style="display: flex; justify-content: flex-end; gap: 8px;">
              <button class="btn btn-outline btn-sm" type="button" title="Im Kundenkontext &ouml;ffnen" style="padding: 0 10px;"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg></button>
              <button class="btn btn-outline btn-sm" type="button">Verwalten</button>
            </div>
          </td>
        </tr>
        <tr>
          <td>
            <div style="font-weight: 500;">Schulgemeinde Flawil</div>
            <div class="muted" style="font-size: 13px;">5 Standorte &middot; 1 640 Benutzer</div>
          </td>
          <td class="mono">flawil.magister.ch</td>
          <td>Schule</td>
          <td>
            <div>Eigene Datenbank</div>
            <div class="muted mono">magister_flawil</div>
          </td>
          <td class="mono">0043</td>
          <td class="muted">vor 2 Min</td>
          <td><span class="pill pill-ok">Aktiv</span></td>
          <td>
            <div style="display: flex; justify-content: flex-end; gap: 8px;">
              <button class="btn btn-outline btn-sm" type="button" title="Im Kundenkontext &ouml;ffnen" style="padding: 0 10px;"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg></button>
              <button class="btn btn-outline btn-sm" type="button">Verwalten</button>
            </div>
          </td>
        </tr>
        <tr>
          <td>
            <div style="font-weight: 500;">Gemeinde Degersheim</div>
            <div class="muted" style="font-size: 13px;">2 Standorte &middot; 430 Benutzer</div>
          </td>
          <td class="mono">degersheim.magister.ch</td>
          <td>Schule</td>
          <td>
            <div>Eigenes Schema</div>
            <div class="muted mono">t_degersheim</div>
          </td>
          <td><span class="pill pill-warn mono">0042</span></td>
          <td class="muted">vor 11 Min</td>
          <td><span class="pill pill-ok">Aktiv</span></td>
          <td>
            <div style="display: flex; justify-content: flex-end; gap: 8px;">
              <button class="btn btn-outline btn-sm" type="button" title="Im Kundenkontext &ouml;ffnen" style="padding: 0 10px;"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg></button>
              <button class="btn btn-outline btn-sm" type="button">Verwalten</button>
            </div>
          </td>
        </tr>
        <tr>
          <td>
            <div style="font-weight: 500;">Alpstein Treuhand AG</div>
            <div class="muted" style="font-size: 13px;">3 Abteilungen &middot; 96 Benutzer</div>
          </td>
          <td class="mono">alpstein.magister.ch</td>
          <td>Firma</td>
          <td>
            <div>Eigenes Schema</div>
            <div class="muted mono">t_alpstein</div>
          </td>
          <td class="mono">0043</td>
          <td class="muted">vor 5 Min</td>
          <td><span class="pill pill-ok">Aktiv</span></td>
          <td>
            <div style="display: flex; justify-content: flex-end; gap: 8px;">
              <button class="btn btn-outline btn-sm" type="button" title="Im Kundenkontext &ouml;ffnen" style="padding: 0 10px;"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg></button>
              <button class="btn btn-outline btn-sm" type="button">Verwalten</button>
            </div>
          </td>
        </tr>
        <tr>
          <td>
            <div style="font-weight: 500;">Toggenburg Energie AG</div>
            <div class="muted" style="font-size: 13px;">6 Abteilungen &middot; 212 Benutzer</div>
          </td>
          <td class="mono">tbenergie.magister.ch</td>
          <td>Firma</td>
          <td>
            <div>Eigenes Schema</div>
            <div class="muted mono">t_tbenergie</div>
          </td>
          <td class="mono">0043</td>
          <td><span class="pill pill-danger">Kein DC</span></td>
          <td><span class="pill pill-ok">Aktiv</span></td>
          <td>
            <div style="display: flex; justify-content: flex-end; gap: 8px;">
              <button class="btn btn-outline btn-sm" type="button" title="Im Kundenkontext &ouml;ffnen" style="padding: 0 10px;"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg></button>
              <button class="btn btn-outline btn-sm" type="button">Verwalten</button>
            </div>
          </td>
        </tr>
        <tr>
          <td>
            <div style="font-weight: 500;">Schulgemeinde Nesslau</div>
            <div class="muted" style="font-size: 13px;">Erfasst am 04.09.2026</div>
          </td>
          <td class="mono">nesslau.magister.ch</td>
          <td>Schule</td>
          <td>
            <div class="muted">Eigenes Schema</div>
            <div class="muted mono">wird angelegt &hellip;</div>
          </td>
          <td class="muted">&mdash;</td>
          <td class="muted">&mdash;</td>
          <td><span class="pill pill-muted">Bereitstellung</span></td>
          <td>
            <div style="display: flex; justify-content: flex-end; gap: 8px;">
              <button class="btn btn-outline btn-sm" type="button">Verwalten</button>
            </div>
          </td>
        </tr>
        <tr>
          <td>
            <div style="font-weight: 500;">Gemeinde Ebnat-Kappel</div>
            <div class="muted" style="font-size: 13px;">3 Standorte &middot; 780 Benutzer</div>
          </td>
          <td class="mono">ebnat.magister.ch</td>
          <td>Schule</td>
          <td>
            <div>Eigene Datenbank</div>
            <div class="muted mono">magister_ebnat</div>
          </td>
          <td class="mono">0043</td>
          <td class="muted">pausiert</td>
          <td><span class="pill pill-warn">Gesperrt</span></td>
          <td>
            <div style="display: flex; justify-content: flex-end; gap: 8px;">
              <button class="btn btn-outline btn-sm" type="button">Verwalten</button>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
    <div style="display: flex; align-items: center; justify-content: space-between; border-top: 1px solid #e2e8f0; padding: 12px 16px;">
      <span class="muted" style="font-size: 13px;">8 von 8 Kunden</span>
      <span class="muted" style="font-size: 13px;">Kein Kunde sieht diese Seite &mdash; die Konsole l&auml;uft auf einer eigenen Origin.</span>
    </div>
  </div>
</div>
EOF

# ------------------------------------------------- Kunde -> Systemeinstellungen
emit KundeDetail.dc.html <<'EOF'
<div class="topbar">
  <div class="shell" style="display: flex; height: 56px; align-items: center; justify-content: space-between;">
    <div style="display: flex; align-items: center; gap: 28px;">
      <div style="display: flex; align-items: baseline; gap: 8px;">
        <span class="serif" style="font-size: 18px; font-weight: 600; letter-spacing: -0.025em;">Magister Console</span>
        <span style="font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: #64748b;">Vita Brevis</span>
      </div>
      <nav style="display: flex; align-items: center; gap: 4px; font-size: 14px;">
        <span class="navlink active">Kunden</span>
        <span class="navlink">Vorlagen</span>
        <span class="navlink">Rechte</span>
        <span class="navlink">Module</span>
        <span class="navlink">Betrieb</span>
        <span class="navlink">Audit</span>
      </nav>
    </div>
    <div style="display: flex; align-items: center; gap: 12px;">
      <span class="pill" style="background: rgba(248, 250, 252, 0.1); color: #e2e8f0; box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.25);">Global Admin</span>
      <span style="display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px; border-radius: 9999px; background: #334155; color: #f8fafc; font-size: 11px; font-weight: 600;">MH</span>
    </div>
  </div>
</div>

<div class="shell" style="padding-top: 24px; padding-bottom: 32px;">
  <div class="muted" style="font-size: 13px;">Kunden &nbsp;&rsaquo;&nbsp; Gemeinde Wattwil</div>

  <header style="display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; margin-top: 12px;">
    <div>
      <div style="display: flex; align-items: center; gap: 10px;">
        <h1 class="serif h1">Gemeinde Wattwil</h1>
        <span class="pill pill-ok">Aktiv</span>
      </div>
      <p class="muted" style="margin: 6px 0 0;">
        <span class="mono">wattwil.magister.ch</span> &middot; Profil Schule &middot; Kundennummer K-0041
      </p>
    </div>
    <div style="display: flex; gap: 8px;">
      <button class="btn btn-outline" type="button">Kunde sperren</button>
      <button class="btn btn-primary" type="button">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg>
        Im Kundenkontext &ouml;ffnen
      </button>
    </div>
  </header>

  <div style="display: flex; align-items: flex-end; border-bottom: 1px solid #e2e8f0; margin-top: 20px;">
    <span class="tab">&Uuml;bersicht</span>
    <span class="tab active">Systemeinstellungen</span>
    <span class="tab">Rechte</span>
    <span class="tab">Vorlagen</span>
    <span class="tab">Module</span>
    <span class="tab">Datenbank</span>
    <span class="tab">Audit</span>
  </div>

  <div class="note" style="margin-top: 24px; display: flex; gap: 12px; align-items: flex-start;">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#0f172a" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="flex-shrink: 0; margin-top: 1px;"><rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
    <div>
      <div style="font-weight: 500;">Nur f&uuml;r Global Admins</div>
      <p class="muted" style="margin: 4px 0 0;">
        OIDC, Active Directory und Konnektoren werden ausschliesslich hier gepflegt. Im Kunden-UI existiert
        <span class="mono">Einstellungen &rsaquo; System</span> nicht mehr &mdash; die Endpunkte sind gar nicht Teil der Kunden-API.
        &Auml;nderungen werden in das Kunden-Schema materialisiert und im Kunden-Audit als
        <span class="mono">settings_pushed</span> sichtbar.
      </p>
    </div>
  </div>

  <div style="display: grid; grid-template-columns: minmax(0, 2.1fr) minmax(0, 1fr); gap: 24px; margin-top: 24px;">
    <div style="display: flex; flex-direction: column; gap: 16px;">

      <div class="card" style="padding: 24px;">
        <h2 class="serif h2">Entra ID (OIDC)</h2>
        <p class="muted" style="margin: 8px 0 20px;">Anmeldung der Lehr- und Leitungspersonen dieses Kunden.</p>
        <div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px;">
          <div>
            <label class="label">Issuer</label>
            <div class="input"><span class="mono">https://login.microsoftonline.com/8c1f&hellip;/v2.0</span></div>
          </div>
          <div>
            <label class="label">Client-ID</label>
            <div class="input"><span class="mono">4d9b1f7a-2c30-4e88-9a51-6b0e</span></div>
          </div>
          <div>
            <label class="label">Client-Secret</label>
            <div class="input" style="justify-content: space-between;">
              <span class="muted">&bull;&bull;&bull;&bull;&bull;&bull;&bull;&bull;&bull;&bull; gesetzt am 12.08.2026</span>
              <span style="font-size: 13px; font-weight: 500;">Ersetzen</span>
            </div>
          </div>
          <div>
            <label class="label">Redirect-URI <span class="muted" style="font-weight: 400;">(abgeleitet)</span></label>
            <div class="input" style="background: #f8fafc;"><span class="muted mono">https://wattwil.magister.ch/api/auth/callback</span></div>
          </div>
        </div>
      </div>

      <div class="card" style="padding: 24px;">
        <div style="display: flex; align-items: flex-start; justify-content: space-between;">
          <div>
            <h2 class="serif h2">Active Directory</h2>
            <p class="muted" style="margin: 8px 0 0;">Eigene Domänencontroller und eigenes Dienstkonto pro Kunde.</p>
          </div>
          <button class="btn btn-outline btn-sm" type="button">Verbindung testen</button>
        </div>
        <div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin-top: 20px;">
          <div>
            <label class="label">Domänencontroller</label>
            <div class="input" style="gap: 6px;">
              <span class="pill pill-muted mono">dc01.wattwil.local</span>
              <span class="pill pill-muted mono">dc02.wattwil.local</span>
            </div>
          </div>
          <div>
            <label class="label">Bind-Modus</label>
            <div class="input" style="justify-content: space-between;">
              <span>GSSAPI (Kerberos, kein Passwort)</span>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
            </div>
          </div>
          <div>
            <label class="label">Such-Basis Benutzer</label>
            <div class="input"><span class="mono">OU=Schulen,DC=wattwil,DC=local</span></div>
          </div>
          <div>
            <label class="label">Sync-Intervall</label>
            <div class="input" style="justify-content: space-between;">
              <span>15 Minuten</span>
              <span class="muted" style="font-size: 13px;">n&auml;chster Lauf in 4 Min</span>
            </div>
          </div>
          <div>
            <label class="label">LDAPS-Zertifikat pr&uuml;fen</label>
            <div class="input" style="justify-content: space-between;">
              <span>Eigene Root-CA hinterlegt</span>
              <span style="display: inline-flex; align-items: center; gap: 8px;">
                <span style="position: relative; display: inline-block; width: 36px; height: 20px; border-radius: 9999px; background: #0f172a;">
                  <span style="position: absolute; top: 2px; left: 18px; width: 16px; height: 16px; border-radius: 9999px; background: #f8fafc;"></span>
                </span>
              </span>
            </div>
          </div>
          <div>
            <label class="label">AD-Anbindung</label>
            <div class="input" style="justify-content: space-between;">
              <span>On-Prem-Connector (ausgehend)</span>
              <span class="pill pill-ok">verbunden</span>
            </div>
          </div>
        </div>
      </div>

      <div class="card" style="padding: 24px;">
        <h2 class="serif h2">Konnektoren</h2>
        <div style="margin-top: 16px; border-top: 1px solid #e2e8f0;">
          <div style="display: flex; align-items: center; justify-content: space-between; padding: 14px 0; border-bottom: 1px solid #e2e8f0;">
            <div>
              <div style="font-weight: 500;">NinjaOne RMM</div>
              <div class="muted" style="font-size: 13px;">Region EU &middot; Ger&auml;testatus und Skriptl&auml;ufe</div>
            </div>
            <div style="display: flex; align-items: center; gap: 12px;">
              <span class="pill pill-ok">aktiv</span>
              <button class="btn btn-outline btn-sm" type="button">Bearbeiten</button>
            </div>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; padding: 14px 0;">
            <div>
              <div style="font-weight: 500;">Webserver-Zertifikat</div>
              <div class="muted" style="font-size: 13px;">Plattform-Zertifikat &middot; Wildcard *.magister.ch</div>
            </div>
            <div style="display: flex; align-items: center; gap: 12px;">
              <span class="pill pill-muted">plattformweit</span>
              <button class="btn btn-outline btn-sm" type="button" disabled style="opacity: 0.5;">Bearbeiten</button>
            </div>
          </div>
        </div>
      </div>

      <div style="display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 16px 20px; border: 1px solid #e2e8f0; border-radius: 8px; background: #f8fafc;">
        <span class="muted">Zuletzt ge&auml;ndert von matthias.hadorn@vitabrevis.ch am 05.09.2026, 14:12</span>
        <div style="display: flex; gap: 8px;">
          <button class="btn btn-outline" type="button">Verwerfen</button>
          <button class="btn btn-primary" type="button">Speichern und ausrollen</button>
        </div>
      </div>
    </div>

    <div style="display: flex; flex-direction: column; gap: 16px;">
      <div class="card" style="padding: 20px;">
        <h2 class="serif h2" style="font-size: 16px;">Datenbank-Trennung</h2>
        <div style="display: grid; gap: 10px; margin-top: 16px; font-size: 13px;">
          <div style="display: flex; justify-content: space-between; gap: 12px;">
            <span class="muted">Modus</span><span style="font-weight: 500;">Eigenes Schema</span>
          </div>
          <div style="display: flex; justify-content: space-between; gap: 12px;">
            <span class="muted">Schema</span><span class="mono">t_wattwil</span>
          </div>
          <div style="display: flex; justify-content: space-between; gap: 12px;">
            <span class="muted">DB-Rolle</span><span class="mono">r_wattwil</span>
          </div>
          <div style="display: flex; justify-content: space-between; gap: 12px;">
            <span class="muted">Migration</span><span class="mono">0043</span>
          </div>
          <div style="display: flex; justify-content: space-between; gap: 12px;">
            <span class="muted">Audit-Schl&uuml;ssel</span><span class="mono">kunden-eigen</span>
          </div>
          <div style="display: flex; justify-content: space-between; gap: 12px;">
            <span class="muted">Backup</span><span>t&auml;glich 02:15</span>
          </div>
        </div>
        <p class="muted" style="margin: 16px 0 0; font-size: 13px;">
          Die Rolle <span class="mono">r_wattwil</span> hat <span class="mono">USAGE</span> nur auf
          <span class="mono">t_wattwil</span>. Ein Query in ein anderes Kundenschema wird von Postgres
          abgewiesen, nicht erst von der Anwendung.
        </p>
        <button class="btn btn-outline btn-sm" type="button" style="margin-top: 16px; width: 100%;">Auf eigene Datenbank umziehen</button>
      </div>

      <div class="card" style="padding: 20px;">
        <h2 class="serif h2" style="font-size: 16px;">Vertrag</h2>
        <div style="display: grid; gap: 10px; margin-top: 16px; font-size: 13px;">
          <div style="display: flex; justify-content: space-between; gap: 12px;">
            <span class="muted">Edition</span><span style="font-weight: 500;">Pro</span>
          </div>
          <div style="display: flex; justify-content: space-between; gap: 12px;">
            <span class="muted">Module</span><span>6 von 7</span>
          </div>
          <div style="display: flex; justify-content: space-between; gap: 12px;">
            <span class="muted">Benutzer-Limit</span><span>2 000</span>
          </div>
          <div style="display: flex; justify-content: space-between; gap: 12px;">
            <span class="muted">Sprachen</span><span>de, fr</span>
          </div>
          <div style="display: flex; justify-content: space-between; gap: 12px;">
            <span class="muted">Kunden-Admin</span><span class="mono" style="font-size: 12px;">it@wattwil.ch</span>
          </div>
        </div>
      </div>

      <div class="card" style="padding: 20px;">
        <h2 class="serif h2" style="font-size: 16px;">Operator-Zugriffe</h2>
        <p class="muted" style="margin: 8px 0 16px; font-size: 13px;">Letzte Zugriffe im Kundenkontext &mdash; der Kunde sieht dieselbe Liste.</p>
        <div style="display: grid; gap: 12px; font-size: 13px;">
          <div>
            <div style="font-weight: 500;">matthias.hadorn</div>
            <div class="muted">05.09. 14:08 &middot; Ticket VB-2291 &middot; 12 Min</div>
          </div>
          <div>
            <div style="font-weight: 500;">support-team</div>
            <div class="muted">28.08. 09:41 &middot; Ticket VB-2244 &middot; 4 Min</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
EOF

# ------------------------------------------------------------- Kunde erfassen
emit NeuerKunde.dc.html <<'EOF'
<div class="topbar">
  <div class="shell" style="display: flex; height: 56px; align-items: center; justify-content: space-between;">
    <div style="display: flex; align-items: center; gap: 28px;">
      <div style="display: flex; align-items: baseline; gap: 8px;">
        <span class="serif" style="font-size: 18px; font-weight: 600; letter-spacing: -0.025em;">Magister Console</span>
        <span style="font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: #64748b;">Vita Brevis</span>
      </div>
      <nav style="display: flex; align-items: center; gap: 4px; font-size: 14px;">
        <span class="navlink active">Kunden</span>
        <span class="navlink">Vorlagen</span>
        <span class="navlink">Rechte</span>
        <span class="navlink">Module</span>
        <span class="navlink">Betrieb</span>
        <span class="navlink">Audit</span>
      </nav>
    </div>
    <div style="display: flex; align-items: center; gap: 12px;">
      <span class="pill" style="background: rgba(248, 250, 252, 0.1); color: #e2e8f0; box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.25);">Global Admin</span>
      <span style="display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px; border-radius: 9999px; background: #334155; color: #f8fafc; font-size: 11px; font-weight: 600;">MH</span>
    </div>
  </div>
</div>

<div class="shell" style="padding-top: 24px; padding-bottom: 32px;">
  <div class="muted" style="font-size: 13px;">Kunden &nbsp;&rsaquo;&nbsp; Neu</div>
  <h1 class="serif h1" style="margin-top: 12px;">Kunde erfassen</h1>
  <p class="muted" style="margin: 6px 0 0;">Legt Mandant, Datenbank-Trennung, Zugangspfad und Startkonfiguration in einem Vorgang an.</p>

  <div style="display: grid; grid-template-columns: minmax(0, 2.1fr) minmax(0, 1fr); gap: 24px; margin-top: 24px;">
    <div style="display: flex; flex-direction: column; gap: 16px;">

      <div class="card" style="padding: 24px;">
        <h2 class="serif h2">Kunde</h2>
        <div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin-top: 20px;">
          <div>
            <label class="label">Name</label>
            <div class="input"><span>Schulgemeinde Nesslau</span></div>
          </div>
          <div>
            <label class="label">Kundennummer</label>
            <div class="input" style="background: #f8fafc;"><span class="muted mono">K-0049 (automatisch)</span></div>
          </div>
        </div>
        <div style="margin-top: 16px;">
          <label class="label">Profil</label>
          <div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px;">
            <label style="display: flex; gap: 12px; padding: 14px; border: 1px solid #0f172a; border-radius: 8px; background: #f8fafc;">
              <span style="flex-shrink: 0; margin-top: 2px; width: 16px; height: 16px; border-radius: 9999px; border: 1px solid #0f172a; display: inline-flex; align-items: center; justify-content: center;"><span style="width: 8px; height: 8px; border-radius: 9999px; background: #0f172a;"></span></span>
              <span>
                <span style="display: block; font-weight: 500;">Schule</span>
                <span class="muted" style="display: block; font-size: 13px; margin-top: 2px;">Klassen, Zyklen, Briefe</span>
              </span>
            </label>
            <label style="display: flex; gap: 12px; padding: 14px; border: 1px solid #e2e8f0; border-radius: 8px;">
              <span style="flex-shrink: 0; margin-top: 2px; width: 16px; height: 16px; border-radius: 9999px; border: 1px solid #cbd5e1;"></span>
              <span>
                <span style="display: block; font-weight: 500;">Firma</span>
                <span class="muted" style="display: block; font-size: 13px; margin-top: 2px;">Abteilungen, Vorgesetzte</span>
              </span>
            </label>
            <label style="display: flex; gap: 12px; padding: 14px; border: 1px solid #e2e8f0; border-radius: 8px;">
              <span style="flex-shrink: 0; margin-top: 2px; width: 16px; height: 16px; border-radius: 9999px; border: 1px solid #cbd5e1;"></span>
              <span>
                <span style="display: block; font-weight: 500;">Neutral</span>
                <span class="muted" style="display: block; font-size: 13px; margin-top: 2px;">Nur Basis-Module</span>
              </span>
            </label>
          </div>
        </div>
      </div>

      <div class="card" style="padding: 24px;">
        <h2 class="serif h2">Zugang</h2>
        <p class="muted" style="margin: 8px 0 20px;">
          Jeder Kunde bekommt eine eigene Subdomain &mdash; und damit eine eigene Origin: eigener
          Browser-Speicher, eigene Cookies, XSS-Radius endet beim Kunden. Wildcard-Zertifikat deckt sie ab,
          es braucht nur einen DNS-Eintrag.
        </p>
        <div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px;">
          <div>
            <label class="label">Subdomain</label>
            <div style="display: flex;">
              <div class="input" style="border-radius: 6px 0 0 6px; border-right: 0;"><span class="mono">nesslau</span></div>
              <span style="display: inline-flex; align-items: center; height: 40px; padding: 0 12px; border: 1px solid #e2e8f0; border-radius: 0 6px 6px 0; background: #f8fafc; color: #64748b;" class="mono">.magister.ch</span>
            </div>
          </div>
          <div>
            <label class="label">Eigene Domain <span class="muted" style="font-weight: 400;">(optional, sp&auml;ter)</span></label>
            <div class="input"><span class="ph mono">magister.nesslau.ch</span></div>
          </div>
          <div style="grid-column: span 2;">
            <label class="label">Kunden-Admins beim ersten Login</label>
            <div class="input" style="gap: 6px;">
              <span class="pill pill-muted mono">it@nesslau.ch</span>
              <span class="pill pill-muted mono">schulleitung@nesslau.ch</span>
              <span class="ph">weitere UPN erfassen &hellip;</span>
            </div>
          </div>
        </div>
      </div>

      <div class="card" style="padding: 24px;">
        <h2 class="serif h2">Datenbank-Trennung</h2>
        <p class="muted" style="margin: 8px 0 20px;">Bestimmt, wie hart die Daten dieses Kunden von allen anderen getrennt sind. Sp&auml;ter umziehbar.</p>
        <div style="display: flex; flex-direction: column; gap: 12px;">
          <label style="display: flex; gap: 12px; padding: 14px; border: 1px solid #0f172a; border-radius: 8px; background: #f8fafc;">
            <span style="flex-shrink: 0; margin-top: 2px; width: 16px; height: 16px; border-radius: 9999px; border: 1px solid #0f172a; display: inline-flex; align-items: center; justify-content: center;"><span style="width: 8px; height: 8px; border-radius: 9999px; background: #0f172a;"></span></span>
            <span>
              <span style="display: block; font-weight: 500;">Eigenes Schema <span class="pill pill-muted" style="margin-left: 6px;">Standard</span></span>
              <span class="muted" style="display: block; font-size: 13px; margin-top: 3px;">Eigenes Postgres-Schema <span class="mono">t_nesslau</span> mit eigener DB-Rolle. Kein Zugriff auf andere Schemas &mdash; von Postgres erzwungen, nicht von der Anwendung.</span>
            </span>
          </label>
          <label style="display: flex; gap: 12px; padding: 14px; border: 1px solid #e2e8f0; border-radius: 8px;">
            <span style="flex-shrink: 0; margin-top: 2px; width: 16px; height: 16px; border-radius: 9999px; border: 1px solid #cbd5e1;"></span>
            <span>
              <span style="display: block; font-weight: 500;">Eigene Datenbank</span>
              <span class="muted" style="display: block; font-size: 13px; margin-top: 3px;">Zus&auml;tzlich getrennte Sicherung, getrennte Wiederherstellung und getrennte Verbindungsgrenzen. F&uuml;r grosse oder besonders regulierte Kunden.</span>
            </span>
          </label>
          <label style="display: flex; gap: 12px; padding: 14px; border: 1px solid #e2e8f0; border-radius: 8px;">
            <span style="flex-shrink: 0; margin-top: 2px; width: 16px; height: 16px; border-radius: 9999px; border: 1px solid #cbd5e1;"></span>
            <span>
              <span style="display: block; font-weight: 500;">Eigener Cluster</span>
              <span class="muted" style="display: block; font-size: 13px; margin-top: 3px;">Eigener Datenbankserver &mdash; auch Rechenlast ist getrennt. Teuerste Variante, gleicher Code-Pfad.</span>
            </span>
          </label>
        </div>
      </div>

      <div class="card" style="padding: 24px;">
        <h2 class="serif h2">Startkonfiguration</h2>
        <div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin-top: 20px;">
          <div>
            <label class="label">Vorlagen-Set</label>
            <div class="input" style="justify-content: space-between;">
              <span>Global &middot; Schule (de)</span>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
            </div>
          </div>
          <div>
            <label class="label">Rechte-Matrix</label>
            <div class="input" style="justify-content: space-between;">
              <span>Global &middot; Standard Schule</span>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
            </div>
          </div>
          <div style="grid-column: span 2;">
            <label class="label">Module</label>
            <div style="display: flex; flex-wrap: wrap; gap: 8px;">
              <span class="pill pill-muted">platform</span>
              <span class="pill pill-muted">ad</span>
              <span class="pill pill-muted">users</span>
              <span class="pill pill-muted">settings</span>
              <span class="pill pill-ok">classes</span>
              <span class="pill pill-ok">templates</span>
              <span class="pill pill-ok">imports</span>
              <span class="pill pill-ok">reports</span>
              <span class="pill pill-ok">devices</span>
              <span class="pill pill-muted">departments</span>
            </div>
            <p class="muted" style="margin: 10px 0 0; font-size: 13px;">Aus dem Profil vorbelegt. Vier Basis-Module sind nicht abschaltbar.</p>
          </div>
        </div>
      </div>

      <div style="display: flex; align-items: center; justify-content: flex-end; gap: 8px;">
        <button class="btn btn-outline" type="button">Abbrechen</button>
        <button class="btn btn-primary" type="button">Kunde anlegen</button>
      </div>
    </div>

    <div class="card" style="padding: 20px; align-self: flex-start;">
      <h2 class="serif h2" style="font-size: 16px;">Beim Anlegen passiert</h2>
      <ol style="margin: 16px 0 0; padding-left: 0; list-style: none; display: grid; gap: 14px;">
        <li style="display: flex; gap: 12px;">
          <span class="mono" style="flex-shrink: 0; width: 22px; height: 22px; border-radius: 9999px; background: #f1f5f9; color: #475569; display: inline-flex; align-items: center; justify-content: center; font-size: 12px;">1</span>
          <span style="font-size: 13px;">Eintrag in der Mandanten-Registry, DNS-Eintrag f&uuml;r die Subdomain</span>
        </li>
        <li style="display: flex; gap: 12px;">
          <span class="mono" style="flex-shrink: 0; width: 22px; height: 22px; border-radius: 9999px; background: #f1f5f9; color: #475569; display: inline-flex; align-items: center; justify-content: center; font-size: 12px;">2</span>
          <span style="font-size: 13px;">Schema plus DB-Rolle anlegen, <span class="mono">USAGE</span> auf alle anderen Schemas entzogen</span>
        </li>
        <li style="display: flex; gap: 12px;">
          <span class="mono" style="flex-shrink: 0; width: 22px; height: 22px; border-radius: 9999px; background: #f1f5f9; color: #475569; display: inline-flex; align-items: center; justify-content: center; font-size: 12px;">3</span>
          <span style="font-size: 13px;">Alembic auf Kopf-Version <span class="mono">0043</span></span>
        </li>
        <li style="display: flex; gap: 12px;">
          <span class="mono" style="flex-shrink: 0; width: 22px; height: 22px; border-radius: 9999px; background: #f1f5f9; color: #475569; display: inline-flex; align-items: center; justify-content: center; font-size: 12px;">4</span>
          <span style="font-size: 13px;">Eigener Audit-Schl&uuml;ssel, im Plattform-Schl&uuml;ssel verpackt</span>
        </li>
        <li style="display: flex; gap: 12px;">
          <span class="mono" style="flex-shrink: 0; width: 22px; height: 22px; border-radius: 9999px; background: #f1f5f9; color: #475569; display: inline-flex; align-items: center; justify-content: center; font-size: 12px;">5</span>
          <span style="font-size: 13px;">Rechte-Matrix und Vorlagen-Set in das Kunden-Schema materialisieren</span>
        </li>
      </ol>
      <p class="muted" style="margin: 18px 0 0; font-size: 13px;">
        L&auml;uft als Auftrag mit Fortschritt und Wiederaufnahme. Bricht ein Schritt ab, bleibt der Kunde
        auf <span class="mono">Bereitstellung</span> und ist nicht erreichbar &mdash; nie halb angelegt.
      </p>
    </div>
  </div>
</div>
EOF

# ------------------------------------------------------------ Konsolen-Login
emit Login.dc.html <<'EOF'
<div style="display: flex; min-height: 100vh; align-items: center; justify-content: center; background: #ffffff; padding: 16px;">
  <div class="card" style="width: 100%; max-width: 448px;">
    <div style="display: flex; flex-direction: column; gap: 4px; padding: 24px;">
      <div style="display: flex; align-items: baseline; gap: 8px;">
        <h1 class="serif" style="font-size: 20px; line-height: 20px; font-weight: 600; letter-spacing: -0.025em; margin: 0;">Magister Console</h1>
        <span style="font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: #64748b;">Vita Brevis</span>
      </div>
      <p class="muted" style="margin: 8px 0 0;">Anmeldung f&uuml;r Global Admins und Operatoren. Kunden melden sich unter ihrem eigenen Pfad an.</p>
    </div>
    <div style="padding: 0 24px 24px; display: flex; flex-direction: column; gap: 24px;">
      <button class="btn btn-primary" type="button" style="width: 100%;">Mit Entra ID anmelden</button>
      <div class="note" style="border-left-color: #0f172a;">
        <div style="display: flex; gap: 10px; align-items: flex-start;">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#0f172a" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="flex-shrink: 0; margin-top: 2px;"><path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/></svg>
          <p class="muted" style="margin: 0; font-size: 13px;">
            Verlangt einen Hardware-Schl&uuml;ssel und ein verwaltetes Ger&auml;t. Kein lokales Konto,
            kein AD-Login, kein Notzugang &mdash; die Konsole kann Sitzungen in jeden Kunden ausstellen.
          </p>
        </div>
      </div>
      <p class="muted" style="margin: 0; font-size: 13px; text-align: center;">
        <span class="mono">console.magister.ch:4444</span> &mdash; nur im internen Netz,
        aus dem Internet nicht geroutet
      </p>
    </div>
  </div>
</div>
EOF

# ---------------------------------------------------- Kundenwahl nach Anmeldung
emit Kundenwahl.dc.html <<'EOF'
<div style="display: flex; min-height: 100vh; align-items: center; justify-content: center; background: #ffffff; padding: 24px;">
  <div class="card" style="width: 100%; max-width: 640px;">
    <div style="padding: 24px; border-bottom: 1px solid #e2e8f0;">
      <h1 class="serif h2">Welchen Kunden m&ouml;chten Sie bedienen?</h1>
      <p class="muted" style="margin: 8px 0 0;">Angemeldet als matthias.hadorn@vitabrevis.ch &middot; Global Admin</p>
    </div>

    <div style="padding: 20px 24px 8px;">
      <div class="input">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
        <span class="ph">Kunde suchen</span>
      </div>
    </div>

    <div style="padding: 12px 24px 0;">
      <div class="muted" style="font-size: 12px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase;">Zuletzt bedient</div>
      <div style="display: flex; flex-direction: column; margin-top: 8px;">
        <div style="display: flex; align-items: center; gap: 12px; padding: 12px; border-radius: 6px; background: #f1f5f9;">
          <span class="serif" style="flex-shrink: 0; display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; border-radius: 6px; background: #0f172a; color: #f8fafc; font-size: 13px; font-weight: 600;">GW</span>
          <span style="flex-grow: 1;">
            <span style="display: block; font-weight: 500;">Gemeinde Wattwil</span>
            <span class="muted mono" style="display: block; font-size: 12.5px;">wattwil.magister.ch &middot; t_wattwil</span>
          </span>
          <span class="pill pill-ok">Aktiv</span>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6"/></svg>
        </div>
        <div style="display: flex; align-items: center; gap: 12px; padding: 12px; border-radius: 6px;">
          <span class="serif" style="flex-shrink: 0; display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; border-radius: 6px; background: #f1f5f9; color: #475569; font-size: 13px; font-weight: 600;">AT</span>
          <span style="flex-grow: 1;">
            <span style="display: block; font-weight: 500;">Alpstein Treuhand AG</span>
            <span class="muted mono" style="display: block; font-size: 12.5px;">alpstein.magister.ch &middot; t_alpstein</span>
          </span>
          <span class="pill pill-ok">Aktiv</span>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6"/></svg>
        </div>
      </div>
    </div>

    <div style="padding: 16px 24px 0;">
      <div class="muted" style="font-size: 12px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase;">Alle Kunden</div>
      <div style="display: flex; flex-direction: column; margin-top: 8px;">
        <div style="display: flex; align-items: center; gap: 12px; padding: 12px; border-radius: 6px;">
          <span class="serif" style="flex-shrink: 0; display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; border-radius: 6px; background: #f1f5f9; color: #475569; font-size: 13px; font-weight: 600;">SU</span>
          <span style="flex-grow: 1;">
            <span style="display: block; font-weight: 500;">Stadt Uzwil</span>
            <span class="muted mono" style="display: block; font-size: 12.5px;">uzwil.magister.ch &middot; t_uzwil</span>
          </span>
          <span class="pill pill-ok">Aktiv</span>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6"/></svg>
        </div>
        <div style="display: flex; align-items: center; gap: 12px; padding: 12px; border-radius: 6px;">
          <span class="serif" style="flex-shrink: 0; display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; border-radius: 6px; background: #f1f5f9; color: #475569; font-size: 13px; font-weight: 600;">SF</span>
          <span style="flex-grow: 1;">
            <span style="display: block; font-weight: 500;">Schulgemeinde Flawil</span>
            <span class="muted mono" style="display: block; font-size: 12.5px;">flawil.magister.ch &middot; magister_flawil</span>
          </span>
          <span class="pill pill-ok">Aktiv</span>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6"/></svg>
        </div>
        <div style="display: flex; align-items: center; gap: 12px; padding: 12px; border-radius: 6px;">
          <span class="serif" style="flex-shrink: 0; display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; border-radius: 6px; background: #f1f5f9; color: #475569; font-size: 13px; font-weight: 600;">GE</span>
          <span style="flex-grow: 1;">
            <span style="display: block; font-weight: 500;">Gemeinde Ebnat-Kappel</span>
            <span class="muted mono" style="display: block; font-size: 12.5px;">ebnat.magister.ch &middot; magister_ebnat</span>
          </span>
          <span class="pill pill-warn">Gesperrt</span>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#cbd5e1" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6"/></svg>
        </div>
      </div>
    </div>

    <div style="padding: 20px 24px 24px; margin-top: 12px; border-top: 1px solid #e2e8f0;">
      <label class="label">Grund oder Ticket</label>
      <div class="input"><span class="ph">VB-2291 &mdash; Passwort-Reset schl&auml;gt fehl</span></div>
      <p class="muted" style="margin: 10px 0 0; font-size: 13px;">
        Wird im Audit des Kunden festgehalten und ist f&uuml;r den Kunden sichtbar. Die Sitzung im Kundenkontext
        l&auml;uft nach 60 Minuten ab.
      </p>
      <div style="display: flex; gap: 8px; margin-top: 16px;">
        <button class="btn btn-outline" type="button" style="flex-grow: 1;">Nur Konsole &ouml;ffnen</button>
        <button class="btn btn-primary" type="button" style="flex-grow: 1;">Kunde bedienen</button>
      </div>
    </div>
  </div>
</div>
EOF

# ------------------------------------------------------- Rollen und Rechte
emit Rechte.dc.html <<'EOF'
<div class="topbar">
  <div class="shell" style="display: flex; height: 56px; align-items: center; justify-content: space-between;">
    <div style="display: flex; align-items: center; gap: 28px;">
      <div style="display: flex; align-items: baseline; gap: 8px;">
        <span class="serif" style="font-size: 18px; font-weight: 600; letter-spacing: -0.025em;">Magister Console</span>
        <span style="font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: #64748b;">Vita Brevis</span>
      </div>
      <nav style="display: flex; align-items: center; gap: 4px; font-size: 14px;">
        <span class="navlink">Kunden</span>
        <span class="navlink">Vorlagen</span>
        <span class="navlink active">Rechte</span>
        <span class="navlink">Module</span>
        <span class="navlink">Betrieb</span>
        <span class="navlink">Audit</span>
      </nav>
    </div>
    <div style="display: flex; align-items: center; gap: 12px;">
      <span class="pill" style="background: rgba(248, 250, 252, 0.1); color: #e2e8f0; box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.25);">Global Admin</span>
      <span style="display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px; border-radius: 9999px; background: #334155; color: #f8fafc; font-size: 11px; font-weight: 600;">MH</span>
    </div>
  </div>
</div>

<div class="shell" style="padding-top: 32px; padding-bottom: 32px;">
  <header style="display: flex; align-items: flex-start; justify-content: space-between; gap: 24px;">
    <div>
      <h1 class="serif h1">Rollen und Rechte</h1>
      <p class="muted" style="margin: 6px 0 0;">Die Matrix wird ausschliesslich hier gepflegt und in die Kunden-Schemas materialisiert.</p>
    </div>
    <div style="display: flex; gap: 8px;">
      <button class="btn btn-outline" type="button">Rolle hinzuf&uuml;gen</button>
      <button class="btn btn-primary" type="button">Speichern und ausrollen</button>
    </div>
  </header>

  <div style="display: flex; align-items: flex-end; border-bottom: 1px solid #e2e8f0; margin-top: 20px;">
    <span class="tab active">Standard Schule</span>
    <span class="tab">Standard Firma</span>
    <span class="tab">Standard Neutral</span>
    <span class="tab">Abweichungen (1)</span>
  </div>

  <div style="display: grid; grid-template-columns: minmax(0, 2.4fr) minmax(0, 1fr); gap: 24px; margin-top: 24px;">
    <div class="card" style="overflow: hidden;">
      <table>
        <thead>
          <tr>
            <th style="width: 220px;">Rolle</th>
            <th style="text-align: center;">Benutzer<br>lesen</th>
            <th style="text-align: center;">Benutzer<br>verwalten</th>
            <th style="text-align: center;">Benutzer-<br>konfiguration</th>
            <th style="text-align: center;">Standorte<br>verwalten</th>
            <th style="text-align: center;">Import<br>ausf&uuml;hren</th>
            <th style="text-align: center; color: #94a3b8;">System<br>konfigurieren</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>
              <div style="font-weight: 500;">Kunden-Admin</div>
              <div class="muted mono" style="font-size: 12.5px;">admin</div>
            </td>
            <td colspan="5" style="text-align: center;" class="muted">alle Rechte dieses Kunden &mdash; nicht editierbar</td>
            <td style="text-align: center;">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#cbd5e1" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
            </td>
          </tr>
          <tr>
            <td>
              <div style="font-weight: 500;">Schulleitung</div>
              <div class="muted mono" style="font-size: 12.5px;">schulleitung</div>
            </td>
            <td style="text-align: center;"><span style="display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; border-radius: 4px; background: #0f172a;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#f8fafc" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg></span></td>
            <td style="text-align: center;"><span style="display: inline-block; width: 18px; height: 18px; border-radius: 4px; border: 1px solid #cbd5e1; background: #ffffff;"></span></td>
            <td style="text-align: center;"><span style="display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; border-radius: 4px; background: #0f172a;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#f8fafc" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg></span></td>
            <td style="text-align: center;"><span style="display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; border-radius: 4px; background: #0f172a;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#f8fafc" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg></span></td>
            <td style="text-align: center;"><span style="display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; border-radius: 4px; background: #0f172a;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#f8fafc" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg></span></td>
            <td style="text-align: center;">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#cbd5e1" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
            </td>
          </tr>
          <tr>
            <td>
              <div style="font-weight: 500;">Schultr&auml;ger-IT</div>
              <div class="muted mono" style="font-size: 12.5px;">smi</div>
            </td>
            <td style="text-align: center;"><span style="display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; border-radius: 4px; background: #0f172a;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#f8fafc" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg></span></td>
            <td style="text-align: center;"><span style="display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; border-radius: 4px; background: #0f172a;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#f8fafc" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg></span></td>
            <td style="text-align: center;"><span style="display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; border-radius: 4px; background: #0f172a;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#f8fafc" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg></span></td>
            <td style="text-align: center;"><span style="display: inline-block; width: 18px; height: 18px; border-radius: 4px; border: 1px solid #cbd5e1; background: #ffffff;"></span></td>
            <td style="text-align: center;"><span style="display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; border-radius: 4px; background: #0f172a;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#f8fafc" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg></span></td>
            <td style="text-align: center;">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#cbd5e1" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
            </td>
          </tr>
          <tr>
            <td>
              <div style="font-weight: 500;">Klassenlehrperson</div>
              <div class="muted mono" style="font-size: 12.5px;">kl &middot; abgeleitet</div>
            </td>
            <td colspan="6" style="text-align: center;" class="muted">Rechte pro Klasse &mdash; nicht Teil der Matrix</td>
          </tr>
          <tr>
            <td>
              <div style="display: flex; align-items: center; gap: 8px;">
                <span style="font-weight: 500;">Hausdienst</span>
                <span class="pill pill-muted">eigen</span>
              </div>
              <div class="muted mono" style="font-size: 12.5px;">hausdienst</div>
            </td>
            <td style="text-align: center;"><span style="display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; border-radius: 4px; background: #0f172a;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#f8fafc" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg></span></td>
            <td style="text-align: center;"><span style="display: inline-block; width: 18px; height: 18px; border-radius: 4px; border: 1px solid #cbd5e1; background: #ffffff;"></span></td>
            <td style="text-align: center;"><span style="display: inline-block; width: 18px; height: 18px; border-radius: 4px; border: 1px solid #cbd5e1; background: #ffffff;"></span></td>
            <td style="text-align: center;"><span style="display: inline-block; width: 18px; height: 18px; border-radius: 4px; border: 1px solid #cbd5e1; background: #ffffff;"></span></td>
            <td style="text-align: center;"><span style="display: inline-block; width: 18px; height: 18px; border-radius: 4px; border: 1px solid #cbd5e1; background: #ffffff;"></span></td>
            <td style="text-align: center;">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#cbd5e1" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
            </td>
          </tr>
        </tbody>
      </table>
      <div style="border-top: 1px solid #e2e8f0; padding: 14px 16px;">
        <p class="muted" style="margin: 0; font-size: 13px;">
          <span style="display: inline-block; vertical-align: -2px; margin-right: 6px;"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg></span>
          <span class="mono">System konfigurieren</span> ist keine Kundenrolle mehr: die Endpunkte liegen in der Konsole,
          nicht in der Kunden-API. Auch ein &uuml;bernommener Kunden-Admin kann sie nicht erreichen.
        </p>
      </div>
    </div>

    <div style="display: flex; flex-direction: column; gap: 16px;">
      <div class="card" style="padding: 20px;">
        <h2 class="serif h2" style="font-size: 16px;">Verteilung</h2>
        <p class="muted" style="margin: 8px 0 16px; font-size: 13px;">Welche Kunden fahren auf dieser Matrix.</p>
        <div style="display: grid; gap: 12px; font-size: 13px;">
          <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px;">
            <span>Gemeinde Wattwil</span><span class="pill pill-ok">global</span>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px;">
            <span>Stadt Uzwil</span><span class="pill pill-ok">global</span>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px;">
            <span>Schulgemeinde Flawil</span><span class="pill pill-ok">global</span>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px;">
            <span>Gemeinde Degersheim</span><span class="pill pill-warn">abweichend</span>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px;">
            <span>Gemeinde Ebnat-Kappel</span><span class="pill pill-ok">global</span>
          </div>
        </div>
        <button class="btn btn-outline btn-sm" type="button" style="width: 100%; margin-top: 18px;">Abweichung ansehen</button>
      </div>

      <div class="card" style="padding: 20px;">
        <h2 class="serif h2" style="font-size: 16px;">Plattform-Rechte</h2>
        <p class="muted" style="margin: 8px 0 16px; font-size: 13px;">Gelten nur in der Konsole. Keine Kundenrolle kann sie halten.</p>
        <div style="display: grid; gap: 10px; font-size: 13px;">
          <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px;">
            <span class="mono" style="font-size: 12px;">platform.tenant.manage</span><span class="muted">Global Admin</span>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px;">
            <span class="mono" style="font-size: 12px;">platform.settings.write</span><span class="muted">Global Admin</span>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px;">
            <span class="mono" style="font-size: 12px;">platform.rights.write</span><span class="muted">Global Admin</span>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px;">
            <span class="mono" style="font-size: 12px;">platform.templates.publish</span><span class="muted">Global Admin</span>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px;">
            <span class="mono" style="font-size: 12px;">platform.tenant.impersonate</span><span class="muted">Admin + Operator</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
EOF

# --------------------------------------------------------- Globale Vorlagen
emit Vorlagen.dc.html <<'EOF'
<div class="topbar">
  <div class="shell" style="display: flex; height: 56px; align-items: center; justify-content: space-between;">
    <div style="display: flex; align-items: center; gap: 28px;">
      <div style="display: flex; align-items: baseline; gap: 8px;">
        <span class="serif" style="font-size: 18px; font-weight: 600; letter-spacing: -0.025em;">Magister Console</span>
        <span style="font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: #64748b;">Vita Brevis</span>
      </div>
      <nav style="display: flex; align-items: center; gap: 4px; font-size: 14px;">
        <span class="navlink">Kunden</span>
        <span class="navlink active">Vorlagen</span>
        <span class="navlink">Rechte</span>
        <span class="navlink">Module</span>
        <span class="navlink">Betrieb</span>
        <span class="navlink">Audit</span>
      </nav>
    </div>
    <div style="display: flex; align-items: center; gap: 12px;">
      <span class="pill" style="background: rgba(248, 250, 252, 0.1); color: #e2e8f0; box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.25);">Global Admin</span>
      <span style="display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px; border-radius: 9999px; background: #334155; color: #f8fafc; font-size: 11px; font-weight: 600;">MH</span>
    </div>
  </div>
</div>

<div class="shell" style="padding-top: 32px; padding-bottom: 32px;">
  <header style="display: flex; align-items: flex-start; justify-content: space-between; gap: 24px;">
    <div>
      <h1 class="serif h1">Globale Vorlagen</h1>
      <p class="muted" style="margin: 6px 0 0;">Einmal gepflegt, in jeden Kunden ausgerollt. Ein Kunde kann nur &uuml;berschreiben, wo es erlaubt ist.</p>
    </div>
    <div style="display: flex; gap: 8px;">
      <button class="btn btn-outline" type="button">Vorlage anlegen</button>
      <button class="btn btn-primary" type="button">Auf Kunden anwenden</button>
    </div>
  </header>

  <div style="display: flex; align-items: flex-end; border-bottom: 1px solid #e2e8f0; margin-top: 20px;">
    <span class="tab active">Dokumentvorlagen</span>
    <span class="tab">AD-Gruppen-Vorlagen</span>
    <span class="tab">Modul-Voreinstellungen</span>
    <span class="tab">Rollout-Verlauf</span>
  </div>

  <div style="display: grid; grid-template-columns: minmax(0, 2.2fr) minmax(0, 1fr); gap: 24px; margin-top: 24px;">
    <div style="display: flex; flex-direction: column; gap: 16px;">
      <div class="card" style="overflow: hidden;">
        <table>
          <thead>
            <tr>
              <th style="width: 300px;">Vorlage</th>
              <th style="width: 130px;">Sprachen</th>
              <th style="width: 96px;">Version</th>
              <th style="width: 180px;">Kunde darf &uuml;berschreiben</th>
              <th>Ge&auml;ndert</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <div style="font-weight: 500;">Anmeldebest&auml;tigung</div>
                <div class="muted mono" style="font-size: 12.5px;">enrollment</div>
              </td>
              <td>de &middot; fr &middot; it</td>
              <td class="mono">v5</td>
              <td><span class="pill pill-muted">nein</span></td>
              <td class="muted">02.09.2026</td>
            </tr>
            <tr>
              <td>
                <div style="font-weight: 500;">Klassenwechsel</div>
                <div class="muted mono" style="font-size: 12.5px;">class_change</div>
              </td>
              <td>de &middot; fr</td>
              <td class="mono">v3</td>
              <td><span class="pill pill-ok">ja</span></td>
              <td class="muted">18.08.2026</td>
            </tr>
            <tr>
              <td>
                <div style="font-weight: 500;">Passwort-Handout</div>
                <div class="muted mono" style="font-size: 12.5px;">password_handout</div>
              </td>
              <td>de &middot; fr &middot; it &middot; en</td>
              <td class="mono">v7</td>
              <td><span class="pill pill-muted">nein</span></td>
              <td class="muted">05.09.2026</td>
            </tr>
            <tr>
              <td>
                <div style="font-weight: 500;">Zugangsdaten-Klassenliste</div>
                <div class="muted mono" style="font-size: 12.5px;">class_password_list</div>
              </td>
              <td>de</td>
              <td class="mono">v2</td>
              <td><span class="pill pill-ok">ja</span></td>
              <td class="muted">30.06.2026</td>
            </tr>
            <tr>
              <td>
                <div style="font-weight: 500;">Eintrittsschreiben Firma</div>
                <div class="muted mono" style="font-size: 12.5px;">onboarding_company</div>
              </td>
              <td>de &middot; en</td>
              <td class="mono">v1</td>
              <td><span class="pill pill-ok">ja</span></td>
              <td class="muted">21.08.2026</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="card" style="padding: 20px 24px;">
        <h2 class="serif h2" style="font-size: 16px;">Welche Fassung ein Kunde sieht</h2>
        <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-top: 16px; font-size: 13px;">
          <span class="pill" style="background: #0f172a; color: #f8fafc;">Kunde + Standort</span>
          <span class="muted">&rarr;</span>
          <span class="pill pill-muted">Kunde</span>
          <span class="muted">&rarr;</span>
          <span class="pill pill-muted">Global</span>
          <span class="muted">&rarr;</span>
          <span class="pill pill-muted">eingebaut im Code</span>
        </div>
        <p class="muted" style="margin: 14px 0 0; font-size: 13px;">
          Die erste vorhandene Fassung gewinnt. Globale Vorlagen liegen als Kopie im Kunden-Schema und
          sind dort schreibgesch&uuml;tzt &mdash; das Rendern bleibt ein rein lokaler Lesezugriff, ohne
          Verbindung zur Konsole. F&auml;llt die Konsole aus, drucken alle Kunden weiter.
        </p>
      </div>
    </div>

    <div style="display: flex; flex-direction: column; gap: 16px;">
      <div class="card" style="padding: 20px;">
        <h2 class="serif h2" style="font-size: 16px;">Passwort-Handout v7 ausrollen</h2>
        <div style="margin-top: 16px;">
          <label class="label">Anwenden auf</label>
          <div class="input" style="justify-content: space-between;">
            <span>Alle Kunden mit Profil Schule</span>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
          </div>
        </div>
        <div style="display: grid; gap: 12px; margin-top: 18px; font-size: 13px;">
          <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px;">
            <span>Gemeinde Wattwil</span><span class="pill pill-muted mono">v6 &rarr; v7</span>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px;">
            <span>Stadt Uzwil</span><span class="pill pill-muted mono">v6 &rarr; v7</span>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px;">
            <span>Schulgemeinde Flawil</span><span class="pill pill-ok mono">v7</span>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px;">
            <span>Gemeinde Degersheim</span><span class="pill pill-muted mono">v6 &rarr; v7</span>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px;">
            <span>Gemeinde Ebnat-Kappel</span><span class="pill pill-warn">eigene Fassung</span>
          </div>
        </div>
        <p class="muted" style="margin: 16px 0 0; font-size: 13px;">
          Ebnat-Kappel hat eine eigene Fassung und bleibt unver&auml;ndert. Der Kunde sieht den Hinweis
          &bdquo;neue globale Fassung verf&uuml;gbar&ldquo; und kann zur&uuml;ck auf global wechseln.
        </p>
        <button class="btn btn-primary" type="button" style="width: 100%; margin-top: 18px;">Auf 4 Kunden ausrollen</button>
      </div>

      <div class="card" style="padding: 20px;">
        <h2 class="serif h2" style="font-size: 16px;">Letzter Rollout</h2>
        <div style="display: grid; gap: 10px; margin-top: 16px; font-size: 13px;">
          <div style="display: flex; justify-content: space-between; gap: 12px;">
            <span class="muted">Vorlage</span><span class="mono">enrollment v5</span>
          </div>
          <div style="display: flex; justify-content: space-between; gap: 12px;">
            <span class="muted">Kunden</span><span>8 von 8</span>
          </div>
          <div style="display: flex; justify-content: space-between; gap: 12px;">
            <span class="muted">Zeitpunkt</span><span>02.09.2026, 09:14</span>
          </div>
          <div style="display: flex; justify-content: space-between; gap: 12px;">
            <span class="muted">Ausgel&ouml;st von</span><span class="mono" style="font-size: 12px;">matthias.hadorn</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
EOF

# --------------------------------------------- Betrieb: Datenbank-Trennung
emit Isolation.dc.html <<'EOF'
<div class="topbar">
  <div class="shell" style="display: flex; height: 56px; align-items: center; justify-content: space-between;">
    <div style="display: flex; align-items: center; gap: 28px;">
      <div style="display: flex; align-items: baseline; gap: 8px;">
        <span class="serif" style="font-size: 18px; font-weight: 600; letter-spacing: -0.025em;">Magister Console</span>
        <span style="font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: #64748b;">Vita Brevis</span>
      </div>
      <nav style="display: flex; align-items: center; gap: 4px; font-size: 14px;">
        <span class="navlink">Kunden</span>
        <span class="navlink">Vorlagen</span>
        <span class="navlink">Rechte</span>
        <span class="navlink">Module</span>
        <span class="navlink active">Betrieb</span>
        <span class="navlink">Audit</span>
      </nav>
    </div>
    <div style="display: flex; align-items: center; gap: 12px;">
      <span class="pill" style="background: rgba(248, 250, 252, 0.1); color: #e2e8f0; box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.25);">Global Admin</span>
      <span style="display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px; border-radius: 9999px; background: #334155; color: #f8fafc; font-size: 11px; font-weight: 600;">MH</span>
    </div>
  </div>
</div>

<div class="shell" style="padding-top: 32px; padding-bottom: 32px;">
  <header>
    <h1 class="serif h1">Datenbank und Migrationen</h1>
    <p class="muted" style="margin: 6px 0 0;">Ein Schema-Stand pro Kunde. Die Anwendung bedient einen Kunden nur, wenn sein Stand zum Code passt.</p>
  </header>

  <div style="display: flex; align-items: flex-end; border-bottom: 1px solid #e2e8f0; margin-top: 20px;">
    <span class="tab active">Datenbank</span>
    <span class="tab">Migrationen</span>
    <span class="tab">Sicherungen</span>
    <span class="tab">AD-Connectoren</span>
  </div>

  <div class="card" style="padding: 20px 24px; margin-top: 24px;">
    <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 24px;">
      <div>
        <h2 class="serif h2" style="font-size: 16px;">Migration <span class="mono">0044_tenant_registry</span> ausrollen</h2>
        <p class="muted" style="margin: 8px 0 0; font-size: 13px;">
          Zuerst der Kanarienvogel-Kunde, dann in Wellen von drei. Ein Fehlschlag h&auml;lt die Welle an;
          der Kunde bleibt auf dem alten Stand und wird auf Wartung gestellt statt falsch bedient.
        </p>
      </div>
      <div style="display: flex; gap: 8px; flex-shrink: 0;">
        <button class="btn btn-outline" type="button">Trockenlauf</button>
        <button class="btn btn-primary" type="button">Welle 1 starten</button>
      </div>
    </div>
    <div style="display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; margin-top: 20px;">
      <div>
        <div class="muted" style="font-size: 13px;">Kopf-Version im Code</div>
        <div class="mono" style="margin-top: 4px; font-size: 15px;">0044</div>
      </div>
      <div>
        <div class="muted" style="font-size: 13px;">Kunden auf 0044</div>
        <div style="margin-top: 4px; font-size: 15px;">1 von 8</div>
      </div>
      <div>
        <div class="muted" style="font-size: 13px;">Kanarienvogel</div>
        <div style="margin-top: 4px; font-size: 15px;">Alpstein Treuhand AG</div>
      </div>
      <div>
        <div class="muted" style="font-size: 13px;">Art der Migration</div>
        <div style="margin-top: 4px; font-size: 15px;">nur erweiternd</div>
      </div>
    </div>
  </div>

  <div class="card" style="margin-top: 16px; overflow: hidden;">
    <table>
      <thead>
        <tr>
          <th style="width: 240px;">Kunde</th>
          <th style="width: 175px;">Trennung</th>
          <th style="width: 210px;">Ziel</th>
          <th style="width: 130px;">DB-Rolle</th>
          <th style="width: 100px;">Stand</th>
          <th style="width: 130px;">Verbindungen</th>
          <th>Letzte Sicherung</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td style="font-weight: 500;">Alpstein Treuhand AG</td>
          <td>Eigenes Schema</td>
          <td class="mono">pg-01 &middot; t_alpstein</td>
          <td class="mono">r_alpstein</td>
          <td><span class="pill pill-ok mono">0044</span></td>
          <td class="muted">3 von 10</td>
          <td class="muted">heute 02:15</td>
        </tr>
        <tr>
          <td style="font-weight: 500;">Gemeinde Wattwil</td>
          <td>Eigenes Schema</td>
          <td class="mono">pg-01 &middot; t_wattwil</td>
          <td class="mono">r_wattwil</td>
          <td><span class="pill pill-muted mono">0043</span></td>
          <td class="muted">6 von 10</td>
          <td class="muted">heute 02:15</td>
        </tr>
        <tr>
          <td style="font-weight: 500;">Stadt Uzwil</td>
          <td>Eigenes Schema</td>
          <td class="mono">pg-01 &middot; t_uzwil</td>
          <td class="mono">r_uzwil</td>
          <td><span class="pill pill-muted mono">0043</span></td>
          <td class="muted">8 von 12</td>
          <td class="muted">heute 02:15</td>
        </tr>
        <tr>
          <td style="font-weight: 500;">Schulgemeinde Flawil</td>
          <td>Eigene Datenbank</td>
          <td class="mono">pg-01 &middot; magister_flawil</td>
          <td class="mono">r_flawil</td>
          <td><span class="pill pill-muted mono">0043</span></td>
          <td class="muted">5 von 10</td>
          <td class="muted">heute 02:22</td>
        </tr>
        <tr>
          <td style="font-weight: 500;">Gemeinde Degersheim</td>
          <td>Eigenes Schema</td>
          <td class="mono">pg-01 &middot; t_degersheim</td>
          <td class="mono">r_degersheim</td>
          <td><span class="pill pill-warn mono">0042</span></td>
          <td class="muted">2 von 10</td>
          <td class="muted">heute 02:15</td>
        </tr>
        <tr>
          <td style="font-weight: 500;">Toggenburg Energie AG</td>
          <td>Eigenes Schema</td>
          <td class="mono">pg-01 &middot; t_tbenergie</td>
          <td class="mono">r_tbenergie</td>
          <td><span class="pill pill-muted mono">0043</span></td>
          <td class="muted">4 von 10</td>
          <td class="muted">heute 02:15</td>
        </tr>
        <tr>
          <td style="font-weight: 500;">Gemeinde Ebnat-Kappel</td>
          <td>Eigene Datenbank</td>
          <td class="mono">pg-02 &middot; magister_ebnat</td>
          <td class="mono">r_ebnat</td>
          <td><span class="pill pill-muted mono">0043</span></td>
          <td class="muted">0 von 10</td>
          <td class="muted">heute 02:31</td>
        </tr>
        <tr>
          <td style="font-weight: 500;">Schulgemeinde Nesslau</td>
          <td class="muted">Eigenes Schema</td>
          <td class="muted mono">pg-01 &middot; wird angelegt</td>
          <td class="muted">&mdash;</td>
          <td class="muted">&mdash;</td>
          <td class="muted">&mdash;</td>
          <td class="muted">&mdash;</td>
        </tr>
      </tbody>
    </table>
  </div>

  <div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin-top: 16px;">
    <div class="card" style="padding: 20px 24px;">
      <h2 class="serif h2" style="font-size: 16px;">Wie die Trennung erzwungen wird</h2>
      <ul style="margin: 16px 0 0; padding-left: 20px; display: grid; gap: 8px; font-size: 13px;">
        <li>Jeder Kunde hat eine eigene DB-Rolle mit <span class="mono">USAGE</span> nur auf sein Schema.</li>
        <li>Pro Transaktion setzt die Anwendung <span class="mono">SET LOCAL ROLE</span> und <span class="mono">SET LOCAL search_path</span> &mdash; beides endet mit der Transaktion, ein Verbindungs-Pool kann nichts weitertragen.</li>
        <li>Vor dem ersten Query pr&uuml;ft eine Zusicherung, dass <span class="mono">current_user</span> zum Kunden der Anfrage passt; sonst bricht die Anfrage ab.</li>
        <li>Ein vergessener Filter liefert damit keine fremden Zeilen, sondern einen Postgres-Fehler.</li>
      </ul>
    </div>
    <div class="card" style="padding: 20px 24px;">
      <h2 class="serif h2" style="font-size: 16px;">Lastgrenzen pro Kunde</h2>
      <div style="display: grid; gap: 10px; margin-top: 16px; font-size: 13px;">
        <div style="display: flex; justify-content: space-between; gap: 12px;">
          <span class="muted">Verbindungen</span><span class="mono">10 (eigene DB: 20)</span>
        </div>
        <div style="display: flex; justify-content: space-between; gap: 12px;">
          <span class="muted">statement_timeout</span><span class="mono">30 s (Import 300 s)</span>
        </div>
        <div style="display: flex; justify-content: space-between; gap: 12px;">
          <span class="muted">Gleichzeitige Auftr&auml;ge</span><span class="mono">2</span>
        </div>
        <div style="display: flex; justify-content: space-between; gap: 12px;">
          <span class="muted">AD-Sync</span><span class="mono">1 Lauf, versetzt gestartet</span>
        </div>
        <div style="display: flex; justify-content: space-between; gap: 12px;">
          <span class="muted">Anfragen pro Minute</span><span class="mono">600</span>
        </div>
      </div>
      <p class="muted" style="margin: 14px 0 0; font-size: 13px;">
        Ein Kunde, der die Grenzen dauerhaft ausreizt, wird auf eine eigene Datenbank oder einen
        eigenen Cluster umgezogen &mdash; gleicher Code-Pfad, nur ein anderer Registry-Eintrag.
      </p>
    </div>
  </div>
</div>
EOF

# ------------------------------------ Kundenkontext: Banner im Kunden-System
emit Kundenkontext.dc.html <<'EOF'
<div style="padding: 32px; background: #f8fafc; min-height: 100vh;">
  <p class="muted" style="margin: 0 0 10px; font-size: 12px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase;">Was der Operator sieht</p>
  <div style="border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; background: #ffffff;">
    <div style="display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 10px 20px; background: #0f172a; color: #f8fafc;">
      <div style="display: flex; align-items: center; gap: 10px;">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#f8fafc" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/></svg>
        <span style="font-size: 13px;">Sie arbeiten als Vita Brevis im Kundenkontext <strong>Gemeinde Wattwil</strong> &middot; Ticket VB-2291 &middot; endet 15:08</span>
      </div>
      <div style="display: flex; align-items: center; gap: 8px;">
        <button class="btn btn-sm" type="button" style="background: rgba(248, 250, 252, 0.12); color: #f8fafc;">Kunde wechseln</button>
        <button class="btn btn-sm" type="button" style="background: #f8fafc; color: #0f172a;">Zur&uuml;ck zur Konsole</button>
      </div>
    </div>
    <div style="display: flex; align-items: center; justify-content: space-between; height: 56px; padding: 0 20px; border-bottom: 1px solid #e2e8f0; background: rgba(255, 255, 255, 0.6);">
      <div style="display: flex; align-items: center; gap: 24px;">
        <span class="serif" style="font-size: 18px; font-weight: 600; letter-spacing: -0.025em;">Magister</span>
        <nav style="display: flex; align-items: center; gap: 4px; font-size: 14px; font-weight: 500;">
          <span style="padding: 6px 12px; border-radius: 6px; background: #f1f5f9; color: #020817;">Klassen</span>
          <span style="padding: 6px 12px; border-radius: 6px; color: #64748b;">Benutzer</span>
          <span style="padding: 6px 12px; border-radius: 6px; color: #64748b;">Ger&auml;te</span>
          <span style="padding: 6px 12px; border-radius: 6px; color: #64748b;">Einstellungen</span>
        </nav>
      </div>
      <span class="muted" style="font-size: 13px;">Gemeinde Wattwil &middot; <span class="mono">wattwil.magister.ch</span></span>
    </div>
    <div style="padding: 20px;">
      <div style="height: 12px; width: 200px; border-radius: 4px; background: #f1f5f9;"></div>
      <div style="height: 12px; width: 420px; border-radius: 4px; background: #f1f5f9; margin-top: 12px;"></div>
      <div style="height: 12px; width: 330px; border-radius: 4px; background: #f1f5f9; margin-top: 12px;"></div>
    </div>
  </div>

  <p class="muted" style="margin: 28px 0 10px; font-size: 12px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase;">Was der Kunde sieht &mdash; w&auml;hrend und nach dem Zugriff</p>
  <div style="border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; background: #ffffff;">
    <div style="display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 12px 20px; background: #fffbeb; border-bottom: 1px solid #fde68a;">
      <div style="display: flex; align-items: center; gap: 10px; color: #b45309;">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#b45309" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>
        <span style="font-size: 13px;">Vita Brevis greift derzeit auf Ihre Instanz zu &middot; matthias.hadorn &middot; Ticket VB-2291 &middot; seit 14:56</span>
      </div>
      <button class="btn btn-sm btn-outline" type="button" style="border-color: #fde68a; color: #b45309;">Zugriff beenden</button>
    </div>
    <div style="display: flex; align-items: center; justify-content: space-between; height: 56px; padding: 0 20px; border-bottom: 1px solid #e2e8f0; background: rgba(255, 255, 255, 0.6);">
      <div style="display: flex; align-items: center; gap: 24px;">
        <span class="serif" style="font-size: 18px; font-weight: 600; letter-spacing: -0.025em;">Magister</span>
        <nav style="display: flex; align-items: center; gap: 4px; font-size: 14px; font-weight: 500;">
          <span style="padding: 6px 12px; border-radius: 6px; background: #f1f5f9; color: #020817;">Klassen</span>
          <span style="padding: 6px 12px; border-radius: 6px; color: #64748b;">Benutzer</span>
          <span style="padding: 6px 12px; border-radius: 6px; color: #64748b;">Ger&auml;te</span>
          <span style="padding: 6px 12px; border-radius: 6px; color: #64748b;">Einstellungen</span>
        </nav>
      </div>
      <span class="muted" style="font-size: 13px;">angemeldet als schulleitung@wattwil.ch</span>
    </div>
    <div style="padding: 20px;">
      <p style="margin: 0; font-size: 13px; font-weight: 500;">Einstellungen &rsaquo; Zugriffe von Vita Brevis</p>
      <table style="margin-top: 12px;">
        <thead>
          <tr>
            <th style="height: 40px; width: 150px;">Zeitpunkt</th>
            <th style="height: 40px; width: 190px;">Person</th>
            <th style="height: 40px; width: 130px;">Ticket</th>
            <th style="height: 40px;">Dauer</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td style="padding: 10px 16px;">05.09. 14:56</td>
            <td style="padding: 10px 16px;" class="mono">matthias.hadorn</td>
            <td style="padding: 10px 16px;" class="mono">VB-2291</td>
            <td style="padding: 10px 16px;" class="muted">l&auml;uft</td>
          </tr>
          <tr>
            <td style="padding: 10px 16px;">28.08. 09:41</td>
            <td style="padding: 10px 16px;" class="mono">support-team</td>
            <td style="padding: 10px 16px;" class="mono">VB-2244</td>
            <td style="padding: 10px 16px;" class="muted">4 Min</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</div>
EOF

# ------------------------------------------------ Kunde -> AD-Connector
emit Connector.dc.html <<'EOF'
<div class="topbar">
  <div class="shell" style="display: flex; height: 56px; align-items: center; justify-content: space-between;">
    <div style="display: flex; align-items: center; gap: 28px;">
      <div style="display: flex; align-items: baseline; gap: 8px;">
        <span class="serif" style="font-size: 18px; font-weight: 600; letter-spacing: -0.025em;">Magister Console</span>
        <span style="font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: #64748b;">Vita Brevis</span>
      </div>
      <nav style="display: flex; align-items: center; gap: 4px; font-size: 14px;">
        <span class="navlink active">Kunden</span>
        <span class="navlink">Vorlagen</span>
        <span class="navlink">Rechte</span>
        <span class="navlink">Module</span>
        <span class="navlink">Betrieb</span>
        <span class="navlink">Audit</span>
      </nav>
    </div>
    <div style="display: flex; align-items: center; gap: 12px;">
      <span class="pill" style="background: rgba(248, 250, 252, 0.1); color: #e2e8f0; box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.25);">Global Admin</span>
      <span style="display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px; border-radius: 9999px; background: #334155; color: #f8fafc; font-size: 11px; font-weight: 600;">MH</span>
    </div>
  </div>
</div>

<div class="shell" style="padding-top: 24px; padding-bottom: 32px;">
  <div class="muted" style="font-size: 13px;">Kunden &nbsp;&rsaquo;&nbsp; Gemeinde Wattwil</div>

  <header style="display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; margin-top: 12px;">
    <div>
      <div style="display: flex; align-items: center; gap: 10px;">
        <h1 class="serif h1">Gemeinde Wattwil</h1>
        <span class="pill pill-ok">Aktiv</span>
      </div>
      <p class="muted" style="margin: 6px 0 0;">
        <span class="mono">wattwil.magister.ch</span> &middot; Profil Schule &middot; Kundennummer K-0041
      </p>
    </div>
    <button class="btn btn-primary" type="button">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/></svg>
      Agent-Paket beziehen
    </button>
  </header>

  <div style="display: flex; align-items: flex-end; border-bottom: 1px solid #e2e8f0; margin-top: 20px;">
    <span class="tab">&Uuml;bersicht</span>
    <span class="tab">Systemeinstellungen</span>
    <span class="tab active">AD-Connector</span>
    <span class="tab">Rechte</span>
    <span class="tab">Vorlagen</span>
    <span class="tab">Datenbank</span>
    <span class="tab">Audit</span>
  </div>

  <div class="note" style="margin-top: 24px; display: flex; gap: 12px; align-items: flex-start;">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#0f172a" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="flex-shrink: 0; margin-top: 1px;"><path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/></svg>
    <div>
      <div style="font-weight: 500;">Der Agent telefoniert nach Hause &mdash; die Plattform ruft nie an</div>
      <p class="muted" style="margin: 4px 0 0;">
        Der Agent baut ausgehend TCP 46200 zu <span class="mono">connect.magister.ch</span> auf und holt dort die
        AD-Auftr&auml;ge ab. LDAPS bleibt vollst&auml;ndig im Kundennetz; beim Kunden ist keine eingehende
        Freigabe n&ouml;tig. Anmeldung mit Client-Zertifikat einer privaten CA <em>und</em> API-Key.
      </p>
    </div>
  </div>

  <div style="display: grid; grid-template-columns: minmax(0, 2.1fr) minmax(0, 1fr); gap: 24px; margin-top: 24px;">
    <div style="display: flex; flex-direction: column; gap: 16px;">

      <div class="card" style="padding: 24px;">
        <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 16px;">
          <div>
            <h2 class="serif h2">Agent <span class="mono" style="font-size: 15px; font-weight: 400;">wattwil-dc-01</span></h2>
            <p class="muted" style="margin: 8px 0 0;">Windows-Dienst auf <span class="mono">SRV-MGMT01.wattwil.local</span></p>
          </div>
          <span class="pill pill-ok">verbunden</span>
        </div>
        <div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 24px; margin-top: 20px; font-size: 13px;">
          <div style="display: flex; justify-content: space-between; gap: 12px; border-bottom: 1px solid #f1f5f9; padding-bottom: 10px;">
            <span class="muted">Letzter Kontakt</span><span>vor 3 Sekunden</span>
          </div>
          <div style="display: flex; justify-content: space-between; gap: 12px; border-bottom: 1px solid #f1f5f9; padding-bottom: 10px;">
            <span class="muted">Agent-Version</span><span class="mono">1.4.2</span>
          </div>
          <div style="display: flex; justify-content: space-between; gap: 12px; border-bottom: 1px solid #f1f5f9; padding-bottom: 10px;">
            <span class="muted">Angemeldet am</span><span>14.08.2026, 10:22</span>
          </div>
          <div style="display: flex; justify-content: space-between; gap: 12px; border-bottom: 1px solid #f1f5f9; padding-bottom: 10px;">
            <span class="muted">Auftr&auml;ge (24 h)</span><span>412, keine Fehler</span>
          </div>
          <div style="display: flex; justify-content: space-between; gap: 12px;">
            <span class="muted">Domänencontroller</span><span class="mono" style="font-size: 12px;">dc01, dc02</span>
          </div>
          <div style="display: flex; justify-content: space-between; gap: 12px;">
            <span class="muted">Mittlere Antwortzeit</span><span>41 ms</span>
          </div>
        </div>
      </div>

      <div class="card" style="padding: 24px;">
        <h2 class="serif h2">Anmeldedaten des Agenten</h2>
        <p class="muted" style="margin: 8px 0 20px;">Zwei unabh&auml;ngige Faktoren, beide an diesen Agenten gebunden. Einer allein wird abgewiesen.</p>
        <div style="border-top: 1px solid #e2e8f0;">
          <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding: 16px 0; border-bottom: 1px solid #e2e8f0;">
            <div style="min-width: 0;">
              <div style="font-weight: 500;">Client-Zertifikat <span class="pill pill-muted" style="margin-left: 6px;">private CA</span></div>
              <div class="muted mono" style="font-size: 12px; margin-top: 4px;">SPKI SHA-256 &nbsp;9f:2a:c1:44:8b:0d:e7:31:5a:6c:be:90:12:4f:a8:d3</div>
              <div class="muted" style="font-size: 13px; margin-top: 4px;">L&auml;uft am 12.11.2026 ab &middot; erneuert sich selbst am 12.10.2026</div>
            </div>
            <div style="display: flex; gap: 8px; flex-shrink: 0;">
              <button class="btn btn-outline btn-sm" type="button">Neu ausstellen</button>
              <button class="btn btn-outline btn-sm" type="button" style="color: #be123c; border-color: #fecdd3;">Widerrufen</button>
            </div>
          </div>
          <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding: 16px 0;">
            <div>
              <div style="font-weight: 500;">API-Key</div>
              <div class="muted" style="font-size: 13px; margin-top: 4px;">Nur als Hash gespeichert &middot; gesetzt am 14.08.2026 &middot; unabh&auml;ngig vom Zertifikat rotierbar</div>
            </div>
            <button class="btn btn-outline btn-sm" type="button" style="flex-shrink: 0;">Rotieren</button>
          </div>
        </div>
        <p class="muted" style="margin: 16px 0 0; font-size: 13px;">
          Der private Schl&uuml;ssel entsteht auf dem Agenten und verl&auml;sst ihn nie. Das Download-Paket
          enth&auml;lt kein Geheimnis, nur den Installer, das CA-Bundle und ein Einmal-Token.
        </p>
      </div>

      <div class="card" style="padding: 24px;">
        <h2 class="serif h2">Was der Agent ausf&uuml;hren darf</h2>
        <p class="muted" style="margin: 8px 0 20px;">Feste Methodenliste. Es gibt keine Auftragsart f&uuml;r beliebiges LDAP, PowerShell oder Skripte.</p>
        <div style="display: flex; flex-wrap: wrap; gap: 8px;">
          <span class="pill pill-muted mono">find_user_dn</span>
          <span class="pill pill-muted mono">fetch_user_groups</span>
          <span class="pill pill-muted mono">modify_password</span>
          <span class="pill pill-muted mono">modify_user_attributes</span>
          <span class="pill pill-muted mono">rename_user</span>
          <span class="pill pill-muted mono">set_proxy_addresses</span>
          <span class="pill pill-muted mono">set_account_enabled</span>
          <span class="pill pill-muted mono">create_user</span>
          <span class="pill pill-muted mono">add_user_to_groups</span>
          <span class="pill pill-muted mono">remove_user_from_groups</span>
          <span class="pill pill-muted mono">delete_user_object</span>
          <span class="pill pill-muted mono">probe_bind_as_user</span>
        </div>
        <div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin-top: 20px;">
          <div>
            <label class="label">Grenzen, die der Agent selbst erzwingt</label>
            <div class="input" style="height: auto; display: block; padding: 12px;">
              <div class="mono" style="font-size: 12px;">OU=Schulen,DC=wattwil,DC=local</div>
              <div class="mono" style="font-size: 12px; margin-top: 4px;">OU=Geraete,DC=wattwil,DC=local</div>
            </div>
          </div>
          <div>
            <label class="label">Gesperrte Gruppen</label>
            <div class="input" style="height: auto; display: block; padding: 12px;">
              <div class="mono" style="font-size: 12px;">Domain Admins, Enterprise Admins,</div>
              <div class="mono" style="font-size: 12px; margin-top: 4px;">Schema Admins, Backup Operators</div>
            </div>
          </div>
        </div>
        <p class="muted" style="margin: 14px 0 0; font-size: 13px;">
          Diese Politik steht in der Konfiguration des Agenten beim Kunden. Auch eine kompromittierte
          Plattform kommt nicht dar&uuml;ber hinaus.
        </p>
      </div>
    </div>

    <div style="display: flex; flex-direction: column; gap: 16px;">
      <div class="card" style="padding: 20px;">
        <h2 class="serif h2" style="font-size: 16px;">Der Kunde beh&auml;lt die Kontrolle</h2>
        <ul style="margin: 14px 0 0; padding-left: 18px; display: grid; gap: 8px; font-size: 13px;">
          <li>Agent stoppen beendet jeden Plattformzugriff auf das AD &mdash; sofort, ohne Vita Brevis.</li>
          <li>Lokales Protokoll auf dem Server, nur anf&uuml;gbar, vom Kunden lesbar.</li>
          <li>Einzelne Operationen lokal abschaltbar.</li>
          <li>Firewall-Anforderung: ausgehend TCP 46200 zu einem Hostnamen. Nichts eingehend.</li>
        </ul>
      </div>

      <div class="card" style="padding: 20px;">
        <h2 class="serif h2" style="font-size: 16px;">Letzte Ereignisse</h2>
        <div style="display: grid; gap: 14px; margin-top: 16px; font-size: 13px;">
          <div>
            <div style="font-weight: 500;">Zertifikat erneuert</div>
            <div class="muted">12.08.2026, 03:14 &middot; automatisch</div>
          </div>
          <div>
            <div style="font-weight: 500;">Agent auf 1.4.2 aktualisiert</div>
            <div class="muted">28.07.2026, 22:05 &middot; freigegeben von matthias.hadorn</div>
          </div>
          <div>
            <div style="font-weight: 500;">Verbindung 6 Min unterbrochen</div>
            <div class="muted">19.07.2026, 14:31 &middot; Auftr&auml;ge liefen in <span class="mono">503</span></div>
          </div>
          <div>
            <div style="font-weight: 500;">Agent angemeldet</div>
            <div class="muted">14.08.2026, 10:22 &middot; Token eingel&ouml;st</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
EOF

# ----------------------------------------------------- Agent-Paket beziehen
emit AgentSetup.dc.html <<'EOF'
<div style="display: flex; min-height: 100vh; align-items: center; justify-content: center; background: rgba(2, 8, 23, 0.45); padding: 24px;">
  <div class="card" style="width: 100%; max-width: 720px;">
    <div style="padding: 24px; border-bottom: 1px solid #e2e8f0;">
      <h1 class="serif h2">Agent-Paket beziehen</h1>
      <p class="muted" style="margin: 8px 0 0;">Gemeinde Wattwil &middot; das Paket enth&auml;lt kein Geheimnis.</p>
    </div>

    <div style="padding: 24px; display: flex; flex-direction: column; gap: 20px;">
      <div>
        <label class="label">Plattform</label>
        <div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px;">
          <label style="display: flex; gap: 10px; padding: 14px; border: 1px solid #0f172a; border-radius: 8px; background: #f8fafc;">
            <span style="flex-shrink: 0; margin-top: 2px; width: 16px; height: 16px; border-radius: 9999px; border: 1px solid #0f172a; display: inline-flex; align-items: center; justify-content: center;"><span style="width: 8px; height: 8px; border-radius: 9999px; background: #0f172a;"></span></span>
            <span>
              <span style="display: block; font-weight: 500;">Windows</span>
              <span class="muted" style="display: block; font-size: 13px; margin-top: 2px;">MSI, als Dienst</span>
            </span>
          </label>
          <label style="display: flex; gap: 10px; padding: 14px; border: 1px solid #e2e8f0; border-radius: 8px;">
            <span style="flex-shrink: 0; margin-top: 2px; width: 16px; height: 16px; border-radius: 9999px; border: 1px solid #cbd5e1;"></span>
            <span>
              <span style="display: block; font-weight: 500;">Linux</span>
              <span class="muted" style="display: block; font-size: 13px; margin-top: 2px;">.deb, systemd</span>
            </span>
          </label>
          <label style="display: flex; gap: 10px; padding: 14px; border: 1px solid #e2e8f0; border-radius: 8px;">
            <span style="flex-shrink: 0; margin-top: 2px; width: 16px; height: 16px; border-radius: 9999px; border: 1px solid #cbd5e1;"></span>
            <span>
              <span style="display: block; font-weight: 500;">Container</span>
              <span class="muted" style="display: block; font-size: 13px; margin-top: 2px;">OCI-Image</span>
            </span>
          </label>
        </div>
      </div>

      <div>
        <label class="label">Einmal-Token f&uuml;r die Anmeldung</label>
        <div class="input" style="justify-content: space-between; background: #f8fafc;">
          <span class="mono">wtw-4KQ7-9RJP-2M6X-D8LA</span>
          <span style="display: inline-flex; align-items: center; gap: 12px;">
            <span class="pill pill-warn">g&uuml;ltig 23 h 58 min</span>
            <span style="font-size: 13px; font-weight: 500;">Kopieren</span>
          </span>
        </div>
        <p class="muted" style="margin: 8px 0 0; font-size: 13px;">
          Einmal einl&ouml;sbar und an diesen Kunden gebunden. Der Agent erzeugt beim ersten Start sein
          Schl&uuml;sselpaar selbst, schickt einen CSR mit dem Token und erh&auml;lt Zertifikat und API-Key
          zur&uuml;ck. Ein privater Schl&uuml;ssel wird nie ausgeliefert.
        </p>
      </div>

      <div>
        <label class="label">Paket</label>
        <div class="input" style="height: auto; display: block; padding: 14px;">
          <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px;">
            <span class="mono" style="font-size: 13px;">magister-connector-1.4.2-x64.msi</span>
            <span class="muted" style="font-size: 13px;">18.4 MB</span>
          </div>
          <div class="muted mono" style="font-size: 12px; margin-top: 8px;">SHA-256 &nbsp;3c:1f:88:d0:5b:a7:44:2e:91:6c:0b:fd:37:82:ae:19</div>
          <div class="muted" style="font-size: 13px; margin-top: 6px;">Signiert von Vita Brevis GmbH &middot; enthält das CA-Bundle f&uuml;r das Pinning</div>
        </div>
      </div>

      <div class="note">
        <div style="font-weight: 500; font-size: 13px;">Was die Kunden-IT vorbereiten muss</div>
        <ul style="margin: 8px 0 0; padding-left: 18px; display: grid; gap: 6px; font-size: 13px;" class="muted">
          <li>Ausgehend <span class="mono">TCP 46200</span> zu <span class="mono">connect.magister.ch</span> erlauben. Nichts eingehend.</li>
          <li>Dienstkonto mit den delegierten AD-Rechten (Kennwort zur&uuml;cksetzen, Attribute schreiben) auf den freigegebenen OUs.</li>
          <li>Netzsicht auf die eigenen Domänencontroller &uuml;ber <span class="mono">LDAPS 636</span>.</li>
        </ul>
      </div>

      <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 4px;">
        <span class="muted" style="font-size: 13px;">Download und Anmeldung werden auditiert.</span>
        <div style="display: flex; gap: 8px;">
          <button class="btn btn-outline" type="button">Abbrechen</button>
          <button class="btn btn-primary" type="button">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/></svg>
            Paket herunterladen
          </button>
        </div>
      </div>
    </div>
  </div>
</div>
EOF

# --------------------------------------------------- TOTP für lokales Konto
emit MfaSetup.dc.html <<'EOF'
<div style="display: flex; min-height: 100vh; align-items: center; justify-content: center; background: #ffffff; padding: 24px;">
  <div class="card" style="width: 100%; max-width: 448px;">
    <div style="padding: 24px 24px 0;">
      <h1 class="serif" style="font-size: 20px; line-height: 20px; font-weight: 600; letter-spacing: -0.025em; margin: 0;">Zweiten Faktor einrichten</h1>
      <p class="muted" style="margin: 10px 0 0;">
        Das lokale Konto <span class="mono">admin</span> ist der Notzugang, wenn Entra ID nicht erreichbar
        ist. Er verlangt einen zweiten Faktor &mdash; ohne Einrichtung geht es nicht weiter.
      </p>
    </div>

    <div style="padding: 24px; display: flex; flex-direction: column; gap: 20px;">
      <div style="display: flex; justify-content: center;">
        <div style="width: 168px; height: 168px; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; background: #ffffff;">
          <svg viewBox="0 0 21 21" width="144" height="144" shape-rendering="crispEdges" aria-label="QR-Code Platzhalter">
            <rect width="21" height="21" fill="#ffffff"/>
            <g fill="#020817">
              <path d="M0 0h7v1H0zM8 0h1v1H8zM10 0h2v1h-2zM14 0h7v1h-7z"/>
              <path d="M0 1h1v1H0zM6 1h1v1H6zM9 1h3v1H9zM14 1h1v1h-1zM20 1h1v1h-1z"/>
              <path d="M0 2h1v1H0zM2 2h3v1H2zM6 2h1v1H6zM8 2h1v1H8zM11 2h1v1h-1zM14 2h1v1h-1zM16 2h3v1h-3zM20 2h1v1h-1z"/>
              <path d="M0 3h1v1H0zM2 3h3v1H2zM6 3h1v1H6zM9 3h1v1H9zM12 3h1v1h-1zM14 3h1v1h-1zM16 3h3v1h-3zM20 3h1v1h-1z"/>
              <path d="M0 4h1v1H0zM2 4h3v1H2zM6 4h1v1H6zM8 4h2v1H8zM11 4h1v1h-1zM14 4h1v1h-1zM16 4h3v1h-3zM20 4h1v1h-1z"/>
              <path d="M0 5h1v1H0zM6 5h1v1H6zM10 5h1v1h-1zM12 5h1v1h-1zM14 5h1v1h-1zM20 5h1v1h-1z"/>
              <path d="M0 6h7v1H0zM8 6h1v1H8zM10 6h2v1h-2zM14 6h7v1h-7z"/>
              <path d="M9 7h1v1H9zM11 7h2v1h-2z"/>
              <path d="M0 8h2v1H0zM3 8h2v1H3zM6 8h4v1H6zM12 8h2v1h-2zM15 8h1v1h-1zM17 8h4v1h-4z"/>
              <path d="M1 9h1v1H1zM4 9h1v1H4zM8 9h1v1H8zM10 9h1v1h-1zM13 9h3v1h-3zM18 9h1v1h-1zM20 9h1v1h-1z"/>
              <path d="M0 10h3v1H0zM5 10h2v1H5zM9 10h2v1H9zM12 10h1v1h-1zM14 10h2v1h-2zM17 10h2v1h-2zM20 10h1v1h-1z"/>
              <path d="M2 11h1v1H2zM4 11h1v1H4zM7 11h1v1H7zM10 11h3v1h-3zM15 11h1v1h-1zM17 11h1v1h-1zM19 11h2v1h-2z"/>
              <path d="M0 12h2v1H0zM3 12h3v1H3zM8 12h1v1H8zM11 12h1v1h-1zM13 12h2v1h-2zM16 12h2v1h-2zM20 12h1v1h-1z"/>
              <path d="M8 13h2v1H8zM11 13h2v1h-2zM14 13h1v1h-1zM16 13h1v1h-1zM18 13h1v1h-1z"/>
              <path d="M0 14h7v1H0zM9 14h1v1H9zM12 14h2v1h-2zM16 14h2v1h-2zM19 14h1v1h-1z"/>
              <path d="M0 15h1v1H0zM6 15h1v1H6zM8 15h2v1H8zM11 15h1v1h-1zM14 15h1v1h-1zM17 15h1v1h-1zM20 15h1v1h-1z"/>
              <path d="M0 16h1v1H0zM2 16h3v1H2zM6 16h1v1H6zM9 16h1v1H9zM12 16h3v1h-3zM16 16h2v1h-2zM19 16h2v1h-2z"/>
              <path d="M0 17h1v1H0zM2 17h3v1H2zM6 17h1v1H6zM8 17h1v1H8zM10 17h1v1h-1zM13 17h1v1h-1zM15 17h1v1h-1zM18 17h1v1h-1z"/>
              <path d="M0 18h1v1H0zM2 18h3v1H2zM6 18h1v1H6zM9 18h3v1H9zM14 18h2v1h-2zM17 18h2v1h-2zM20 18h1v1h-1z"/>
              <path d="M0 19h1v1H0zM6 19h1v1H6zM8 19h1v1H8zM11 19h1v1h-1zM13 19h1v1h-1zM16 19h1v1h-1zM19 19h1v1h-1z"/>
              <path d="M0 20h7v1H0zM8 20h2v1H8zM12 20h3v1h-3zM17 20h2v1h-2zM20 20h1v1h-1z"/>
            </g>
          </svg>
        </div>
      </div>

      <div>
        <label class="label">Falls die Kamera nicht geht</label>
        <div class="input" style="justify-content: space-between; background: #f8fafc;">
          <span class="mono" style="font-size: 12px;">JBSW Y3DP EHPK 3PXP GQ7A</span>
          <span style="font-size: 13px; font-weight: 500;">Kopieren</span>
        </div>
      </div>

      <div>
        <label class="label">Code aus der App</label>
        <div class="input"><span class="ph mono" style="letter-spacing: 0.3em;">000000</span></div>
      </div>

      <div class="note">
        <div style="font-weight: 500; font-size: 13px;">Wiederherstellungscodes</div>
        <p class="muted" style="margin: 6px 0 10px; font-size: 13px;">
          Zehn Codes, jeder einmal verwendbar. Sie werden nur jetzt angezeigt.
        </p>
        <div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px 16px;">
          <span class="mono" style="font-size: 12px;">4KQ7-9RJP</span>
          <span class="mono" style="font-size: 12px;">2M6X-D8LA</span>
          <span class="mono" style="font-size: 12px;">7TVB-1NZC</span>
          <span class="mono" style="font-size: 12px;">9HDK-3WQE</span>
          <span class="mono" style="font-size: 12px;">6PYF-8SLM</span>
          <span class="mono" style="font-size: 12px;">1RKG-5XJT</span>
          <span class="muted" style="font-size: 12px;">und 4 weitere</span>
        </div>
        <button class="btn btn-outline btn-sm" type="button" style="margin-top: 12px;">Als Datei speichern</button>
      </div>

      <button class="btn btn-primary" type="button" style="width: 100%;">Einrichtung abschliessen</button>
      <p class="muted" style="margin: 0; font-size: 13px; text-align: center;">
        Der direkte AD-Login ist entfernt. Es bleiben Entra ID und dieses Konto.
      </p>
    </div>
  </div>
</div>
EOF

# ------------------------------------------------------------- Zugangswege
emit Zugangswege.dc.html <<'EOF'
<div class="topbar">
  <div class="shell" style="display: flex; height: 56px; align-items: center; justify-content: space-between;">
    <div style="display: flex; align-items: center; gap: 28px;">
      <div style="display: flex; align-items: baseline; gap: 8px;">
        <span class="serif" style="font-size: 18px; font-weight: 600; letter-spacing: -0.025em;">Magister Console</span>
        <span style="font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: #64748b;">Vita Brevis</span>
      </div>
      <nav style="display: flex; align-items: center; gap: 4px; font-size: 14px;">
        <span class="navlink">Kunden</span>
        <span class="navlink">Vorlagen</span>
        <span class="navlink">Rechte</span>
        <span class="navlink">Module</span>
        <span class="navlink active">Betrieb</span>
        <span class="navlink">Audit</span>
      </nav>
    </div>
    <div style="display: flex; align-items: center; gap: 12px;">
      <span class="pill" style="background: rgba(248, 250, 252, 0.1); color: #e2e8f0; box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.25);">Global Admin</span>
      <span style="display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px; border-radius: 9999px; background: #334155; color: #f8fafc; font-size: 11px; font-weight: 600;">MH</span>
    </div>
  </div>
</div>

<div class="shell" style="padding-top: 32px; padding-bottom: 32px;">
  <header>
    <h1 class="serif h1">Zugangswege</h1>
    <p class="muted" style="margin: 6px 0 0;">Nach der H&auml;rtung hat jeder verbleibende Weg einen zweiten Faktor.</p>
  </header>

  <div style="display: flex; align-items: flex-end; border-bottom: 1px solid #e2e8f0; margin-top: 20px;">
    <span class="tab">Datenbank</span>
    <span class="tab">Migrationen</span>
    <span class="tab">Sicherungen</span>
    <span class="tab">AD-Connectoren</span>
    <span class="tab active">Zugangswege</span>
  </div>

  <div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; margin-top: 24px;">
    <div class="card" style="padding: 20px;">
      <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px;">
        <h2 class="serif h2" style="font-size: 16px;">Kunde</h2>
        <span class="pill pill-ok">aktiv</span>
      </div>
      <p style="margin: 12px 0 0; font-weight: 500;">Entra ID (OIDC)</p>
      <p class="muted" style="margin: 6px 0 0; font-size: 13px;">
        Der einzige Weg f&uuml;r Lehr- und Leitungspersonen. Aus dem Internet erreichbar und mit MFA
        gesch&uuml;tzt &mdash; die MFA kommt aus der Conditional-Access-Politik des Kunden, nicht aus
        Magister.
      </p>
      <div style="display: grid; gap: 8px; margin-top: 16px; font-size: 13px;">
        <div style="display: flex; justify-content: space-between; gap: 12px;">
          <span class="muted">Listener</span><span class="mono">443 &ouml;ffentlich</span>
        </div>
        <div style="display: flex; justify-content: space-between; gap: 12px;">
          <span class="muted">Zweiter Faktor</span><span>Conditional Access</span>
        </div>
        <div style="display: flex; justify-content: space-between; gap: 12px;">
          <span class="muted">Passwort in Magister</span><span>nie</span>
        </div>
      </div>
    </div>

    <div class="card" style="padding: 20px;">
      <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px;">
        <h2 class="serif h2" style="font-size: 16px;">Notzugang</h2>
        <span class="pill pill-warn">nur on-prem</span>
      </div>
      <p style="margin: 12px 0 0; font-weight: 500;">Lokales Konto mit TOTP</p>
      <p class="muted" style="margin: 6px 0 0; font-size: 13px;">
        F&uuml;r den Fall, dass Entra ID nicht erreichbar ist. Einrichtung erzwungen,
        Wiederherstellungscodes einmalig, Zur&uuml;cksetzen &uuml;ber Konsole oder CLI. Gehostet ist
        dieser Weg ganz abgeschaltet.
      </p>
      <div style="display: grid; gap: 8px; margin-top: 16px; font-size: 13px;">
        <div style="display: flex; justify-content: space-between; gap: 12px;">
          <span class="muted">Listener</span><span class="mono">443 &ouml;ffentlich</span>
        </div>
        <div style="display: flex; justify-content: space-between; gap: 12px;">
          <span class="muted">Zweiter Faktor</span><span>TOTP, RFC 6238</span>
        </div>
        <div style="display: flex; justify-content: space-between; gap: 12px;">
          <span class="muted">Kontosperre</span><span>5 Fehlversuche</span>
        </div>
      </div>
    </div>

    <div class="card" style="padding: 20px; border-color: #cbd5e1;">
      <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px;">
        <h2 class="serif h2" style="font-size: 16px;">Konsole</h2>
        <span class="pill pill-ok">aktiv</span>
      </div>
      <p style="margin: 12px 0 0; font-weight: 500;">Eigener Listener plus Client-Zertifikat</p>
      <p class="muted" style="margin: 6px 0 0; font-size: 13px;">
        Nur im internen Netz &mdash; der Listener wird nie auf der &ouml;ffentlichen Adresse gebunden,
        erreichbar allein vom Management-Server. Client-Zertifikat der privaten CA verpflichtend, dazu
        ein Marker-Riegel in der Anwendung. Die Identit&auml;t bleibt Entra mit Hardware-Schl&uuml;ssel.
      </p>
      <div style="display: grid; gap: 8px; margin-top: 16px; font-size: 13px;">
        <div style="display: flex; justify-content: space-between; gap: 12px;">
          <span class="muted">Listener</span><span class="mono">10.0.0.5:4444</span>
        </div>
        <div style="display: flex; justify-content: space-between; gap: 12px;">
          <span class="muted">Zweiter Faktor</span><span>WebAuthn / FIDO2</span>
        </div>
        <div style="display: flex; justify-content: space-between; gap: 12px;">
          <span class="muted">Aus dem Internet</span><span>nicht geroutet</span>
        </div>
      </div>
    </div>
  </div>

  <div class="card" style="margin-top: 16px; padding: 20px 24px; background: #f8fafc;">
    <div style="display: flex; align-items: flex-start; gap: 14px;">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="flex-shrink: 0; margin-top: 2px;"><circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/></svg>
      <div>
        <div style="display: flex; align-items: center; gap: 10px;">
          <span style="font-weight: 500; text-decoration: line-through; text-decoration-color: #94a3b8;">Direkter AD-Login</span>
          <span class="pill pill-muted">entfernt, nicht abgeschaltet</span>
        </div>
        <p class="muted" style="margin: 8px 0 0; font-size: 13px; max-width: 980px;">
          Nahm das Klartext-Passwort eines Verzeichnisbenutzers an und band es per LDAPS gegen das AD &mdash;
          ohne zweiten Faktor, also als Umgehung der MFA auf dem OIDC-Pfad, und &uuml;ber einen &ouml;ffentlich
          erreichbaren Endpunkt, der echte AD-Konten durchprobieren und reihenweise sperren liess. Ein
          Schalter gen&uuml;gt nicht: der Code verschwindet, und der Start bricht ab, wenn
          <span class="mono">MAGISTER_AD_LOGIN_*</span> noch gesetzt ist.
        </p>
      </div>
    </div>
  </div>

  <div class="card" style="margin-top: 16px; overflow: hidden;">
    <table>
      <thead>
        <tr>
          <th style="width: 250px;">Listener</th>
          <th style="width: 240px;">Adresse</th>
          <th style="width: 250px;">Wer</th>
          <th style="width: 190px;">Client-Zertifikat</th>
          <th>Zweiter Faktor</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>
            <div style="font-weight: 500;">Kundenoberfl&auml;che</div>
            <div class="muted mono" style="font-size: 12.5px;">&lt;kunde&gt;.magister.ch</div>
          </td>
          <td class="mono">0.0.0.0:443</td>
          <td>Lehr- und Leitungspersonen</td>
          <td class="muted">nein</td>
          <td>MFA &uuml;ber Entra</td>
        </tr>
        <tr>
          <td>
            <div style="font-weight: 500;">Konsole</div>
            <div class="muted mono" style="font-size: 12.5px;">console.magister.ch</div>
          </td>
          <td class="mono">10.0.0.5:4444</td>
          <td>Global Admin, Global Operator</td>
          <td><span class="pill pill-ok">erforderlich</span></td>
          <td>WebAuthn &uuml;ber Entra</td>
        </tr>
        <tr>
          <td>
            <div style="font-weight: 500;">Connector</div>
            <div class="muted mono" style="font-size: 12.5px;">connect.magister.ch</div>
          </td>
          <td class="mono">0.0.0.0:46200</td>
          <td>Connector-Agenten der Kunden</td>
          <td><span class="pill pill-ok">erforderlich</span></td>
          <td>API-Key derselben Zeile</td>
        </tr>
        <tr>
          <td>
            <div style="font-weight: 500;">AD-RPC intern</div>
            <div class="muted mono" style="font-size: 12.5px;">/internal/ad-rpc</div>
          </td>
          <td class="mono">nur Container-Netz</td>
          <td>Geschwister-Container</td>
          <td class="muted">nein</td>
          <td>gemeinsames Geheimnis</td>
        </tr>
      </tbody>
    </table>
    <div style="border-top: 1px solid #e2e8f0; padding: 14px 16px;">
      <p class="muted" style="margin: 0; font-size: 13px;">
        Das Usermanagement des Kunden geh&ouml;rt ins Internet, das Global Management nicht. Getrennte
        Listener sind die Voraussetzung daf&uuml;r: nur so l&auml;sst sich die Konsole an die interne
        Adresse binden, w&auml;hrend 443 &ouml;ffentlich bleibt. Jeder Kunde hat dort seine eigene
        Subdomain und damit eine eigene Origin. Quell-IP-Regeln macht die Fortigate mit der WAF &mdash;
        nicht Magister.
      </p>
    </div>
  </div>
</div>
EOF

# --------------------------------------- Kunde -> Notzugang (TOTP-Verwaltung)
emit Notzugang.dc.html <<'EOF'
<div class="topbar">
  <div class="shell" style="display: flex; height: 56px; align-items: center; justify-content: space-between;">
    <div style="display: flex; align-items: center; gap: 28px;">
      <div style="display: flex; align-items: baseline; gap: 8px;">
        <span class="serif" style="font-size: 18px; font-weight: 600; letter-spacing: -0.025em;">Magister Console</span>
        <span style="font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: #64748b;">Vita Brevis</span>
      </div>
      <nav style="display: flex; align-items: center; gap: 4px; font-size: 14px;">
        <span class="navlink active">Kunden</span>
        <span class="navlink">Vorlagen</span>
        <span class="navlink">Rechte</span>
        <span class="navlink">Module</span>
        <span class="navlink">Betrieb</span>
        <span class="navlink">Audit</span>
      </nav>
    </div>
    <div style="display: flex; align-items: center; gap: 12px;">
      <span class="pill" style="background: rgba(248, 250, 252, 0.1); color: #e2e8f0; box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.25);">Global Admin</span>
      <span style="display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px; border-radius: 9999px; background: #334155; color: #f8fafc; font-size: 11px; font-weight: 600;">MH</span>
    </div>
  </div>
</div>

<div class="shell" style="padding-top: 24px; padding-bottom: 32px;">
  <div class="muted" style="font-size: 13px;">Kunden &nbsp;&rsaquo;&nbsp; Schulgemeinde Flawil</div>

  <header style="margin-top: 12px;">
    <div style="display: flex; align-items: center; gap: 10px;">
      <h1 class="serif h1">Schulgemeinde Flawil</h1>
      <span class="pill pill-ok">Aktiv</span>
    </div>
    <p class="muted" style="margin: 6px 0 0;">
      <span class="mono">flawil.magister.ch</span> &middot; Profil Schule &middot; Kundennummer K-0043
    </p>
  </header>

  <div style="display: flex; align-items: flex-end; border-bottom: 1px solid #e2e8f0; margin-top: 20px;">
    <span class="tab">&Uuml;bersicht</span>
    <span class="tab">Systemeinstellungen</span>
    <span class="tab">AD-Connector</span>
    <span class="tab active">Notzugang</span>
    <span class="tab">Rechte</span>
    <span class="tab">Vorlagen</span>
    <span class="tab">Audit</span>
  </div>

  <div style="display: grid; grid-template-columns: minmax(0, 2.1fr) minmax(0, 1fr); gap: 24px; margin-top: 24px;">
    <div style="display: flex; flex-direction: column; gap: 16px;">

      <div class="card" style="padding: 24px;">
        <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 16px;">
          <div>
            <h2 class="serif h2">Lokales Konto <span class="mono" style="font-size: 15px; font-weight: 400;">admin</span></h2>
            <p class="muted" style="margin: 8px 0 0;">Notzugang, wenn Entra ID nicht erreichbar ist.</p>
          </div>
          <span class="pill pill-ok">zweiter Faktor aktiv</span>
        </div>
        <div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 24px; margin-top: 20px; font-size: 13px;">
          <div style="display: flex; justify-content: space-between; gap: 12px; border-bottom: 1px solid #f1f5f9; padding-bottom: 10px;">
            <span class="muted">TOTP best&auml;tigt am</span><span>02.07.2026</span>
          </div>
          <div style="display: flex; justify-content: space-between; gap: 12px; border-bottom: 1px solid #f1f5f9; padding-bottom: 10px;">
            <span class="muted">Letzte Anmeldung</span><span>28.08.2026, 09:41</span>
          </div>
          <div style="display: flex; justify-content: space-between; gap: 12px; border-bottom: 1px solid #f1f5f9; padding-bottom: 10px;">
            <span class="muted">Wiederherstellungscodes</span><span>7 von 10 offen</span>
          </div>
          <div style="display: flex; justify-content: space-between; gap: 12px; border-bottom: 1px solid #f1f5f9; padding-bottom: 10px;">
            <span class="muted">Fehlversuche</span><span>0 &middot; nicht gesperrt</span>
          </div>
          <div style="display: flex; justify-content: space-between; gap: 12px;">
            <span class="muted">Passwort ge&auml;ndert</span><span>14.05.2026</span>
          </div>
          <div style="display: flex; justify-content: space-between; gap: 12px;">
            <span class="muted">MFA-Pflicht</span><span>aktiv</span>
          </div>
        </div>
      </div>

      <div class="card" style="padding: 24px;">
        <h2 class="serif h2">Eingriffe</h2>
        <p class="muted" style="margin: 8px 0 20px;">Vier Aktionen. Nur die letzte schw&auml;cht etwas ab &mdash; und nur befristet.</p>
        <div style="border-top: 1px solid #e2e8f0;">
          <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding: 16px 0; border-bottom: 1px solid #e2e8f0;">
            <div>
              <div style="font-weight: 500;">TOTP zur&uuml;cksetzen</div>
              <div class="muted" style="font-size: 13px; margin-top: 3px;">
                L&ouml;scht Geheimnis, Best&auml;tigung und alle Wiederherstellungscodes. Beim n&auml;chsten
                Anmelden landet das Konto zwingend in der Einrichtung. Die MFA-Pflicht bleibt.
              </div>
            </div>
            <button class="btn btn-outline btn-sm" type="button" style="flex-shrink: 0;">Zur&uuml;cksetzen</button>
          </div>
          <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding: 16px 0; border-bottom: 1px solid #e2e8f0;">
            <div>
              <div style="font-weight: 500;">Neue Wiederherstellungscodes</div>
              <div class="muted" style="font-size: 13px; margin-top: 3px;">
                Frischer Satz, Geheimnis unber&uuml;hrt. F&uuml;r &bdquo;Codes verbraucht&ldquo;, nicht f&uuml;r
                &bdquo;Telefon weg&ldquo;.
              </div>
            </div>
            <button class="btn btn-outline btn-sm" type="button" style="flex-shrink: 0;">Neu erzeugen</button>
          </div>
          <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding: 16px 0; border-bottom: 1px solid #e2e8f0;">
            <div>
              <div style="font-weight: 500;">Konto deaktivieren</div>
              <div class="muted" style="font-size: 13px; margin-top: 3px;">
                Der Notzugang ist zu. Das ist das &bdquo;L&ouml;schen&ldquo;, das keine L&uuml;cke aufmacht.
              </div>
            </div>
            <button class="btn btn-outline btn-sm" type="button" style="flex-shrink: 0;">Deaktivieren</button>
          </div>
          <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding: 16px 0;">
            <div>
              <div style="display: flex; align-items: center; gap: 8px;">
                <span style="font-weight: 500;">MFA-Pflicht befristet aufheben</span>
                <span class="pill pill-danger">24 Stunden</span>
              </div>
              <div class="muted" style="font-size: 13px; margin-top: 3px;">
                Passwort allein gen&uuml;gt wieder. Greift nach 24 Stunden von selbst wieder, ohne
                Verl&auml;ngerungsknopf. Verlangt Grund oder Ticket und zeigt dem Kunden einen Warnbalken.
              </div>
            </div>
            <button class="btn btn-outline btn-sm" type="button" style="flex-shrink: 0; color: #be123c; border-color: #fecdd3;">Aufheben</button>
          </div>
        </div>
      </div>

      <div class="card" style="padding: 24px;">
        <h2 class="serif h2">On-prem: derselbe Eingriff auf dem Server</h2>
        <p class="muted" style="margin: 8px 0 16px;">
          Eine Installation beim Kunden hat keine Konsole. Dort macht es das CLI &mdash; wer Shell-Zugang
          auf die Box hat, hat ohnehin Datenbank-Zugang; das Verfahren gibt keine neuen Rechte, es macht
          den Eingriff nur auditierbar statt zu einem <span class="mono">UPDATE</span> von Hand.
        </p>
        <div style="border: 1px solid #e2e8f0; border-radius: 6px; background: #0f172a; padding: 14px 16px;">
          <div class="mono" style="font-size: 12.5px; color: #94a3b8;">$ magister-cli local-admin totp-reset</div>
          <div class="mono" style="font-size: 12.5px; color: #f8fafc; margin-top: 6px;">Konto &bdquo;admin&ldquo; zur&uuml;ckgesetzt. Einrichtung beim n&auml;chsten Anmelden erforderlich.</div>
          <div class="mono" style="font-size: 12.5px; color: #94a3b8; margin-top: 10px;">$ magister-cli local-admin totp-reset --new-recovery-codes</div>
          <div class="mono" style="font-size: 12.5px; color: #94a3b8; margin-top: 6px;">$ magister-cli local-admin totp-reset --disable</div>
        </div>
      </div>
    </div>

    <div style="display: flex; flex-direction: column; gap: 16px;">
      <div class="card" style="padding: 20px;">
        <h2 class="serif h2" style="font-size: 16px;">Was ein Reset nicht kann</h2>
        <ul style="margin: 14px 0 0; padding-left: 18px; display: grid; gap: 8px; font-size: 13px;">
          <li>Ein Reset <strong>zeigt nie ein Geheimnis</strong>. Er l&ouml;scht nur; das neue Geheimnis
            entsteht bei der Einrichtung durch den Kunden.</li>
          <li>Ein Operator kann sich damit also keinen funktionierenden zweiten Faktor ausstellen.</li>
          <li>Das Passwort zur&uuml;cksetzen ist eine <strong>getrennte, getrennt auditierte</strong>
            Handlung.</li>
        </ul>
      </div>

      <div class="card" style="padding: 20px;">
        <h2 class="serif h2" style="font-size: 16px;">Der Kunde sieht jeden Eingriff</h2>
        <p class="muted" style="margin: 8px 0 16px; font-size: 13px;">
          Dieselben Ereignisse stehen im Audit des Kunden und in dessen Liste
          &bdquo;Zugriffe von Vita Brevis&ldquo;.
        </p>
        <div style="display: grid; gap: 8px; font-size: 13px;">
          <span class="pill pill-muted mono" style="justify-self: start;">local_totp_reset</span>
          <span class="pill pill-muted mono" style="justify-self: start;">local_recovery_codes_regenerated</span>
          <span class="pill pill-muted mono" style="justify-self: start;">local_account_disabled</span>
          <span class="pill pill-warn mono" style="justify-self: start;">local_mfa_requirement_suspended</span>
        </div>
      </div>

      <div class="card" style="padding: 20px;">
        <h2 class="serif h2" style="font-size: 16px;">Letzte Eingriffe</h2>
        <div style="display: grid; gap: 14px; margin-top: 16px; font-size: 13px;">
          <div>
            <div style="font-weight: 500;">TOTP zur&uuml;ckgesetzt</div>
            <div class="muted">02.07.2026, 08:12 &middot; Ticket VB-2118 &middot; matthias.hadorn</div>
            <div class="muted">Grund: Telefonwechsel Schulleitung</div>
          </div>
          <div>
            <div style="font-weight: 500;">Wiederherstellungscodes erneuert</div>
            <div class="muted">14.05.2026, 16:40 &middot; Ticket VB-1994 &middot; support-team</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
EOF

# ---------------------------------------- Betrieb: Sicherungen pro Kunde
emit Sicherungen.dc.html <<'EOF'
<div class="topbar">
  <div class="shell" style="display: flex; height: 56px; align-items: center; justify-content: space-between;">
    <div style="display: flex; align-items: center; gap: 28px;">
      <div style="display: flex; align-items: baseline; gap: 8px;">
        <span class="serif" style="font-size: 18px; font-weight: 600; letter-spacing: -0.025em;">Magister Console</span>
        <span style="font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: #64748b;">Vita Brevis</span>
      </div>
      <nav style="display: flex; align-items: center; gap: 4px; font-size: 14px;">
        <span class="navlink">Kunden</span>
        <span class="navlink">Vorlagen</span>
        <span class="navlink">Rechte</span>
        <span class="navlink">Module</span>
        <span class="navlink active">Betrieb</span>
        <span class="navlink">Audit</span>
      </nav>
    </div>
    <div style="display: flex; align-items: center; gap: 12px;">
      <span class="pill" style="background: rgba(248, 250, 252, 0.1); color: #e2e8f0; box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.25);">Global Admin</span>
      <span style="display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px; border-radius: 9999px; background: #334155; color: #f8fafc; font-size: 11px; font-weight: 600;">MH</span>
    </div>
  </div>
</div>

<div class="shell" style="padding-top: 32px; padding-bottom: 32px;">
  <header style="display: flex; align-items: flex-start; justify-content: space-between; gap: 24px;">
    <div>
      <h1 class="serif h1">Sicherungen</h1>
      <p class="muted" style="margin: 6px 0 0;">Eine Sicherung, die nie eingespielt wurde, ist kein Backup. Darum wird jede Woche automatisch geprüft.</p>
    </div>
    <button class="btn btn-outline" type="button">Sicherung jetzt ziehen</button>
  </header>

  <div style="display: flex; align-items: flex-end; border-bottom: 1px solid #e2e8f0; margin-top: 20px;">
    <span class="tab">Datenbank</span>
    <span class="tab">Migrationen</span>
    <span class="tab active">Sicherungen</span>
    <span class="tab">AD-Connectoren</span>
    <span class="tab">Zugangswege</span>
  </div>

  <div style="display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; margin-top: 24px;">
    <div class="card" style="padding: 16px 18px;">
      <div class="muted" style="font-size: 13px; font-weight: 500;">Cluster-PITR</div>
      <p style="margin: 8px 0 0; font-weight: 500;">WAL bis vor 40 Sek.</p>
      <p class="muted" style="margin: 2px 0 0; font-size: 13px;">Basebackup heute 01:00</p>
    </div>
    <div class="card" style="padding: 16px 18px;">
      <div class="muted" style="font-size: 13px; font-weight: 500;">Kunden gesichert</div>
      <p style="margin: 8px 0 0; font-weight: 500;">7 von 8</p>
      <p class="muted" style="margin: 2px 0 0; font-size: 13px;">Nesslau in Bereitstellung</p>
    </div>
    <div class="card" style="padding: 16px 18px;">
      <div style="display: flex; align-items: center; justify-content: space-between;">
        <span class="muted" style="font-size: 13px; font-weight: 500;">Pr&uuml;fung offen</span>
        <span class="pill pill-warn">1</span>
      </div>
      <p style="margin: 8px 0 0; font-weight: 500;">Toggenburg Energie AG</p>
      <p class="muted" style="margin: 2px 0 0; font-size: 13px;">seit 9 Tagen nicht gepr&uuml;ft</p>
    </div>
    <div class="card" style="padding: 16px 18px;">
      <div class="muted" style="font-size: 13px; font-weight: 500;">Ablage</div>
      <p style="margin: 8px 0 0; font-weight: 500;">Share &middot; Tages-Backup</p>
      <p class="muted" style="margin: 2px 0 0; font-size: 13px;">9.9 GB, weggesichert 03:40</p>
    </div>
  </div>

  <div class="card" style="margin-top: 16px; overflow: hidden;">
    <table>
      <thead>
        <tr>
          <th style="width: 230px;">Kunde</th>
          <th style="width: 150px;">Letzte Sicherung</th>
          <th style="width: 100px;">Gr&ouml;sse</th>
          <th style="width: 190px;">Aufbewahrung</th>
          <th style="width: 165px;">Zuletzt gepr&uuml;ft</th>
          <th style="width: 145px;">Tages-Backup</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td style="font-weight: 500;">Gemeinde Wattwil</td>
          <td>heute 02:15</td>
          <td class="mono">1.9 GB</td>
          <td>30 Tage auf dem Share</td>
          <td><span class="pill pill-ok">05.09. bestanden</span></td>
          <td class="muted">mitgesichert</td>
          <td>
            <div style="display: flex; justify-content: flex-end; gap: 8px;">
              <button class="btn btn-outline btn-sm" type="button">Wiederherstellen</button>
              <button class="btn btn-outline btn-sm" type="button">Export</button>
            </div>
          </td>
        </tr>
        <tr>
          <td style="font-weight: 500;">Stadt Uzwil</td>
          <td>heute 02:15</td>
          <td class="mono">3.1 GB</td>
          <td>30 Tage auf dem Share</td>
          <td><span class="pill pill-ok">04.09. bestanden</span></td>
          <td class="muted">mitgesichert</td>
          <td>
            <div style="display: flex; justify-content: flex-end; gap: 8px;">
              <button class="btn btn-outline btn-sm" type="button">Wiederherstellen</button>
              <button class="btn btn-outline btn-sm" type="button">Export</button>
            </div>
          </td>
        </tr>
        <tr>
          <td style="font-weight: 500;">Schulgemeinde Flawil</td>
          <td>heute 02:22</td>
          <td class="mono">2.4 GB</td>
          <td>90 Tage auf dem Share</td>
          <td><span class="pill pill-ok">06.09. bestanden</span></td>
          <td class="muted">mitgesichert</td>
          <td>
            <div style="display: flex; justify-content: flex-end; gap: 8px;">
              <button class="btn btn-outline btn-sm" type="button">Wiederherstellen</button>
              <button class="btn btn-outline btn-sm" type="button">Export</button>
            </div>
          </td>
        </tr>
        <tr>
          <td style="font-weight: 500;">Gemeinde Degersheim</td>
          <td>
            <div>heute 02:15</div>
            <div class="muted" style="font-size: 13px;">plus <span class="mono">pre_migration</span></div>
          </td>
          <td class="mono">0.7 GB</td>
          <td>30 Tage auf dem Share</td>
          <td><span class="pill pill-ok">03.09. bestanden</span></td>
          <td class="muted">mitgesichert</td>
          <td>
            <div style="display: flex; justify-content: flex-end; gap: 8px;">
              <button class="btn btn-outline btn-sm" type="button">Wiederherstellen</button>
              <button class="btn btn-outline btn-sm" type="button">Export</button>
            </div>
          </td>
        </tr>
        <tr>
          <td style="font-weight: 500;">Alpstein Treuhand AG</td>
          <td>heute 02:15</td>
          <td class="mono">0.2 GB</td>
          <td>30 Tage auf dem Share</td>
          <td><span class="pill pill-ok">06.09. bestanden</span></td>
          <td class="muted">mitgesichert</td>
          <td>
            <div style="display: flex; justify-content: flex-end; gap: 8px;">
              <button class="btn btn-outline btn-sm" type="button">Wiederherstellen</button>
              <button class="btn btn-outline btn-sm" type="button">Export</button>
            </div>
          </td>
        </tr>
        <tr>
          <td style="font-weight: 500;">Toggenburg Energie AG</td>
          <td>heute 02:15</td>
          <td class="mono">0.4 GB</td>
          <td>30 Tage auf dem Share</td>
          <td><span class="pill pill-warn">seit 9 Tagen offen</span></td>
          <td class="muted">mitgesichert</td>
          <td>
            <div style="display: flex; justify-content: flex-end; gap: 8px;">
              <button class="btn btn-outline btn-sm" type="button">Pr&uuml;fen</button>
              <button class="btn btn-outline btn-sm" type="button">Export</button>
            </div>
          </td>
        </tr>
        <tr>
          <td style="font-weight: 500;">Gemeinde Ebnat-Kappel</td>
          <td>heute 02:31</td>
          <td class="mono">1.2 GB</td>
          <td>30 Tage auf dem Share</td>
          <td><span class="pill pill-ok">05.09. bestanden</span></td>
          <td class="muted">mitgesichert</td>
          <td>
            <div style="display: flex; justify-content: flex-end; gap: 8px;">
              <button class="btn btn-outline btn-sm" type="button">Wiederherstellen</button>
              <button class="btn btn-outline btn-sm" type="button">Export</button>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
  </div>

  <div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; margin-top: 16px;">
    <div class="card" style="padding: 20px 24px;">
      <h2 class="serif h2" style="font-size: 16px;">Zwei Ebenen</h2>
      <p class="muted" style="margin: 12px 0 0; font-size: 13px;">
        <strong style="color: #020817;">Cluster-PITR</strong> bringt die Datenbank auf einen Zeitpunkt
        &mdash; aber f&uuml;r alle Kunden zugleich.
      </p>
      <p class="muted" style="margin: 10px 0 0; font-size: 13px;">
        <strong style="color: #020817;">Dump pro Kunde</strong> holt genau einen Kunden zur&uuml;ck, ohne
        die anderen anzufassen &mdash; daf&uuml;r nur auf den Stand der letzten Nacht.
      </p>
      <p class="muted" style="margin: 10px 0 0; font-size: 13px;">
        Keines ersetzt das andere.
      </p>
    </div>
    <div class="card" style="padding: 20px 24px;">
      <h2 class="serif h2" style="font-size: 16px;">Wiederherstellung daneben</h2>
      <p class="muted" style="margin: 12px 0 0; font-size: 13px;">
        Ein Restore legt <span class="mono">r_&lt;kunde&gt;_&lt;stempel&gt;</span> als neues Schema an
        und l&auml;sst das Produktivschema unber&uuml;hrt. Umgeschaltet wird erst nach Freigabe durch eine
        zweite Person; das alte Schema bleibt Tage stehen.
      </p>
      <p class="muted" style="margin: 10px 0 0; font-size: 13px;">
        Nebeneffekt: eine einzelne Tabelle oder Klasse zur&uuml;ckholen geht damit auch &mdash; man liest
        aus dem Nebenschema, ohne umzuschalten. Das ist der h&auml;ufigere Fall.
      </p>
    </div>
    <div class="card" style="padding: 20px 24px;">
      <h2 class="serif h2" style="font-size: 16px;">Share, aber schreibend</h2>
      <p class="muted" style="margin: 12px 0 0; font-size: 13px;">
        Magister schreibt die verschl&uuml;sselten Dumps auf einen Share; das t&auml;gliche
        Unternehmens-Backup nimmt ihn mit. Das Dienstkonto darf <strong style="color: #020817;">schreiben,
        aber nicht l&ouml;schen</strong> &mdash; das Aufr&auml;umen l&auml;uft als getrennter Job.
      </p>
      <p class="muted" style="margin: 10px 0 0; font-size: 13px;">
        Damit tr&auml;gt die Aufbewahrung des Tages-Backups die Wiederherstellungsgarantie. Diese Zahl
        geh&ouml;rt in Vertrag und AVV &mdash; sie ist auch die L&ouml;schfrist beim Offboarding.
      </p>
    </div>
  </div>
</div>
EOF
