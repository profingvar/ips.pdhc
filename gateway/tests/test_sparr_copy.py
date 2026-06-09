"""Tests for the spärr patient-facing copy bundle and endpoint —
ticket #210.

Focus areas:
  - Bundle parses and contains every named section.
  - Both Swedish (primary) + English (secondary) variants present
    for every section.
  - Placeholder names are consistent across languages so client-side
    template fill can use one set of variables for both translations.
  - Endpoint /api/v1/patient/copy/sparr returns the right shape with
    and without ?lang=.
  - The legal_review_status field is surfaced through the loader and
    the endpoint — production UIs gate on this.
  - The shipped bundle is "draft" (not yet legally approved); when
    counsel signs off, that test flip + a fresh commit is the audit
    trail.
"""
from __future__ import annotations

import re
import string

import pytest

from app.services import sparr_copy as sc


# ---------------------------------------------------------------------------
# Bundle structure
# ---------------------------------------------------------------------------

SECTIONS = [
    "block_create_confirmation",
    "block_list",
    "indispensable_care_notification",
    "common",
]


def setup_function(_fn):
    # Each test gets a fresh load — the lru_cache could mask a
    # corrupted-bundle regression otherwise.
    sc.loaded.cache_clear()


def test_metadata_shape():
    md = sc.metadata()
    assert md["language_primary"] == "sv"
    assert "sv" in md["languages"]
    assert "en" in md["languages"]
    assert md["ticket"] == "#210"
    assert md["legal_review_status"] in ("draft", "approved")


def test_shipped_bundle_is_draft_pending_legal_review():
    """Pin the shipped state to "draft" — counsel sign-off is recorded
    by flipping this AND updating this test in the same commit, so the
    audit trail is git-grep-able.
    """
    assert sc.metadata()["legal_review_status"] == "draft"
    assert sc.is_legally_approved() is False


def test_every_section_in_both_languages():
    for name in SECTIONS:
        sv = sc.section(name, "sv")
        en = sc.section(name, "en")
        assert sv, f"missing Swedish copy for {name}"
        assert en, f"missing English copy for {name}"


def test_lang_fallback_uses_primary():
    """A request for an unknown language falls back to Swedish (the
    declared primary)."""
    fallback = sc.section("block_create_confirmation", "fr")
    sv = sc.section("block_create_confirmation", "sv")
    assert fallback == sv


# ---------------------------------------------------------------------------
# Placeholder consistency across languages
# ---------------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _placeholders_in(value):
    """Recursively collect every {placeholder} key seen in nested
    strings / lists."""
    found = set()
    if isinstance(value, str):
        found.update(_PLACEHOLDER_RE.findall(value))
    elif isinstance(value, list):
        for item in value:
            found.update(_placeholders_in(item))
    elif isinstance(value, dict):
        for v in value.values():
            found.update(_placeholders_in(v))
    return found


@pytest.mark.parametrize("name", SECTIONS)
def test_placeholders_match_across_languages(name):
    """Swedish and English variants must reference the SAME set of
    template variables; otherwise client-side rendering would need a
    per-language placeholder map.
    """
    sv_placeholders = _placeholders_in(sc.section(name, "sv"))
    en_placeholders = _placeholders_in(sc.section(name, "en"))
    assert sv_placeholders == en_placeholders, (
        f"{name}: sv has {sv_placeholders - en_placeholders}, "
        f"en has {en_placeholders - sv_placeholders}"
    )


def test_indispensable_notification_carries_required_template_vars():
    """The notification template MUST surface the law's mechanical
    filter — without {concept_summary} / {from_date} / {until_date}
    the patient can't see the scope of the access. Pin them so a
    well-meaning copy edit doesn't quietly drop one.
    """
    required = {
        "caregiver_name", "accessed_at", "reason",
        "concept_summary", "from_date", "until_date",
        "expires_at", "audit_link", "caregiver_contact",
    }
    placeholders = _placeholders_in(
        sc.section("indispensable_care_notification", "sv")
    )
    missing = required - placeholders
    assert not missing, f"missing required vars: {missing}"


def test_block_create_confirmation_carries_source_name():
    """The patient must see *what* she is about to block — the
    {source_scope_name} placeholder is the only way the UI can show
    it. Pin so a future rewrite doesn't make the consent generic.
    """
    sv = sc.section("block_create_confirmation", "sv")
    placeholders = _placeholders_in(sv)
    assert "source_scope_name" in placeholders


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

def test_endpoint_returns_full_bundle_without_lang(client, db):
    resp = client.get("/api/v1/patient/copy/sparr")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["metadata"]["legal_review_status"] == "draft"
    for name in SECTIONS:
        assert name in body
        # Multi-language bundle: both langs available
        assert "sv" in body[name]
        assert "en" in body[name]


def test_endpoint_returns_single_language_slice(client, db):
    resp = client.get("/api/v1/patient/copy/sparr?lang=en")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["lang"] == "en"
    # English text only — sv is gone
    bcc = body["block_create_confirmation"]
    assert "title" in bcc
    assert bcc["title"] == "Block your care data"


def test_endpoint_lang_fallback_returns_primary(client, db):
    resp = client.get("/api/v1/patient/copy/sparr?lang=zz")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["lang"] == "zz"
    # Fallback to primary (sv)
    bcc = body["block_create_confirmation"]
    assert bcc["title"] == "Spärr av din vårddata"


def test_endpoint_requires_authentication(client, db, app):
    """Sanity-check: in production (AUTH_DISABLED=False) the endpoint
    rejects unauthenticated callers."""
    app.config["AUTH_DISABLED"] = False
    try:
        resp = client.get("/api/v1/patient/copy/sparr")
    finally:
        app.config["AUTH_DISABLED"] = True
    assert resp.status_code == 401
