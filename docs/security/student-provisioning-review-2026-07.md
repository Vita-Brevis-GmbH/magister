# Security review — Student CSV provisioning (2026-07)

Focused security review of the `students` provisioning feature (AD account
creation via CSV import, credential hand-out PDFs, target-OU settings).
Scope: `create_user`, password generator, OU selection, import
classify/apply, WeasyPrint hand-outs, per-kind RBAC, app-settings storage.

## Outcome

**No exploitable findings.** The following surfaces were traced end-to-end and
verified safe:

- **LDAP injection** — the only CSV data in a DN is the CN, escaped via
  `ldap3.utils.dn.escape_rdn`; the target OU comes from admin-only settings,
  never from CSV. All other CSV fields are passed as attribute *values* to
  `conn.add()` (BER-encoded), never concatenated into a DN or search filter.
  objectGUID lookups use `\xx`-escaped bytes / static filters.
- **RBAC & school scope** — the `students` kind requires Admin or SMI, enforced
  on stage/get/apply/cancel/handouts (each re-reads `job.kind` from the DB).
  Non-admins are bounded by `school_scope`; class lookup on apply is
  school-filtered — no cross-school provisioning.
- **Secret exposure** — generated student passwords exist only in the one-time
  apply response and inside the rendered PDFs; never stored, never logged,
  never in the audit payload (allowlist rejects `password`-like keys).
- **Template injection / XSS** — the hand-out Jinja env has autoescape on and
  `StrictUndefined`; no `|safe`, no `dangerouslySetInnerHTML`.

## AD bind-user password (explicit requirement)

Requirement: the bind-user password must not be readable in the DB or in files,
and not be computable.

**Reality & guarantees.** A service *bind* credential is inherently reversible —
Magister must present it in cleartext to AD at bind time, so a one-way hash (as
used for user passwords) is impossible. What is enforced instead:

- **DB:** stored only as `ad_bind_password_enc`, encrypted with pgcrypto
  (`pgp_sym_encrypt`). A database dump **alone** cannot reveal or compute it —
  the encryption key (`MAGISTER_AUDIT_KEY`) is not in the database.
- **API:** never returned; the GUI sees only `ad_bind_password_set: bool`. The
  settings-update audit diff uses the neutral key `rotated_ad_credential`.
- **Logs:** the value is a Pydantic `SecretStr` (no `repr`/log leakage), and the
  logging redaction filter masks `bind_password` / `ldap_password` / `password`.
- **Config:** `MAGISTER_AD_BIND_PASSWORD` is **optional** — set it once via the
  admin UI (→ encrypted DB) and keep it out of `.env`.

**Operational guidance (files):** to avoid a cleartext copy in `.env`, set the
bind password through the admin settings UI rather than the env var, leave
`MAGISTER_AD_BIND_PASSWORD` empty in `.env`, and keep `.env` at mode `600`.

**Preferred hardening (implemented, opt-in):** run the service bind over
**Kerberos/GSSAPI** (`MAGISTER_AD_BIND_MODE=gssapi`) with a keytab from an AD
service account — then there is **no bind password at all** in the DB, `.env`,
or logs; AD owns and rotates the credential. See
[ADR 0007](../adr/0007-ad-gssapi-service-bind.md) and
[runbook `ad-gssapi-bind.md`](../runbooks/ad-gssapi-bind.md).

For instances that stay on `simple`, the app-settings secrets (OIDC client
secret, AD bind password) can now be encrypted with a **dedicated key**
`MAGISTER_SECRETS_KEY` instead of reusing `MAGISTER_AUDIT_KEY` — so compromise
of the audit key does not expose them and vice versa. It falls back to the
audit key when unset (no behaviour change); adopting a distinct key requires
re-entering those two secrets once in the admin UI.

## Dependencies (Dependabot)

The default-branch alerts were dominated by frontend **build/dev/test** tooling
(vitest, vite, ws, form-data, @babel/core, js-yaml, brace-expansion) — none of
which ship in the production bundle (nginx serves the static build). Bumped
`vite`→6.4.3 and `vitest`→3.2.6 and refreshed the transitive tree; `pnpm audit`
is now clean (0/0/0/0). Backend runtime dependencies were already current.
