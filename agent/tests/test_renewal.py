"""Zertifikatserneuerung des Agenten (ADR-0014).

Warum das eine eigene Datei mit dieser Sorgfalt bekommt: das Agentenzertifikat
gilt **90 Tage**. Ohne funktionierende Erneuerung hört jeder ausgelieferte
Agent nach drei Monaten auf zu arbeiten, und der Weg zurück ist ein Widerruf
in der Konsole plus ein neues Einmal-Token plus ein Besuch beim Kunden. Ein
Fehler hier fällt nicht in der Abnahme auf, sondern gleichzeitig bei allen
Kunden, drei Monate nach dem Ausliefern.

Der schwierige Teil ist nicht der glückliche Fall. Es ist der **Absturz mitten
im Wechsel**: eine Erneuerung tauscht Schlüssel und Zertifikat, das sind zwei
Dateien, und dazwischen kann der Prozess sterben. Dann liegt ein neuer
Schlüssel neben einem alten Zertifikat, der TLS-Handshake scheitert lokal, und
im Protokoll steht eine OpenSSL-Meldung, die niemand mit „Erneuerung"
verbindet. Genau das prüfen die Tests unten.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from connector_agent.config import AgentConfig, AgentSecrets, save_secrets, write_secret_file
from connector_agent.enrollment import generate_key_and_csr, spki_fingerprint_from_certificate
from connector_agent.renewal import (
    PREV_SUFFIX,
    RENEW_BEFORE_DAYS,
    RenewalError,
    certificate_not_after,
    days_until_expiry,
    is_due,
    pair_matches,
    recover_if_broken,
    renew,
)

ENDPOINT = "https://connect.example.ch:46200"


def _self_signed(key_pem: bytes, *, days: int) -> str:
    """Ein Zertifikat zum Schlüssel, mit gewählter Restlaufzeit.

    Selbstsigniert: geprüft wird hier die Ablauf- und Paar-Logik des Agenten,
    nicht eine Kette. Die Kette prüft die Plattform.
    """
    loaded = serialization.load_pem_private_key(key_pem, password=None)
    # Eingegrenzt, weil load_pem_private_key jeden Schlüsseltyp zurückgeben
    # könnte und der Zertifikatsbauer nur die zum Signieren taugenden nimmt.
    assert isinstance(loaded, ec.EllipticCurvePrivateKey)
    key = loaded
    now = dt.datetime.now(dt.UTC)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "magister-connector-agent")])
    return (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=days))
        .sign(key, hashes.SHA256())
        .public_bytes(serialization.Encoding.PEM)
        .decode("ascii")
    )


@pytest.fixture
def enrolled(tmp_path: Path) -> AgentConfig:
    """Ein angemeldeter Agent mit einem Zertifikat, das in 60 Tagen abläuft."""
    config = AgentConfig(
        endpoint=ENDPOINT, state_dir=tmp_path / "state", ca_bundle=tmp_path / "ca.pem"
    )
    config.state_dir.mkdir(parents=True)
    key_pem, _ = generate_key_and_csr("magister-connector-agent")
    write_secret_file(config.key_path, key_pem.decode("ascii"))
    config.cert_path.write_text(_self_signed(key_pem, days=60), encoding="utf-8")
    save_secrets(
        config,
        AgentSecrets(
            agent_id="00000000-0000-0000-0000-000000000001",
            api_key="api-key-fuer-den-test",
            result_hmac_key="hmac-key-fuer-den-test",
            spki_sha256=spki_fingerprint_from_certificate(
                config.cert_path.read_text(encoding="utf-8")
            ),
        ),
    )
    return config


def _expire_to(config: AgentConfig, days: int) -> None:
    """Das Zertifikat gegen eines mit anderer Restlaufzeit tauschen."""
    key_pem = config.key_path.read_bytes()
    config.cert_path.write_text(_self_signed(key_pem, days=days), encoding="utf-8")


class TestWhenItIsDue:
    def test_a_fresh_certificate_is_not_due(self, enrolled: AgentConfig) -> None:
        assert not is_due(enrolled.cert_path)
        assert days_until_expiry(enrolled.cert_path) > RENEW_BEFORE_DAYS

    def test_it_becomes_due_thirty_days_before_expiry(self, enrolled: AgentConfig) -> None:
        """30 von 90 Tagen ist reichlich, und das ist Absicht.

        Scheitert die Erneuerung, bleibt ein Monat, in dem sie stündlich
        wiederholt wird und ein Mensch eingreifen kann. Bei 7 Tagen wären
        Betriebsferien beim Kunden genug, um den Agenten stillzulegen.
        """
        _expire_to(enrolled, RENEW_BEFORE_DAYS - 1)
        assert is_due(enrolled.cert_path)

    def test_an_expired_certificate_is_due(self, enrolled: AgentConfig) -> None:
        _expire_to(enrolled, -1)
        assert is_due(enrolled.cert_path)
        assert days_until_expiry(enrolled.cert_path) < 0

    def test_an_unreadable_certificate_counts_as_due(self, enrolled: AgentConfig) -> None:
        """Dann ist etwas kaputt, und ein Versuch ist besser als Stillstand."""
        enrolled.cert_path.write_text("kein zertifikat", encoding="utf-8")
        assert is_due(enrolled.cert_path)
        with pytest.raises(RenewalError, match="nicht lesbar"):
            certificate_not_after(enrolled.cert_path)

    def test_the_expiry_is_timezone_aware(self, enrolled: AgentConfig) -> None:
        """Ein zeitzonenloser Vergleich liegt um Stunden falsch — oder wirft."""
        assert certificate_not_after(enrolled.cert_path).tzinfo is not None


class TestThePair:
    def test_a_matching_pair_is_recognised(self, enrolled: AgentConfig) -> None:
        assert pair_matches(enrolled.cert_path, enrolled.key_path)

    def test_a_mismatched_pair_is_recognised(self, enrolled: AgentConfig) -> None:
        """Der Zustand nach einem Absturz mitten im Wechsel."""
        other_key, _ = generate_key_and_csr("x")
        write_secret_file(enrolled.key_path, other_key.decode("ascii"))
        assert not pair_matches(enrolled.cert_path, enrolled.key_path)

    def test_garbage_is_not_a_match_and_does_not_raise(self, enrolled: AgentConfig) -> None:
        enrolled.key_path.write_text("kein schluessel", encoding="utf-8")
        assert not pair_matches(enrolled.cert_path, enrolled.key_path)


class TestRecoveryAfterACrash:
    """Der Fall, um den herum das ganze Modul gebaut ist."""

    def test_a_healthy_pair_is_left_alone(self, enrolled: AgentConfig) -> None:
        before = enrolled.cert_path.read_text(encoding="utf-8")
        assert recover_if_broken(enrolled) is False
        assert enrolled.cert_path.read_text(encoding="utf-8") == before

    def test_a_broken_pair_is_restored_from_the_backup(self, enrolled: AgentConfig) -> None:
        """Genau der Absturz zwischen den beiden Umbenennungen.

        Danach läuft der Agent weiter: das alte Zertifikat gilt noch (erneuert
        wird 30 Tage vor Ablauf), und die Plattform akzeptiert den alten
        Fingerprint im Übergangsfenster.
        """
        good_cert = enrolled.cert_path.read_text(encoding="utf-8")
        good_key = enrolled.key_path.read_text(encoding="utf-8")
        # Sicherungskopie, wie _install sie anlegt.
        enrolled.cert_path.with_name(enrolled.cert_path.name + PREV_SUFFIX).write_text(
            good_cert, encoding="utf-8"
        )
        write_secret_file(
            enrolled.key_path.with_name(enrolled.key_path.name + PREV_SUFFIX), good_key
        )
        # Der Absturz: neuer Schlüssel, altes Zertifikat.
        new_key, _ = generate_key_and_csr("x")
        write_secret_file(enrolled.key_path, new_key.decode("ascii"))
        assert not pair_matches(enrolled.cert_path, enrolled.key_path)

        assert recover_if_broken(enrolled) is True
        assert pair_matches(enrolled.cert_path, enrolled.key_path)
        assert enrolled.key_path.read_text(encoding="utf-8") == good_key

    def test_without_a_usable_backup_it_says_what_to_do(self, enrolled: AgentConfig) -> None:
        """Keine stille Selbstheilung, die es nicht gibt.

        Ohne brauchbare Kopie ist der Agent nicht zu retten — und dann soll
        die Meldung sagen, was zu tun ist, statt einen OpenSSL-Fehler zu
        produzieren, den niemand einordnen kann.
        """
        new_key, _ = generate_key_and_csr("x")
        write_secret_file(enrolled.key_path, new_key.decode("ascii"))
        with pytest.raises(RenewalError, match="widerrufen und neu anmelden"):
            recover_if_broken(enrolled)


class TestRenewOverTheWire:
    def _platform(
        self, *, status: int = 200, mismatch: bool = False
    ) -> tuple[httpx.MockTransport, dict[str, object]]:
        """Eine Plattform, die einen CSR gegen ein Zertifikat tauscht."""
        seen: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["api_key"] = request.headers.get("X-Connector-Api-Key")
            body = json.loads(request.content)
            seen["csr_pem"] = body["csr_pem"]
            if status != 200:
                return httpx.Response(status, json={"detail": "abgelehnt"})
            csr = x509.load_pem_x509_csr(str(body["csr_pem"]).encode("ascii"))
            # Zertifikat zum eingereichten öffentlichen Schlüssel — so wie die
            # echte CA es tut.
            issuer_key = ec.generate_private_key(ec.SECP256R1())
            now = dt.datetime.now(dt.UTC)
            cert = (
                x509.CertificateBuilder()
                .subject_name(csr.subject)
                .issuer_name(
                    x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Connector Intermediate")])
                )
                .public_key(csr.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now)
                .not_valid_after(now + dt.timedelta(days=90))
                .sign(issuer_key, hashes.SHA256())
            )
            pem = cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
            fingerprint = spki_fingerprint_from_certificate(pem)
            return httpx.Response(
                200,
                json={
                    "certificate_pem": pem,
                    "spki_sha256": "0" * 64 if mismatch else fingerprint,
                    "certificate_not_after": (now + dt.timedelta(days=90)).isoformat(),
                    "previous_valid_until": (now + dt.timedelta(days=7)).isoformat(),
                },
            )

        return httpx.MockTransport(handler), seen

    def _secrets(self, config: AgentConfig) -> AgentSecrets:
        raw = json.loads(config.secrets_path.read_text(encoding="utf-8"))
        return AgentSecrets(
            agent_id=raw["agent_id"],
            api_key=raw["api_key"],
            result_hmac_key=raw["result_hmac_key"],
            spki_sha256=raw["spki_sha256"],
        )

    def test_a_renewal_replaces_the_pair_and_keeps_a_backup(self, enrolled: AgentConfig) -> None:
        old_key = enrolled.key_path.read_text(encoding="utf-8")
        old_spki = self._secrets(enrolled).spki_sha256
        transport, seen = self._platform()

        result = renew(
            enrolled, self._secrets(enrolled), agent_version="0.1.0", transport=transport
        )

        assert seen["url"] == f"{ENDPOINT}/connector/renew"
        # Der API-Key beglaubigt die Anfrage — kein Einmal-Token.
        assert seen["api_key"] == "api-key-fuer-den-test"
        assert "token" not in str(seen.get("csr_pem", ""))

        # Neues Paar, und es passt zusammen.
        assert pair_matches(enrolled.cert_path, enrolled.key_path)
        assert enrolled.key_path.read_text(encoding="utf-8") != old_key
        assert result.spki_sha256 != old_spki
        assert self._secrets(enrolled).spki_sha256 == result.spki_sha256
        # Der API-Key bleibt: ein Ding zur Zeit.
        assert self._secrets(enrolled).api_key == "api-key-fuer-den-test"

        # Und das alte Paar liegt als Sicherungskopie daneben.
        prev_cert = enrolled.cert_path.with_name(enrolled.cert_path.name + PREV_SUFFIX)
        prev_key = enrolled.key_path.with_name(enrolled.key_path.name + PREV_SUFFIX)
        assert prev_key.read_text(encoding="utf-8") == old_key
        assert pair_matches(prev_cert, prev_key)

    def test_a_new_key_is_generated_not_reused(self, enrolled: AgentConfig) -> None:
        """Ein Schlüssel, der über Jahre auf einem Kundenserver liegt, wird
        nie gewechselt. Die Erneuerung ist die Gelegenheit."""
        before = enrolled.key_path.read_text(encoding="utf-8")
        transport, seen = self._platform()
        renew(enrolled, self._secrets(enrolled), agent_version="0.1.0", transport=transport)
        csr = x509.load_pem_x509_csr(str(seen["csr_pem"]).encode("ascii"))
        old = serialization.load_pem_private_key(before.encode("ascii"), password=None)
        submitted = csr.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        existing = old.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        assert submitted != existing

    def test_a_certificate_for_the_wrong_key_is_not_stored(self, enrolled: AgentConfig) -> None:
        """Entweder ein Fehler der Plattform oder jemand dazwischen.

        In beiden Fällen bleibt das bestehende Paar unverändert in Kraft.
        """
        before_cert = enrolled.cert_path.read_text(encoding="utf-8")
        before_key = enrolled.key_path.read_text(encoding="utf-8")
        transport, _ = self._platform(mismatch=True)
        with pytest.raises(RenewalError, match="passt nicht zum lokal erzeugten"):
            renew(enrolled, self._secrets(enrolled), agent_version="0.1.0", transport=transport)
        assert enrolled.cert_path.read_text(encoding="utf-8") == before_cert
        assert enrolled.key_path.read_text(encoding="utf-8") == before_key

    def test_a_revoked_agent_gets_a_clear_message(self, enrolled: AgentConfig) -> None:
        """Und die Meldung sagt, dass eine Erneuerung ihn nicht zurückbringt."""
        transport, _ = self._platform(status=401)
        with pytest.raises(RenewalError, match="widerrufen"):
            renew(enrolled, self._secrets(enrolled), agent_version="0.1.0", transport=transport)

    def test_an_unreachable_platform_leaves_everything_in_place(
        self, enrolled: AgentConfig
    ) -> None:
        before = enrolled.key_path.read_text(encoding="utf-8")

        def boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("keine Route zum Host")

        with pytest.raises(RenewalError, match="nicht erreichbar"):
            renew(
                enrolled,
                self._secrets(enrolled),
                agent_version="0.1.0",
                transport=httpx.MockTransport(boom),
            )
        assert enrolled.key_path.read_text(encoding="utf-8") == before
