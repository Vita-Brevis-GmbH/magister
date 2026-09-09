"""Der Connector-Kanal von der Anmeldung bis zum Ergebnis (ADR-0014).

Die Abnahmekriterien, soweit sie ohne echten Agenten prüfbar sind:

- Ein Client-Zertifikat von Kunde A wird auf dem Kanal von Kunde B abgewiesen.
- Ein Auftrag mit einer Methode ausserhalb der Allowlist wird schon
  plattformseitig verweigert.
- Das Anmelde-Token ist genau einmal einlösbar.
- Ein widerrufener Agent kommt bei der nächsten Anfrage nicht mehr durch.
- Nutzlasten mit Passwörtern sind nach Abschluss gelöscht.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient

from cockpit_api.config import settings
from cockpit_api.management_guard import MARKER_HEADER
from cockpit_api.services.connector import sign_result
from cockpit_api.services.connector_queue import ALLOWED_METHODS

pytestmark = pytest.mark.usefixtures("cockpit_schema")


@pytest.fixture
def connector_ca(tmp_path: Path) -> Iterator[Path]:
    """Ein Intermediate, wie die CA-Zeremonie es ausstellen wird."""
    key = ec.generate_private_key(ec.SECP384R1())
    name = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "CH"),
            x509.NameAttribute(NameOID.COMMON_NAME, "Magister Connector Issuing CA"),
        ]
    )
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(key, hashes.SHA384())
    )
    (tmp_path / "ca.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "ca-key.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    previous = (settings.connector_ca_cert, settings.connector_ca_key)
    settings.connector_ca_cert = str(tmp_path / "ca.pem")
    settings.connector_ca_key = str(tmp_path / "ca-key.pem")
    yield tmp_path
    (settings.connector_ca_cert, settings.connector_ca_key) = previous


def _csr() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "agent")]))
        .sign(key, hashes.SHA256())
    )
    return csr.public_bytes(serialization.Encoding.PEM).decode("ascii")


def _tenant(client: TestClient, slug: str) -> str:
    """Kunden anlegen und aktiv setzen — die Bereitstellung ist hier nicht der Punkt."""
    created = client.post(
        "/api/tenants",
        json={"slug": slug, "name": slug, "hostname": f"{slug}.magister.test"},
    )
    assert created.status_code in (201, 202), created.text
    tenant_id: str = created.json()["tenant"]["id"]
    return tenant_id


def _set_status(tenant_id: str, status: str) -> None:
    """Kundenstatus direkt setzen.

    Der Bereitstellungsschritt ``migrate`` braucht Alembic; für den Connector
    ist nur der Status relevant, und er soll nicht davon abhängen, ob die
    Testumgebung das Alembic-Verzeichnis kennt.
    """
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    async def flip() -> None:
        engine = create_async_engine(_cockpit_url(), poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text("UPDATE tenants SET status = :s WHERE id = :i"),
                    {"s": status, "i": tenant_id},
                )
        finally:
            await engine.dispose()

    asyncio.run(flip())


def _activate(client: TestClient, tenant_id: str) -> None:
    _set_status(tenant_id, "active")


def _cockpit_url() -> str:
    import os

    return os.environ["COCKPIT_TEST_DATABASE_URL"]


def _enroll(
    client: TestClient, tenant_id: str, agent_headers: dict[str, str], *, name: str = "dc01"
) -> dict[str, Any]:
    token = client.post(f"/api/tenants/{tenant_id}/enrollments", json={"agent_name": name})
    assert token.status_code == 201, token.text
    resp = client.post(
        "/connector/enroll",
        headers=agent_headers,
        json={"token": token.json()["token"], "csr_pem": _csr(), "agent_version": "0.1.0"},
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    body["enrollment_token"] = token.json()["token"]
    return body


def _der_b64(certificate_pem: str) -> str:
    """PEM in base64-DER, wie Caddy es im Header überträgt.

    Genau die Form, die der Platzhalter
    ``{http.request.tls.client.certificate_der_base64}`` liefert — gegen einen
    laufenden Caddy nachgemessen. PEM geht nicht: Gos ``net/http`` weist einen
    Header-Wert mit Zeilenumbruch ab.
    """
    cert = x509.load_pem_x509_certificate(certificate_pem.encode())
    return base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode("ascii")


def _auth(agent: dict[str, Any], agent_headers: dict[str, str]) -> dict[str, str]:
    """Header eines authentisierten Agenten."""
    return {
        **agent_headers,
        settings.connector_client_cert_header: _der_b64(agent["certificate_pem"]),
        "X-Connector-Api-Key": agent["api_key"],
    }


class TestAllowlistParity:
    def test_the_allowlist_matches_the_data_plane(self) -> None:
        """Konsole und Datenebene müssen dieselbe Methodenmenge kennen.

        Die Konsole kann ``magister_api`` nicht importieren (eigene Anwendung,
        eigene Abhängigkeiten), deshalb ist die Menge wörtlich wiederholt. Eine
        Änderung auf einer Seite muss hier auffallen — sonst nimmt die Konsole
        einen Auftrag an, den der Agent dann ablehnt, oder umgekehrt.
        """
        source = (
            Path(__file__).resolve().parents[3] / "apps" / "api" / "magister_api" / "ad" / "rpc.py"
        )
        text = source.read_text(encoding="utf-8")
        block = text.split("ALLOWED_METHODS: frozenset[str] = frozenset(", 1)[1].split(")", 1)[0]
        data_plane = {line.strip().strip('",') for line in block.splitlines() if '"' in line}
        assert data_plane == set(ALLOWED_METHODS), (
            "Allowlist von Konsole und Datenebene weichen ab: "
            f"nur Datenebene {data_plane - set(ALLOWED_METHODS)}, "
            f"nur Konsole {set(ALLOWED_METHODS) - data_plane}"
        )


class TestListenerSeparation:
    def test_the_management_marker_does_not_open_the_connector(self, db_client: TestClient) -> None:
        """Sonst wäre die Trennung der beiden Listener nur Dekoration."""
        resp = db_client.post(
            "/connector/enroll",
            headers={MARKER_HEADER: "test-management-marker"},
            json={"token": "x" * 32, "csr_pem": "x" * 64},
        )
        assert resp.status_code == 404

    def test_the_connector_marker_does_not_open_the_console(
        self, db_client: TestClient, agent_headers: dict[str, str]
    ) -> None:
        resp = db_client.get("/api/tenants", headers={**agent_headers, MARKER_HEADER: ""})
        assert resp.status_code == 404

    def test_the_connector_path_needs_its_own_marker(self, db_client: TestClient) -> None:
        resp = db_client.post(
            "/connector/enroll", headers={}, json={"token": "x" * 32, "csr_pem": "x" * 64}
        )
        assert resp.status_code == 404


@pytest.mark.usefixtures("connector_ca")
class TestEnrollmentNeedsNoCertificate:
    """Der einzige Endpunkt des Kanals ohne Client-Zertifikat.

    Ein neuer Agent hat noch keines — es zu bekommen ist der Zweck des
    Aufrufs. Deshalb steht der Connector-Listener auf ``verify_if_given``
    und nicht auf ``require_and_verify``: sonst scheitert der Handshake, bevor
    der Pfad überhaupt bekannt ist, und eine Anmeldung wäre unmöglich.
    Nachgemessen gegen einen laufenden Caddy — der Agent bekam
    ``tlsv13 alert certificate required`` beim allerersten Aufruf.

    Die Kehrseite muss dann hier gelten: **alles andere** verlangt ein
    Zertifikat, und diese Prüfung liegt in der Anwendung, wo der Pfad bekannt
    ist.
    """

    def test_enrollment_works_without_a_client_certificate(
        self, db_client: TestClient, agent_headers: dict[str, str]
    ) -> None:
        tenant_id = _tenant(db_client, "ohnecert2")
        _set_status(tenant_id, "active")
        token = db_client.post(
            f"/api/tenants/{tenant_id}/enrollments", json={"agent_name": "dc01"}
        ).json()["token"]
        # Kein settings.connector_client_cert_header, kein API-Key.
        resp = db_client.post(
            "/connector/enroll",
            headers=agent_headers,
            json={"token": token, "csr_pem": _csr()},
        )
        assert resp.status_code == 201, resp.text

    def test_every_other_path_still_demands_a_certificate(
        self, db_client: TestClient, agent_headers: dict[str, str]
    ) -> None:
        tenant_id = _tenant(db_client, "brauchtcert")
        _set_status(tenant_id, "active")
        agent = _enroll(db_client, tenant_id, agent_headers)
        # Nur der API-Key, kein Zertifikat: das ist der Fall, den
        # verify_if_given auf TLS-Ebene durchlässt und den die Anwendung
        # abfangen muss.
        headers = {**agent_headers, "X-Connector-Api-Key": agent["api_key"]}
        assert db_client.get("/connector/jobs?wait=false", headers=headers).status_code == 401
        assert (
            db_client.post(
                f"/connector/jobs/{agent['agent_id']}/result",
                headers=headers,
                json={"ok": True, "result": None, "error": None, "signature": "0" * 64},
            ).status_code
            == 401
        )


@pytest.mark.usefixtures("connector_ca")
class TestEnrollment:
    def test_a_token_is_redeemable_exactly_once(
        self, db_client: TestClient, agent_headers: dict[str, str]
    ) -> None:
        tenant_id = _tenant(db_client, "enr")
        _activate(db_client, tenant_id)
        agent = _enroll(db_client, tenant_id, agent_headers)
        assert agent["api_key"] and agent["result_hmac_key"]

        again = db_client.post(
            "/connector/enroll",
            headers=agent_headers,
            json={"token": agent["enrollment_token"], "csr_pem": _csr()},
        )
        # 401 und nicht 409: ein verbrauchtes und ein erfundenes Token sind für
        # den Anrufer dasselbe.
        assert again.status_code == 401

    def test_the_package_holds_no_secret_beyond_the_token(self, db_client: TestClient) -> None:
        tenant_id = _tenant(db_client, "paket")
        _activate(db_client, tenant_id)
        resp = db_client.post(f"/api/tenants/{tenant_id}/enrollments", json={"agent_name": "dc01"})
        body = resp.json()
        assert set(body) == {"id", "agent_name", "expires_at", "token"}
        # Genau 24 Stunden, weil das Token im Paket reist.
        expires = dt.datetime.fromisoformat(body["expires_at"])
        hours = (expires - dt.datetime.now(dt.UTC)).total_seconds() / 3600
        assert 23 < hours <= 24

    def test_an_inactive_tenant_gets_no_token(self, db_client: TestClient) -> None:
        """Ein Kunde, der nicht bedient wird, bekommt auch keinen Agenten.

        Der Status wird ausdrücklich gesetzt und nicht aus einem scheiternden
        Bereitstellungs-Auftrag abgeleitet: ob der scheitert, hängt daran, ob
        Alembic konfiguriert ist — das wäre ein Test, der von der Umgebung
        abhängt statt von der Regel.
        """
        tenant_id = _tenant(db_client, "inaktiv")
        _set_status(tenant_id, "provisioning")
        resp = db_client.post(f"/api/tenants/{tenant_id}/enrollments", json={"agent_name": "dc01"})
        assert resp.status_code == 409

    def test_the_console_stores_only_a_hash_of_the_api_key(
        self, db_client: TestClient, agent_headers: dict[str, str]
    ) -> None:
        tenant_id = _tenant(db_client, "hashonly")
        _activate(db_client, tenant_id)
        agent = _enroll(db_client, tenant_id, agent_headers)
        listing = db_client.get(f"/api/tenants/{tenant_id}/agents")
        assert listing.status_code == 200
        assert agent["api_key"] not in listing.text
        row = listing.json()[0]
        assert "api_key_hash" not in row and "result_hmac_key" not in row
        assert row["spki_sha256"] == agent["spki_sha256"]


@pytest.mark.usefixtures("connector_ca")
class TestChannelIsolation:
    def test_an_agent_of_one_tenant_cannot_use_another_tenants_channel(
        self, db_client: TestClient, agent_headers: dict[str, str]
    ) -> None:
        """Das Abnahmekriterium: Zertifikat von A, API-Key von B.

        Beide Faktoren müssen auf dieselbe Agent-Zeile zeigen. Sonst käme der
        Agent von Kunde A auf den Kanal von Kunde B — genau das, was der
        Fingerprint-Abgleich neben der Kettenprüfung verhindert.
        """
        a = _tenant(db_client, "kunde_a")
        b = _tenant(db_client, "kunde_b")
        _activate(db_client, a)
        _activate(db_client, b)
        agent_a = _enroll(db_client, a, agent_headers, name="dc-a")
        agent_b = _enroll(db_client, b, agent_headers, name="dc-b")

        mixed = {
            **agent_headers,
            settings.connector_client_cert_header: agent_a["certificate_pem"].replace("\n", "\t"),
            "X-Connector-Api-Key": agent_b["api_key"],
        }
        assert db_client.get("/connector/jobs?wait=false", headers=mixed).status_code == 401

    def test_an_agent_only_sees_its_own_tenants_jobs(
        self, db_client: TestClient, agent_headers: dict[str, str]
    ) -> None:
        a = _tenant(db_client, "sieht_a")
        b = _tenant(db_client, "sieht_b")
        _activate(db_client, a)
        _activate(db_client, b)
        agent_a = _enroll(db_client, a, agent_headers, name="dc-a")

        db_client.post(f"/api/tenants/{b}/jobs", json={"method": "find_user_dn"})
        jobs = db_client.get("/connector/jobs?wait=false", headers=_auth(agent_a, agent_headers))
        assert jobs.status_code == 200
        assert jobs.json() == [], "der Auftrag von Kunde B darf hier nicht auftauchen"

    def test_a_revoked_agent_is_refused_on_the_next_request(
        self, db_client: TestClient, agent_headers: dict[str, str]
    ) -> None:
        """Kein CRL-Vertrieb: der Widerruf ist ein Flag und wirkt sofort."""
        tenant_id = _tenant(db_client, "widerruf")
        _activate(db_client, tenant_id)
        agent = _enroll(db_client, tenant_id, agent_headers)
        headers = _auth(agent, agent_headers)
        assert db_client.get("/connector/jobs?wait=false", headers=headers).status_code == 200

        revoked = db_client.post(
            f"/api/tenants/{tenant_id}/agents/{agent['agent_id']}/revoke",
            json={"reason": "Server ausgemustert"},
        )
        assert revoked.status_code == 200
        assert db_client.get("/connector/jobs?wait=false", headers=headers).status_code == 401

    def test_a_suspended_tenant_stops_its_agent(
        self, db_client: TestClient, agent_headers: dict[str, str]
    ) -> None:
        # Ein gesperrter Kunde soll auch über den Connector nichts bewegen.
        tenant_id = _tenant(db_client, "gesperrt")
        _activate(db_client, tenant_id)
        agent = _enroll(db_client, tenant_id, agent_headers)
        headers = _auth(agent, agent_headers)
        assert db_client.get("/connector/jobs?wait=false", headers=headers).status_code == 200

        db_client.post(f"/api/tenants/{tenant_id}/suspend", json={"reason": "Test"})
        assert db_client.get("/connector/jobs?wait=false", headers=headers).status_code == 401

    def test_a_wrong_api_key_is_refused(
        self, db_client: TestClient, agent_headers: dict[str, str]
    ) -> None:
        tenant_id = _tenant(db_client, "falscherkey")
        _activate(db_client, tenant_id)
        agent = _enroll(db_client, tenant_id, agent_headers)
        headers = {**_auth(agent, agent_headers), "X-Connector-Api-Key": "geraten"}
        assert db_client.get("/connector/jobs?wait=false", headers=headers).status_code == 401

    def test_a_missing_certificate_is_refused(
        self, db_client: TestClient, agent_headers: dict[str, str]
    ) -> None:
        tenant_id = _tenant(db_client, "ohnecert")
        _activate(db_client, tenant_id)
        agent = _enroll(db_client, tenant_id, agent_headers)
        headers = {**agent_headers, "X-Connector-Api-Key": agent["api_key"]}
        assert db_client.get("/connector/jobs?wait=false", headers=headers).status_code == 401


@pytest.mark.usefixtures("connector_ca")
class TestJobFlow:
    def test_a_method_outside_the_allowlist_is_refused(self, db_client: TestClient) -> None:
        """Auch ein Global Admin bekommt kein freies LDAP."""
        tenant_id = _tenant(db_client, "allow")
        _activate(db_client, tenant_id)
        for method in ("ldap_search", "run_powershell", "authenticate", ""):
            resp = db_client.post(f"/api/tenants/{tenant_id}/jobs", json={"method": method})
            assert resp.status_code in (400, 422), f"{method!r} wurde angenommen"

    def test_a_job_runs_from_enqueue_to_result(
        self, db_client: TestClient, agent_headers: dict[str, str]
    ) -> None:
        tenant_id = _tenant(db_client, "lauf")
        _activate(db_client, tenant_id)
        agent = _enroll(db_client, tenant_id, agent_headers)
        headers = _auth(agent, agent_headers)

        created = db_client.post(
            f"/api/tenants/{tenant_id}/jobs",
            json={"method": "find_user_dn", "payload": {"upn": "a@b.ch"}},
        )
        assert created.status_code == 201, created.text
        job_id = created.json()["id"]

        claimed = db_client.get("/connector/jobs?wait=false", headers=headers)
        assert [j["id"] for j in claimed.json()] == [job_id]
        assert claimed.json()[0]["payload"] == {"upn": "a@b.ch"}

        # Zweiter Poll: derselbe Auftrag darf nicht doppelt kommen.
        assert db_client.get("/connector/jobs?wait=false", headers=headers).json() == []

        body = {"ok": True, "result": {"dn": "CN=a"}, "error": None}
        raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        done = db_client.post(
            f"/connector/jobs/{job_id}/result",
            headers=headers,
            json={**body, "signature": sign_result(agent["result_hmac_key"], job_id, raw)},
        )
        assert done.status_code == 200, done.text
        assert done.json()["state"] == "done"

    def test_a_non_object_result_is_accepted(
        self, db_client: TestClient, agent_headers: dict[str, str]
    ) -> None:
        """``find_user_dn`` liefert einen String, kein Objekt.

        Das Schema forderte ursprünglich ein Objekt, und damit wurde **jedes**
        erfolgreiche Ergebnis mit 422 abgewiesen. Aufgefallen erst mit einem
        echten Agenten, weil die Tests hier dict-Ergebnisse benutzten — der
        Grund, warum dieser Test jetzt die Formen durchgeht, die die Allowlist
        wirklich liefert.
        """
        tenant_id = _tenant(db_client, "formen")
        _set_status(tenant_id, "active")
        agent = _enroll(db_client, tenant_id, agent_headers)
        headers = _auth(agent, agent_headers)

        shapes: list[Any] = [
            "CN=Muster,OU=Lehrer,DC=x",  # find_user_dn
            ["CN=A", "CN=B"],  # fetch_user_groups
            True,  # probe_service_connection
            [True, "ok"],  # probe_service_connection_detailed
            None,  # modify_password
            {"a": 1},  # ein Objekt geht natürlich weiter
        ]
        for shape in shapes:
            job_id = db_client.post(
                f"/api/tenants/{tenant_id}/jobs", json={"method": "find_user_dn"}
            ).json()["id"]
            db_client.get("/connector/jobs?wait=false", headers=headers)
            body = {"ok": True, "result": shape, "error": None}
            raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
            resp = db_client.post(
                f"/connector/jobs/{job_id}/result",
                headers=headers,
                json={**body, "signature": sign_result(agent["result_hmac_key"], job_id, raw)},
            )
            assert resp.status_code == 200, f"{shape!r} wurde abgewiesen: {resp.text}"
            detail = db_client.get(f"/api/tenants/{tenant_id}/jobs/{job_id}").json()
            assert detail["state"] == "done"
            assert detail["result"] == shape

    def test_a_forged_signature_is_refused(
        self, db_client: TestClient, agent_headers: dict[str, str]
    ) -> None:
        """Die HMAC beweist die Unversehrtheit, nicht die Identität.

        Ein Zwischenglied, das TLS terminiert, soll ein „Passwort gesetzt"
        nicht in ein „nein" verwandeln können.
        """
        tenant_id = _tenant(db_client, "hmac")
        _activate(db_client, tenant_id)
        agent = _enroll(db_client, tenant_id, agent_headers)
        headers = _auth(agent, agent_headers)
        job_id = db_client.post(
            f"/api/tenants/{tenant_id}/jobs", json={"method": "find_user_dn"}
        ).json()["id"]
        db_client.get("/connector/jobs?wait=false", headers=headers)

        resp = db_client.post(
            f"/connector/jobs/{job_id}/result",
            headers=headers,
            json={"ok": True, "result": None, "error": None, "signature": "0" * 64},
        )
        assert resp.status_code == 400

    def test_a_signature_cannot_be_moved_to_another_job(
        self, db_client: TestClient, agent_headers: dict[str, str]
    ) -> None:
        """Deshalb steht die Auftrags-Id in der Signatur."""
        tenant_id = _tenant(db_client, "umhaengen")
        _activate(db_client, tenant_id)
        agent = _enroll(db_client, tenant_id, agent_headers)
        headers = _auth(agent, agent_headers)
        first = db_client.post(
            f"/api/tenants/{tenant_id}/jobs", json={"method": "find_user_dn"}
        ).json()["id"]
        second = db_client.post(
            f"/api/tenants/{tenant_id}/jobs", json={"method": "fetch_user_groups"}
        ).json()["id"]
        db_client.get("/connector/jobs?wait=false", headers=headers)
        db_client.get("/connector/jobs?wait=false", headers=headers)

        body = {"ok": True, "result": None, "error": None}
        raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        stolen = sign_result(agent["result_hmac_key"], first, raw)
        resp = db_client.post(
            f"/connector/jobs/{second}/result",
            headers=headers,
            json={**body, "signature": stolen},
        )
        assert resp.status_code == 400

    def test_a_password_payload_is_purged_after_completion(
        self, db_client: TestClient, agent_headers: dict[str, str]
    ) -> None:
        """Sofort nach Abschluss, nicht per Aufräumlauf.

        Ein Passwort, das noch zehn Minuten in der Datenbank liegt, ist zehn
        Minuten zu lang.
        """
        tenant_id = _tenant(db_client, "purge")
        _activate(db_client, tenant_id)
        agent = _enroll(db_client, tenant_id, agent_headers)
        headers = _auth(agent, agent_headers)
        job_id = db_client.post(
            f"/api/tenants/{tenant_id}/jobs",
            json={"method": "modify_password", "payload": {"password": "Geheim-123"}},
        ).json()["id"]
        claimed = db_client.get("/connector/jobs?wait=false", headers=headers)
        assert claimed.json()[0]["payload"] == {"password": "Geheim-123"}

        body = {"ok": True, "result": None, "error": None}
        raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        db_client.post(
            f"/connector/jobs/{job_id}/result",
            headers=headers,
            json={**body, "signature": sign_result(agent["result_hmac_key"], job_id, raw)},
        )

        listing = db_client.get(f"/api/tenants/{tenant_id}/jobs").json()
        row = next(j for j in listing if j["id"] == job_id)
        assert row["payload_purged_at"] is not None
        # Der Konsolenblick zeigt ohnehin keine Nutzlast — und das Passwort
        # steht nirgends mehr in der Antwort.
        assert "Geheim-123" not in json.dumps(listing)

    def test_a_result_for_an_unclaimed_job_is_refused(
        self, db_client: TestClient, agent_headers: dict[str, str]
    ) -> None:
        tenant_id = _tenant(db_client, "unclaimed")
        _activate(db_client, tenant_id)
        agent = _enroll(db_client, tenant_id, agent_headers)
        headers = _auth(agent, agent_headers)
        job_id = db_client.post(
            f"/api/tenants/{tenant_id}/jobs", json={"method": "find_user_dn"}
        ).json()["id"]
        body = {"ok": True, "result": None, "error": None}
        raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        resp = db_client.post(
            f"/connector/jobs/{job_id}/result",
            headers=headers,
            json={**body, "signature": sign_result(agent["result_hmac_key"], job_id, raw)},
        )
        # Nie übernommen: der Agent kann kein Ergebnis liefern.
        assert resp.status_code == 409
