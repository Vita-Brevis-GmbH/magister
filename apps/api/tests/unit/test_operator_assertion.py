"""Den Einlöseschein prüfen (ADR-0019 D2, D3).

Reine Logik, ohne Datenbank — und der wichtigere Teil der Prüfung: hier stehen
die Fälle, in denen ein Zugriff **nicht** stattfinden darf. Die Signatur ist
davon der einfachste; die interessanten sind der fremde Mandant, die
verlängerte Gültigkeit und das Dokument, das seinen eigenen Algorithmus
mitbringt.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa

from magister_api.auth.operator_assertion import (
    ASSERTION_PREFIX,
    MAX_LIFETIME,
    OperatorAssertionError,
    parse_and_verify,
)

SLUG = "musterstadt"


def _pem(key: ed25519.Ed25519PrivateKey) -> str:
    return (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _make(
    key: ed25519.Ed25519PrivateKey,
    *,
    now: datetime | None = None,
    ttl: timedelta = timedelta(seconds=60),
    **over: Any,
) -> str:
    moment = now or datetime.now(UTC)
    payload: dict[str, Any] = {
        "jti": str(uuid.uuid4()),
        "tenant": SLUG,
        "operator": "matthias.hadorn@vitabrevis.ch",
        "reason": "Ticket 4711: Klassenlehrerin sieht die Klasse 4a nicht.",
        "ticket": "4711",
        "iat": int(moment.timestamp()),
        "exp": int((moment + ttl).timestamp()),
    }
    payload.update(over)
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return f"{ASSERTION_PREFIX}.{_b64(body)}.{_b64(key.sign(body))}"


@pytest.fixture
def key() -> ed25519.Ed25519PrivateKey:
    return ed25519.Ed25519PrivateKey.generate()


class TestAValidAssertion:
    def test_it_comes_through_with_its_content(self, key: ed25519.Ed25519PrivateKey) -> None:
        assertion = parse_and_verify(_make(key), _pem(key), tenant_slug=SLUG)
        assert assertion.operator == "matthias.hadorn@vitabrevis.ch"
        assert assertion.ticket == "4711"
        assert "4711" in assertion.reason

    def test_an_empty_ticket_becomes_none(self, key: ed25519.Ed25519PrivateKey) -> None:
        # Ein leerer Text und „kein Ticket" sind dasselbe; zwei Darstellungen
        # desselben Zustands wären eine Falle für jede Anzeige.
        assert parse_and_verify(_make(key, ticket=""), _pem(key), tenant_slug=SLUG).ticket is None


class TestTheSignature:
    def test_another_key_is_refused(self, key: ed25519.Ed25519PrivateKey) -> None:
        other = ed25519.Ed25519PrivateKey.generate()
        with pytest.raises(OperatorAssertionError) as exc:
            parse_and_verify(_make(other), _pem(key), tenant_slug=SLUG)
        assert "Signatur" in str(exc.value)

    def test_a_changed_body_is_refused(self, key: ed25519.Ed25519PrivateKey) -> None:
        """Der Fall, um den es bei einer Signatur geht.

        Jemand fängt einen gültigen Schein ab und setzt seinen eigenen Grund
        ein — oder einen anderen Mandanten.
        """
        prefix, body, signature = _make(key).split(".")
        payload = json.loads(base64.urlsafe_b64decode(body + "=="))
        payload["reason"] = "harmlos"
        tampered = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
        with pytest.raises(OperatorAssertionError):
            parse_and_verify(f"{prefix}.{tampered}.{signature}", _pem(key), tenant_slug=SLUG)

    def test_a_document_with_its_own_algorithm_gains_nothing(
        self, key: ed25519.Ed25519PrivateKey
    ) -> None:
        """`alg: none` ist hier bedeutungslos, und das ist der Entscheid D2.

        Das Verfahren steht im Präfix und im Code. Ein Feld `alg` im Dokument
        wird nicht gelesen — es kann die Prüfung also nicht abschalten.
        """
        body = json.dumps({"alg": "none", "jti": "x"}, separators=(",", ":")).encode()
        with pytest.raises(OperatorAssertionError):
            parse_and_verify(
                f"{ASSERTION_PREFIX}.{_b64(body)}.{_b64(b'nicht-signiert')}",
                _pem(key),
                tenant_slug=SLUG,
            )

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "nur-ein-teil",
            "zwei.teile",
            "vier.teile.sind.zuviel",
            "mgop2.abc.def",
        ],
    )
    def test_a_malformed_assertion_is_refused(
        self, raw: str, key: ed25519.Ed25519PrivateKey
    ) -> None:
        with pytest.raises(OperatorAssertionError):
            parse_and_verify(raw, _pem(key), tenant_slug=SLUG)


class TestTheTenantBinding:
    def test_an_assertion_for_another_tenant_is_refused(
        self, key: ed25519.Ed25519PrivateKey
    ) -> None:
        """Der Fall, der ohne diese Prüfung offen wäre.

        Die Signatur ist gültig — sie sagt nur nichts darüber, **wo** der
        Schein gilt. Ohne den Vergleich mit dem Mandanten der Anfrage wäre ein
        Zugriff auf Kunde A bei Kunde B einlösbar.
        """
        with pytest.raises(OperatorAssertionError) as exc:
            parse_and_verify(_make(key), _pem(key), tenant_slug="anderestadt")
        assert "anderen Kunden" in str(exc.value)


class TestTime:
    def test_an_expired_assertion_is_refused(self, key: ed25519.Ed25519PrivateKey) -> None:
        past = datetime.now(UTC) - timedelta(minutes=5)
        with pytest.raises(OperatorAssertionError) as exc:
            parse_and_verify(_make(key, now=past), _pem(key), tenant_slug=SLUG)
        assert "abgelaufen" in str(exc.value)

    def test_an_assertion_from_the_future_is_refused(self, key: ed25519.Ed25519PrivateKey) -> None:
        future = datetime.now(UTC) + timedelta(minutes=10)
        with pytest.raises(OperatorAssertionError) as exc:
            parse_and_verify(_make(key, now=future), _pem(key), tenant_slug=SLUG)
        assert "Zukunft" in str(exc.value)

    def test_a_small_clock_skew_is_tolerated(self, key: ed25519.Ed25519PrivateKey) -> None:
        # Zwei Maschinen, zwei Uhren. Zehn Sekunden Vorlauf dürfen keinen
        # Support-Fall blockieren.
        slightly_ahead = datetime.now(UTC) + timedelta(seconds=10)
        parse_and_verify(_make(key, now=slightly_ahead), _pem(key), tenant_slug=SLUG)

    def test_a_stretched_lifetime_is_refused(self, key: ed25519.Ed25519PrivateKey) -> None:
        """Die Datenebene setzt ihre eigene Höchstdauer.

        Der Entscheid dahinter: ein Signierschlüssel, der abhanden kommt, soll
        kein Dauerticket ausstellen können. Ohne diese Prüfung wäre ein Schein
        mit `exp = iat + 1 Jahr` gültig — die Signatur stimmt ja.
        """
        with pytest.raises(OperatorAssertionError) as exc:
            parse_and_verify(
                _make(key, ttl=MAX_LIFETIME + timedelta(seconds=1)), _pem(key), tenant_slug=SLUG
            )
        assert "höchstens" in str(exc.value)


class TestTheKey:
    def test_without_a_key_there_is_no_access(self, key: ed25519.Ed25519PrivateKey) -> None:
        with pytest.raises(OperatorAssertionError) as exc:
            parse_and_verify(_make(key), "", tenant_slug=SLUG)
        assert "MAGISTER_OPERATOR_PUBLIC_KEY" in str(exc.value)

    def test_an_rsa_key_is_refused(self, key: ed25519.Ed25519PrivateKey) -> None:
        rsa_pem = (
            rsa.generate_private_key(public_exponent=65537, key_size=2048)
            .public_key()
            .public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode("ascii")
        )
        with pytest.raises(OperatorAssertionError) as exc:
            parse_and_verify(_make(key), rsa_pem, tenant_slug=SLUG)
        assert "Ed25519" in str(exc.value)

    def test_nonsense_instead_of_a_key_is_refused(self, key: ed25519.Ed25519PrivateKey) -> None:
        with pytest.raises(OperatorAssertionError):
            parse_and_verify(_make(key), "kein PEM", tenant_slug=SLUG)


class TestMissingFields:
    @pytest.mark.parametrize("field", ["jti", "tenant", "operator", "reason", "iat", "exp"])
    def test_a_missing_field_is_named(self, field: str, key: ed25519.Ed25519PrivateKey) -> None:
        moment = datetime.now(UTC)
        payload: dict[str, Any] = {
            "jti": str(uuid.uuid4()),
            "tenant": SLUG,
            "operator": "ops@vitabrevis.ch",
            "reason": "Grund mit genug Zeichen",
            "iat": int(moment.timestamp()),
            "exp": int((moment + timedelta(seconds=60)).timestamp()),
        }
        del payload[field]
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        raw = f"{ASSERTION_PREFIX}.{_b64(body)}.{_b64(key.sign(body))}"
        with pytest.raises(OperatorAssertionError) as exc:
            parse_and_verify(raw, _pem(key), tenant_slug=SLUG)
        assert field in str(exc.value) or "Zeitstempel" in str(exc.value)

    def test_an_empty_reason_is_refused(self, key: ed25519.Ed25519PrivateKey) -> None:
        # Der Grund ist der Zweck des ganzen Vorgangs: ohne ihn steht im
        # Protokoll des Kunden „jemand war da".
        with pytest.raises(OperatorAssertionError):
            parse_and_verify(_make(key, reason="   "), _pem(key), tenant_slug=SLUG)


def test_the_prefix_matches_the_console() -> None:
    """Beide Seiten benutzen denselben Präfix — geprüft, nicht behauptet.

    Die Konsole hängt nicht von `magister_api` ab und umgekehrt; gelesen wird
    deshalb die Datei, nicht importiert.
    """
    import ast
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[4]
        / "cockpit"
        / "api"
        / "cockpit_api"
        / "services"
        / "operator_access.py"
    )
    if not path.exists():
        pytest.skip("Konsole liegt in dieser Umgebung nicht daneben")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(getattr(t, "id", "") == "ASSERTION_PREFIX" for t in node.targets):
            assert ast.literal_eval(node.value) == ASSERTION_PREFIX
            return
    pytest.fail("ASSERTION_PREFIX in der Konsole nicht gefunden")
