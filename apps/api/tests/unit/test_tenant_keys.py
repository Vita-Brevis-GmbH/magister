"""Kundenschlüssel je Mandant (ADR-0016 D8).

Der Kern ist eine einzige Frage: **darf ein fehlender mandantenspezifischer
Schlüssel auf den gemeinsamen zurückfallen?** Bei einem Mandanten ja, bei mehr
als einem nein — und das Nein ist der Punkt. Ein Rückfall wäre die Variante,
die niemandem auffällt: alles läuft weiter, und zwei Zusagen aus ADR-0016 sind
still gebrochen (Crypto-Shredding beim Offboarding, zweite
Verschlüsselungsschicht im Backup).
"""

from __future__ import annotations

import pytest

from magister_api.tenancy.keys import (
    ENV_AUDIT_KEY,
    ENV_AUDIT_KEY_ID,
    ENV_SECRETS_KEY,
    MIN_KEY_LENGTH,
    TenantKeyError,
    TenantKeys,
    env_ref,
    resolve_tenant_keys,
)

GOOD = "x" * MIN_KEY_LENGTH
OTHER = "y" * MIN_KEY_LENGTH


def _resolve(slug: str, env: dict[str, str], *, single: bool, fallback: str = "") -> TenantKeys:
    return resolve_tenant_keys(
        slug,
        fallback_audit_key=fallback,
        fallback_audit_key_id="v1",
        fallback_secrets_key=fallback,
        single_tenant=single,
        env=env,
    )


class TestPerTenantKey:
    def test_each_tenant_gets_its_own_key(self) -> None:
        env = {
            ENV_AUDIT_KEY.format(ref="ALPHA"): GOOD,
            ENV_AUDIT_KEY.format(ref="BETA"): OTHER,
        }
        alpha = _resolve("alpha", env, single=False)
        beta = _resolve("beta", env, single=False)
        assert alpha.audit_key != beta.audit_key
        # Und die Ids auch: die Sicherung vermerkt nur die Id, und wer
        # wiederherstellt, sucht damit den passenden Schlüssel.
        assert alpha.audit_key_id != beta.audit_key_id

    def test_a_missing_key_is_refused_with_more_than_one_tenant(self) -> None:
        """Kein stiller Rückfall auf den gemeinsamen Schlüssel.

        Mit einem gemeinsamen Schlüssel würde das Offboarding eines Kunden die
        Audit-Inhalte **aller** Kunden vernichten, und ein gestohlenes Backup
        gäbe die Inhalte aller Kunden her.
        """
        with pytest.raises(TenantKeyError, match="eigenen Kundenschlüssel"):
            _resolve("alpha", {}, single=False, fallback=GOOD)

    def test_the_shared_key_still_serves_a_single_tenant(self) -> None:
        """Eine bestehende Installation läuft nach dem Update ohne neue Konfiguration.

        Bei genau einem Mandanten gibt es nichts zu trennen — dort ist der
        Rückfall richtig und nicht bloss bequem.
        """
        keys = _resolve("default", {}, single=True, fallback=GOOD)
        assert keys.audit_key == GOOD
        assert keys.audit_key_id == "v1"

    def test_without_any_key_it_refuses_even_single_tenant(self) -> None:
        with pytest.raises(TenantKeyError, match="Ohne Kundenschlüssel"):
            _resolve("default", {}, single=True, fallback="")

    def test_a_too_short_new_key_is_refused(self) -> None:
        env = {ENV_AUDIT_KEY.format(ref="ALPHA"): "kurz"}
        with pytest.raises(TenantKeyError, match="kürzer als"):
            _resolve("alpha", env, single=False)

    def test_a_short_existing_shared_key_is_not_refused(self) -> None:
        """Ein Update darf eine laufende Installation nicht abschalten.

        Mit ``MAGISTER_AUDIT_KEY`` sind bestehende Audit-Payloads und
        gespeicherte Passwörter verschlüsselt. Ihn zu wechseln ist eine
        Umschlüsselung aller Zeilen, keine Konfigurationsänderung — eine
        Ablehnung hiesse also nicht „bitte länger", sondern „diese
        Installation antwortet ab dem Update mit 503". Also Warnung.
        """
        keys = _resolve("default", {}, single=True, fallback="zu-kurz-aber-im-bestand")
        assert keys.audit_key == "zu-kurz-aber-im-bestand"

    def test_the_secrets_key_falls_back_to_the_audit_key(self) -> None:
        env = {ENV_AUDIT_KEY.format(ref="ALPHA"): GOOD}
        keys = _resolve("alpha", env, single=False)
        assert keys.secrets_key == GOOD

    def test_a_separate_secrets_key_wins(self) -> None:
        env = {
            ENV_AUDIT_KEY.format(ref="ALPHA"): GOOD,
            ENV_SECRETS_KEY.format(ref="ALPHA"): OTHER,
        }
        assert _resolve("alpha", env, single=False).secrets_key == OTHER

    def test_a_configured_key_id_wins(self) -> None:
        env = {
            ENV_AUDIT_KEY.format(ref="ALPHA"): GOOD,
            ENV_AUDIT_KEY_ID.format(ref="ALPHA"): "alpha-2026",
        }
        assert _resolve("alpha", env, single=False).audit_key_id == "alpha-2026"

    def test_the_key_never_appears_in_a_repr(self) -> None:
        """Ein Traceback zeigt jeden Frame — auch den mit diesem Objekt darin."""
        keys = TenantKeys(audit_key=GOOD, audit_key_id="alpha-v1", secrets_key=OTHER)
        text = repr(keys)
        assert GOOD not in text
        assert OTHER not in text
        assert "alpha-v1" in text


class TestEnvRef:
    @pytest.mark.parametrize(
        ("slug", "expected"),
        [("alpha", "ALPHA"), ("muster_stadt", "MUSTER_STADT"), ("t3", "T3")],
    )
    def test_the_ref_follows_the_dsn_convention(self, slug: str, expected: str) -> None:
        assert env_ref(slug) == expected

    def test_a_slug_that_cannot_be_a_variable_name_is_refused(self) -> None:
        with pytest.raises(TenantKeyError, match="Verweis"):
            env_ref("alpha; rm -rf /")
