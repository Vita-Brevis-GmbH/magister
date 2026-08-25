"""Every built-in starter template must render against the sample context."""

from __future__ import annotations

from magister_api.services.document_templates import (
    EDITABLE_KEYS,
    STARTER_TEMPLATES,
    DocumentTemplateService,
    sample_context,
)


def test_starters_cover_every_editable_key() -> None:
    assert set(STARTER_TEMPLATES) == set(EDITABLE_KEYS)


def test_every_starter_body_and_subject_render() -> None:
    ctx = sample_context()
    for key, starter in STARTER_TEMPLATES.items():
        body = DocumentTemplateService.render_body(starter["body_html"], ctx)
        subject = DocumentTemplateService.render_body(starter["subject"], ctx)
        assert body.strip(), f"{key}: empty rendered body"
        assert subject.strip(), f"{key}: empty rendered subject"
        # Placeholders were substituted, not left literal.
        assert "{{" not in body
        assert "{{" not in subject
