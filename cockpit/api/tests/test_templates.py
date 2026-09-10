"""Globale Vorlagen: pflegen und ausliefern (ADR-0018).

Vier Dinge, die kein Gefühl, sondern eine Prüfung brauchen:

* **Die Fassungsnummer.** Sie steigt bei einer inhaltlichen Änderung und bei
  einer Änderung der Zielgruppe *nicht* (D4). Vom Hinweis beim Kunden hängt
  ab, dass das stimmt: ein Häkchen in der Konsole darf ihn nicht auslösen.
* **Die Zielgruppe.** Wer nicht gemeint ist, bekommt die Vorlage nicht — und
  erfährt auch nicht, dass es sie gibt (D5).
* **Die Vollständigkeit der Liste.** Was ausgeschaltet oder gelöscht ist,
  verschwindet aus der Auslieferung (D6).
* **Die Schlüssel.** Sie sind dieselben wie in der Datenebene. Ein Test hält
  die beiden Listen zusammen; ohne ihn endet eine Umbenennung dort in einer
  stillen Nicht-Zuordnung, bei der niemand einen Fehler sieht.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from cockpit_api.services.templates import (
    LANGUAGES,
    TEMPLATE_KEYS,
    TemplateError,
    validate_body,
)

BODY = "<p>Guten Tag {{ student.display_name }}</p>"


# --- Reine Logik -----------------------------------------------------------
class TestBodyValidation:
    def test_unknown_key_is_refused_with_the_allowed_ones(self) -> None:
        with pytest.raises(TemplateError) as exc:
            validate_body("rechnung", "de", BODY)
        # Die Meldung nennt die erlaubten Schlüssel: „ungültig" allein kostet
        # den Betreiber genau die Zeit, die diese Zeile spart.
        assert "enrollment" in str(exc.value)

    def test_unknown_language_is_refused(self) -> None:
        with pytest.raises(TemplateError):
            validate_body("enrollment", "rm", BODY)

    def test_empty_body_is_refused(self) -> None:
        with pytest.raises(TemplateError):
            validate_body("enrollment", "de", "   \n  ")

    @pytest.mark.parametrize(
        "body",
        [
            "<script>alert(1)</script>",
            "<SCRIPT src=x>",
            "<p>ok</p><iframe src='x'></iframe>",
            "< script >",
        ],
    )
    def test_a_letter_is_a_document_not_a_program(self, body: str) -> None:
        """Die Datenebene rendert in einer Sandbox — das wird hier nicht gebraucht.

        Ein `<script>` im Rumpf käme also nie zur Ausführung, wo es Schaden
        anrichtet. Es ist trotzdem ein Befund: es heisst, dass jemand HTML aus
        einer fremden Quelle eingefügt hat, und das gehört nicht in einen
        Elternbrief.
        """
        with pytest.raises(TemplateError):
            validate_body("enrollment", "de", body)

    def test_a_plain_letter_passes(self) -> None:
        validate_body("enrollment", "de", BODY)


class TestKeysAgreeWithTheDataPlane:
    """Dieselben Schlüssel auf beiden Seiten — geprüft, nicht behauptet.

    Gelesen wird die Datei der Datenebene, nicht importiert: die Konsole hängt
    nicht von `magister_api` ab, und das soll so bleiben. `ast` statt eines
    Imports, damit dieser Test kein zweites Paket in die Umgebung zieht.
    """

    def _data_plane_keys(self) -> set[str] | None:
        path = (
            Path(__file__).resolve().parents[3]
            / "apps"
            / "api"
            / "magister_api"
            / "services"
            / "document_templates.py"
        )
        if not path.exists():
            return None
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if (
                isinstance(node, ast.AnnAssign)
                and getattr(node.target, "id", "") == "EDITABLE_KEYS"
            ):
                assert node.value is not None
                return set(ast.literal_eval(node.value))
        return None

    def test_same_keys(self) -> None:
        keys = self._data_plane_keys()
        if keys is None:
            pytest.skip("Datenebene liegt in dieser Umgebung nicht daneben")
        assert keys == set(TEMPLATE_KEYS), (
            "Die Vorlagen-Schlüssel der Konsole und der Datenebene sind "
            "auseinandergelaufen. Eine Vorlage mit einem Schlüssel, den die "
            "Datenebene nicht kennt, wird ausgeliefert und nie benutzt — ohne "
            "Fehlermeldung."
        )


# --- Über die HTTP-Fläche, mit Datenbank ----------------------------------
def _tenant(cockpit_database_url: str, slug: str, profile: str) -> str:
    import asyncio

    tenant_id = str(uuid.uuid4())

    async def insert() -> None:
        engine = create_async_engine(cockpit_database_url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO tenants (id, slug, name, hostname, status, profile, "
                        "isolation_mode, dsn_ref, schema_name, db_role, created_at, "
                        "updated_at) VALUES (:id, :slug, :name, :host, 'active', :profile, "
                        "'schema', :ref, :schema, :role, now(), now())"
                    ),
                    {
                        "id": tenant_id,
                        "slug": slug,
                        "name": f"Vorlagentest {slug}",
                        "host": f"{slug}.example.ch",
                        "profile": profile,
                        "ref": f"tenant_{slug}",
                        "schema": f"t_{slug}",
                        "role": f"r_{slug}",
                    },
                )
        finally:
            await engine.dispose()

    asyncio.run(insert())
    return tenant_id


@pytest.fixture
def school_tenant(cockpit_schema: str, cockpit_database_url: str) -> str:
    return _tenant(cockpit_database_url, "vorlageschule", "school")


@pytest.fixture
def company_tenant(cockpit_schema: str, cockpit_database_url: str) -> str:
    return _tenant(cockpit_database_url, "vorlagefirma", "company")


def _save(client: TestClient, key: str, language: str, **body: Any) -> Any:
    payload: dict[str, Any] = {"body_html": BODY, "actor": "ops"}
    payload.update(body)
    return client.put(f"/api/platform/templates/{key}/{language}", json=payload)


def _delivered(client: TestClient, tenant_id: str) -> list[dict[str, Any]]:
    state = client.get(f"/api/tenants/{tenant_id}/desired-state")
    assert state.status_code == 200
    return state.json()["templates"]


class TestVersionCounting:
    def test_a_new_template_starts_at_one(
        self, console_client: TestClient, cockpit_schema: str
    ) -> None:
        assert _save(console_client, "enrollment", "de").json()["version"] == 1

    def test_the_same_content_twice_does_not_bump(
        self, console_client: TestClient, cockpit_schema: str
    ) -> None:
        """`PUT` ist idempotent, und die Fassungsnummer beweist es.

        Ein Abgleich, der bei jedem Lauf eine neue Fassung sähe, würde beim
        Kunden jedes Mal den Hinweis auslösen — und der Hinweis wäre nach einer
        Woche Tapete.
        """
        _save(console_client, "enrollment", "de")
        assert _save(console_client, "enrollment", "de").json()["version"] == 1

    def test_new_text_bumps(self, console_client: TestClient, cockpit_schema: str) -> None:
        _save(console_client, "enrollment", "de")
        second = _save(console_client, "enrollment", "de", body_html="<p>anders</p>")
        assert second.json()["version"] == 2

    def test_a_new_lock_bumps(self, console_client: TestClient, cockpit_schema: str) -> None:
        # Die Sperre ist Inhalt: sie ändert, was beim Kunden gilt.
        _save(console_client, "enrollment", "de")
        second = _save(console_client, "enrollment", "de", may_override=False)
        assert second.json()["version"] == 2

    def test_a_new_audience_does_not_bump(
        self, console_client: TestClient, cockpit_schema: str
    ) -> None:
        """Der Entscheid aus D4, als Prüfung.

        Die Zielgruppe ändert, *wer* die Vorlage bekommt, nicht *was* sie
        sagt. Ohne diese Zeile leuchtet bei jedem Kunden „neue Fassung", weil
        in der Konsole jemand ein Häkchen verschoben hat.
        """
        _save(console_client, "enrollment", "de")
        second = _save(
            console_client, "enrollment", "de", audience="profile", audience_profile="school"
        )
        assert second.json()["version"] == 1

    def test_switching_off_does_not_bump(
        self, console_client: TestClient, cockpit_schema: str
    ) -> None:
        _save(console_client, "enrollment", "de")
        assert _save(console_client, "enrollment", "de", is_active=False).json()["version"] == 1


class TestAudience:
    def test_all_reaches_both_profiles(
        self, console_client: TestClient, school_tenant: str, company_tenant: str
    ) -> None:
        _save(console_client, "enrollment", "de")
        assert len(_delivered(console_client, school_tenant)) == 1
        assert len(_delivered(console_client, company_tenant)) == 1

    def test_a_profile_reaches_only_that_profile(
        self, console_client: TestClient, school_tenant: str, company_tenant: str
    ) -> None:
        _save(console_client, "enrollment", "de", audience="profile", audience_profile="company")
        assert _delivered(console_client, school_tenant) == []
        assert len(_delivered(console_client, company_tenant)) == 1

    def test_a_selection_reaches_only_the_chosen(
        self, console_client: TestClient, school_tenant: str, company_tenant: str
    ) -> None:
        _save(
            console_client,
            "enrollment",
            "de",
            audience="selection",
            tenant_ids=[company_tenant],
        )
        assert _delivered(console_client, school_tenant) == []
        assert len(_delivered(console_client, company_tenant)) == 1

    def test_a_profile_without_a_profile_is_refused(
        self, console_client: TestClient, cockpit_schema: str
    ) -> None:
        assert _save(console_client, "enrollment", "de", audience="profile").status_code == 422

    def test_a_profile_on_the_wrong_audience_is_refused(
        self, console_client: TestClient, cockpit_schema: str
    ) -> None:
        # Ein Profil bei `audience = all` wäre eine Zeile, die man beim Lesen
        # für wirksam hält.
        assert (
            _save(
                console_client, "enrollment", "de", audience="all", audience_profile="school"
            ).status_code
            == 422
        )

    def test_an_empty_selection_is_refused(
        self, console_client: TestClient, cockpit_schema: str
    ) -> None:
        response = _save(console_client, "enrollment", "de", audience="selection", tenant_ids=[])
        assert response.status_code == 422
        # Die Meldung nennt den Weg, den der Betreiber wahrscheinlich meinte.
        assert "is_active" in response.json()["detail"]

    def test_an_unknown_tenant_in_the_selection_is_refused(
        self, console_client: TestClient, cockpit_schema: str
    ) -> None:
        response = _save(
            console_client,
            "enrollment",
            "de",
            audience="selection",
            tenant_ids=[str(uuid.uuid4())],
        )
        assert response.status_code == 422

    def test_leaving_the_selection_clears_it(
        self, console_client: TestClient, school_tenant: str, company_tenant: str
    ) -> None:
        """Die alte Auswahl bleibt nicht liegen.

        Sonst gälte sie beim Zurückschalten stillschweigend wieder — mit einem
        Stand, den seit Monaten niemand gesehen hat.
        """
        _save(
            console_client,
            "enrollment",
            "de",
            audience="selection",
            tenant_ids=[company_tenant],
        )
        _save(console_client, "enrollment", "de", audience="all")
        listed = console_client.get("/api/platform/templates").json()["items"]
        assert listed[0]["tenant_ids"] == []


class TestDeliveredListIsComplete:
    def test_switched_off_disappears(self, console_client: TestClient, school_tenant: str) -> None:
        _save(console_client, "enrollment", "de")
        assert len(_delivered(console_client, school_tenant)) == 1
        _save(console_client, "enrollment", "de", is_active=False)
        assert _delivered(console_client, school_tenant) == []

    def test_deleted_disappears(self, console_client: TestClient, school_tenant: str) -> None:
        _save(console_client, "enrollment", "de")
        assert console_client.delete("/api/platform/templates/enrollment/de").status_code == 204
        assert _delivered(console_client, school_tenant) == []

    def test_deleting_what_is_not_there_is_404(
        self, console_client: TestClient, cockpit_schema: str
    ) -> None:
        assert console_client.delete("/api/platform/templates/enrollment/fr").status_code == 404

    def test_the_delivery_carries_what_the_data_plane_needs(
        self, console_client: TestClient, school_tenant: str
    ) -> None:
        _save(console_client, "enrollment", "de", subject="Eintritt", may_override=False)
        (row,) = _delivered(console_client, school_tenant)
        assert row == {
            "key": "enrollment",
            "language": "de",
            "subject": "Eintritt",
            "body_html": BODY,
            "may_override": False,
            "version": 1,
        }


class TestSurface:
    def test_listing_names_the_keys_and_languages(
        self, console_client: TestClient, cockpit_schema: str
    ) -> None:
        # Damit die Oberfläche die Auswahl nicht doppelt pflegt.
        body = console_client.get("/api/platform/templates").json()
        assert set(body["keys"]) == set(TEMPLATE_KEYS)
        assert set(body["languages"]) == set(LANGUAGES)

    def test_needs_a_token(self, client: TestClient, cockpit_schema: str) -> None:
        assert client.get("/api/platform/templates").status_code == 401
