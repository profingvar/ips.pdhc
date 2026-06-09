"""Loader for the patient-facing spärr copy bundle — ticket #210.

The copy itself lives in ``app/copy/sparr_copy.json``; this module is
just the typed accessor. Pure-Python, no I/O beyond a single file
read at process start — the bundle is small (~3 KB) and read-only at
runtime, so we load once and cache.

The bundle's ``legal_review_status`` MUST stay surfaced — the
``loaded()`` accessor exposes it so any consumer can refuse to render
a bundle that hasn't been signed off, and any test can assert the
shipped state. The patient portal is expected to gate production
rendering on ``legal_review_status == "approved"``.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from importlib import resources

log = logging.getLogger(__name__)


_COPY_PACKAGE = "app.copy"
_COPY_FILENAME = "sparr_copy.json"


@lru_cache(maxsize=1)
def loaded() -> dict:
    """Return the parsed copy bundle. Cached for the life of the
    process; tests that want a fresh load can call ``loaded.cache_clear()``.
    """
    try:
        text = resources.files(_COPY_PACKAGE).joinpath(_COPY_FILENAME).read_text(
            encoding="utf-8",
        )
    except (FileNotFoundError, OSError):
        log.warning(
            "sparr_copy bundle not found at %s/%s — returning empty",
            _COPY_PACKAGE, _COPY_FILENAME,
        )
        return {}
    return json.loads(text)


def metadata() -> dict:
    return loaded().get("metadata", {})


def is_legally_approved() -> bool:
    """True iff the bundle has been marked ``approved`` (legal
    sign-off recorded). Production UIs SHOULD refuse to render a
    bundle that returns False here.
    """
    return metadata().get("legal_review_status") == "approved"


def section(name: str, lang: str = "sv") -> dict:
    """Return a section of the bundle in the requested language,
    falling back to the primary language declared in metadata."""
    bundle = loaded()
    sect = bundle.get(name, {})
    if not isinstance(sect, dict):
        return {}
    if lang in sect:
        return sect[lang]
    primary = metadata().get("language_primary", "sv")
    return sect.get(primary, {})
