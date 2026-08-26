"""Every built-in starter template must render against the sample context."""

from __future__ import annotations

from magister_api.services.document_templates import (
    COMPANY_STARTER_TEMPLATES,
    EDITABLE_KEYS,
    STARTER_TEMPLATES,
    DocumentTemplateService,
    sample_context,
    starters_for_profile,
)


def test_starters_cover_every_editable_key() -> None:
    assert set(STARTER_TEMPLATES) == set(EDITABLE_KEYS)
    # The company variants cover the same keys so the editor works in both editions.
    assert set(COMPANY_STARTER_TEMPLATES) == set(EDITABLE_KEYS)


def test_starters_for_profile_selects_company_variant() -> None:
    assert starters_for_profile("company") is COMPANY_STARTER_TEMPLATES
    assert starters_for_profile("school") is STARTER_TEMPLATES
    assert starters_for_profile("neutral") is STARTER_TEMPLATES


def test_every_starter_body_and_subject_render() -> None:
    ctx = sample_context()
    for source in (STARTER_TEMPLATES, COMPANY_STARTER_TEMPLATES):
        for key, starter in source.items():
            body = DocumentTemplateService.render_body(starter["body_html"], ctx)
            subject = DocumentTemplateService.render_body(starter["subject"], ctx)
            assert body.strip(), f"{key}: empty rendered body"
            assert subject.strip(), f"{key}: empty rendered subject"
            # Placeholders were substituted, not left literal.
            assert "{{" not in body
            assert "{{" not in subject


def test_company_starters_have_no_school_vocabulary() -> None:
    # Company variants must not carry school words (Klasse / Schuljahr / Eltern).
    for key, starter in COMPANY_STARTER_TEMPLATES.items():
        blob = f"{starter['subject']} {starter['body_html']}"
        for word in ("Klasse", "Schuljahr", "Eltern", "Schüler"):
            assert word not in blob, f"{key}: company starter still says {word!r}"
