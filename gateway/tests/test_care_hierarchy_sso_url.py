"""#708 — the care-hierarchy sync read a config key ips does not set.

Found by `deploy/smoke_siblings.py` on its first run against production, which
is the kind of defect #708 was filed for: nothing inside this repo was wrong,
and every unit test passed, because the tests supply the variable production
does not.

What the smoke saw: `flask sync-care-hierarchy` refused with "SSO_BASE_URL is
not configured" — before it ever reached the token. ips declares exactly one
sso base URL, `OAUTH_BASE_URL` (`app/config.py`), and this module read only
`SSO_BASE_URL` / `SSO_INTERNAL_URL`. Neither is in production's env, so the
sync has never been able to run, and it reported a configuration error for a
variable nobody was asked to set.

These tests pin the resolution order rather than just the fix, because the
fix is "read the key the service has" and the failure mode of getting that
wrong is an operator's override being silently ignored.
"""
from __future__ import annotations

import pytest

from app.services.care_hierarchy_sync import (
    SsoHierarchyUnavailable, _SSO_URL_KEYS, _sso_base, sync,
)


@pytest.fixture
def cfg(app):
    with app.app_context():
        from flask import current_app
        before = {k: current_app.config.get(k) for k in _SSO_URL_KEYS}
        for k in _SSO_URL_KEYS:
            current_app.config[k] = None
        yield current_app.config
        current_app.config.update(before)


def test_OAUTH_BASE_URL_is_accepted_because_it_is_the_one_ips_SETS(cfg):
    cfg["OAUTH_BASE_URL"] = "https://sso.pdhc.se"
    assert _sso_base() == "https://sso.pdhc.se"


def test_an_operators_explicit_SSO_BASE_URL_still_WINS(cfg):
    """The two older keys stay ahead of it, so anyone who has set one keeps
    their override. Reading the new key first would silently redirect a
    deliberately pointed sync."""
    cfg["OAUTH_BASE_URL"] = "https://sso.pdhc.se"
    cfg["SSO_BASE_URL"] = "http://sso-internal:9000"
    assert _sso_base() == "http://sso-internal:9000"


def test_SSO_INTERNAL_URL_sits_between_them(cfg):
    cfg["OAUTH_BASE_URL"] = "https://sso.pdhc.se"
    cfg["SSO_INTERNAL_URL"] = "http://sso-internal:9000"
    assert _sso_base() == "http://sso-internal:9000"


def test_a_trailing_slash_does_not_double_up(cfg):
    cfg["OAUTH_BASE_URL"] = "https://sso.pdhc.se/"
    assert _sso_base() == "https://sso.pdhc.se"


def test_an_EMPTY_string_is_not_a_configured_url(cfg):
    """`os.environ.get(k, "")` means an unset variable arrives as "", so a
    truthiness test on the first key alone would have returned "" and built
    `/api/registry/care-units` as a relative URL."""
    cfg["SSO_BASE_URL"] = ""
    cfg["SSO_INTERNAL_URL"] = "   "
    cfg["OAUTH_BASE_URL"] = "https://sso.pdhc.se"
    assert _sso_base() == "https://sso.pdhc.se"


def test_with_NOTHING_configured_it_names_every_key_it_would_accept(cfg):
    with pytest.raises(SsoHierarchyUnavailable) as e:
        _sso_base() or sync(token="t", dry_run=True)
    for key in _SSO_URL_KEYS:
        assert key in str(e.value)


def test_a_configured_url_with_NO_TOKEN_fails_on_the_TOKEN_not_the_url(cfg):
    """The distinction the error exists for. "No token" is a missing
    credential HERE; "unreachable" is sso's problem. Conflating them sends
    the operator to the wrong service — and before this fix the operator was
    sent to a third place, a variable that did not need to exist."""
    cfg["OAUTH_BASE_URL"] = "https://sso.pdhc.se"
    with pytest.raises(SsoHierarchyUnavailable) as e:
        sync(token=None, dry_run=True)
    msg = str(e.value).lower()
    assert "token" in msg
    assert "not configured" not in msg
