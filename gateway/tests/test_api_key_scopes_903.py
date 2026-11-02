"""#903 — `ApiKey.scopes` existed and gated nothing.

Found while working #903 (EPS B6b), whose step 3 asks for a service key
"scoped to the one route and nothing else". The mechanism to do that was
already in the model and was inert.

MEASURED 2026-11-02. `ApiKey.scopes` is SET at mint time
(`app/api/auth_routes.py:31`) and COPIED on rotation (`:89`), and read
NOWHERE in `app/` outside the model. `validate_api_key` checks active,
revoked and expired, returns the key, and `require_auth` turns it into an
identity without ever consulting the column.

So every API key in ips reached every `@require_auth` route — the whole
FHIR surface, patients, blocks, consents, state, export — whatever it was
issued for. That is the #729 shape (a field that looks like a gate and
gates nothing) producing the #760 consequence (a credential issued for
one purpose reaching everything).

A second fact that sharpens it: a key minted by a logged-in user carries
that user's guid, so `api_key.user` resolves to them and the key inherits
their privileges in full. A key minted by an SU is an SU key.

WHY THE FIX IS ADDITIVE. Requiring every key to carry a scope would break
every key already issued, because they were minted with `scopes=[]` and
nothing ever required otherwise — the same lockout risk as #902's phase
gate, and the same answer: opt in per route. A route that declares no
scope behaves exactly as before. A route that declares one admits only a
key carrying it. That is asserted in both directions below, because
"additive" is a claim about the routes NOT changed and is otherwise
untested.
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from flask import g as flask_g

from app.models.api_key import ApiKey
from app.services.auth_service import (
    hash_api_key, require_auth, require_scope, SCOPE_IMPLANTS_WRITE,
)

SCOPE = SCOPE_IMPLANTS_WRITE


def _mk_key(db, scopes, *, active=True):
    raw = f"k-{uuid.uuid4()}"
    key = ApiKey(
        key_hash=hash_api_key(raw),
        label="903 test key",
        prefix=raw[:8],
        scopes=scopes,
        is_active=active,
    )
    db.session.add(key)
    db.session.commit()
    return raw, key


# Two probe views, decorated exactly as a real route would be and
# dispatched inside a request context rather than REGISTERED on the app.
#
# An earlier version of this file registered them with @app.route on the
# session-scoped test app. That produced 13 errors when the whole suite
# ran — Flask refuses `route` once an app has handled a request — and it
# made one test order-dependent. Dispatching directly exercises the same
# decorator stack with no app mutation and no ordering.


@require_auth
@require_scope(SCOPE)
def _probe_scoped():
    return {"ok": True, "key": getattr(
        getattr(flask_g, "api_key", None), "prefix", None)}


@require_auth
def _probe_open():
    return {"ok": True}


def _call(app, view, *, headers=None, auth_disabled=False):
    """Dispatch a decorated view and normalise its outcome to
    (status, body_text).

    A decorator short-circuit returns ``(response, code)``; a success
    returns the view's own dict.
    """
    with patch.dict(app.config, {"AUTH_DISABLED": auth_disabled}), \
            app.test_request_context("/__probe903", method="POST",
                                     headers=headers or {}):
        out = view()
    if isinstance(out, tuple):
        body, code = out
        text = body.get_data(as_text=True) if hasattr(body, "get_data") \
            else str(body)
        return code, text
    return 200, str(out)


@pytest.fixture
def app_(client):
    return client.application


class TestTheColumnWasDecorative:
    def test_scopes_is_now_read_by_the_gate(self):
        """The regression guard for the finding itself: the column must
        be consulted somewhere outside the model."""
        import inspect
        from app.services import auth_service
        src = inspect.getsource(auth_service.require_scope)
        assert "api_key.scopes" in src

    def test_require_auth_exposes_the_KEY_not_only_the_identity(self):
        """`g.api_key` is what made the column readable downstream.
        Without it the scopes are unreachable from a route, which is how
        they stayed decorative."""
        import inspect
        from app.services import auth_service
        src = inspect.getsource(auth_service.require_auth)
        assert "g.api_key = api_key" in src


class TestScopedRoute:
    def test_a_key_WITH_the_scope_is_admitted(self, app_, db):
        raw, key = _mk_key(db, [SCOPE])
        code, text = _call(app_, _probe_scoped,
                           headers={"Authorization": f"ApiKey {raw}"})
        assert code == 200, text
        assert key.prefix in text

    def test_a_key_WITHOUT_the_scope_is_refused(self, app_, db):
        raw, _ = _mk_key(db, ["something:else"])
        code, text = _call(app_, _probe_scoped,
                           headers={"Authorization": f"ApiKey {raw}"})
        assert code == 403
        assert SCOPE in text

    def test_an_UNSCOPED_legacy_key_is_refused_on_a_scoped_route(
            self, app_, db):
        """Every key issued before today has scopes=[]. They keep working
        everywhere they worked, and they do NOT reach a route that
        declares a scope."""
        raw, _ = _mk_key(db, [])
        code, _t = _call(app_, _probe_scoped,
                         headers={"Authorization": f"ApiKey {raw}"})
        assert code == 403

    def test_a_null_scopes_column_is_refused_not_crashed(self, app_, db):
        raw, _ = _mk_key(db, None)
        code, _t = _call(app_, _probe_scoped,
                         headers={"Authorization": f"ApiKey {raw}"})
        assert code == 403

    @pytest.mark.parametrize("bad", [
        "implants:write", "implants:write-nothing", 7, {"a": 1},
    ])
    def test_a_MALFORMED_scopes_value_denies(self, app_, db, bad):
        """Fail closed on a value that is not a list of scopes.

        HONEST NOTE on what this proves, twice corrected.

        The first version claimed the `isinstance` guard stops a string
        matching "by substring". That was wrong: iterating a string
        yields single CHARACTERS, which can never equal a
        multi-character scope, so a string denies with or without the
        guard — and the control that removed the guard failed nothing,
        which is how the error was found.

        Parametrising it showed the guard DOES carry behaviour, just not
        the behaviour claimed. Without it, a non-iterable value (`7`)
        raises a TypeError inside the gate and the caller gets a 500
        instead of a clean 403. A dict denies either way, its keys not
        matching. So the guard converts a crash into a refusal, and it
        also keeps a malformed value failing closed should the comparison
        ever be rewritten in `in`-style, where substring matching WOULD
        apply.
        """
        raw, _ = _mk_key(db, bad)
        code, _t = _call(app_, _probe_scoped,
                         headers={"Authorization": f"ApiKey {raw}"})
        assert code == 403

    def test_an_extra_scope_alongside_the_required_one_still_admits(
            self, app_, db):
        raw, _ = _mk_key(db, ["other:read", SCOPE])
        code, text = _call(app_, _probe_scoped,
                           headers={"Authorization": f"ApiKey {raw}"})
        assert code == 200, text

    def test_an_inactive_key_with_the_scope_is_still_refused(
            self, app_, db):
        """require_auth refuses first; the scope check must not become a
        second, weaker door."""
        raw, _ = _mk_key(db, [SCOPE], active=False)
        code, _t = _call(app_, _probe_scoped,
                         headers={"Authorization": f"ApiKey {raw}"})
        assert code == 401

    def test_no_credential_at_all_is_refused(self, app_, db):
        code, _t = _call(app_, _probe_scoped)
        assert code == 401


class TestAnSsoHumanIsRefused:
    def test_a_bearer_caller_cannot_reach_a_scoped_route(self, app_, db):
        """A scoped route exists for a machine. Admitting a human
        identity — even an SU — is how a service surface quietly becomes
        a general one. An SU who needs to drive it by hand mints a key.
        """
        from app.models.user import User
        u = User(username="su903@example.test", email="su903@example.test",
                 display_name="SU 903", is_active=True, is_superuser=True)
        db.session.add(u)
        db.session.commit()
        blob = {"username": u.username, "email": u.email,
                "user_type": "professional", "is_su_admin": True}
        with patch("app.services.auth_service.resolve_sso_user",
                   return_value=blob):
            code, _t = _call(app_, _probe_scoped,
                             headers={"Authorization": "Bearer t"})
        assert code == 403
        # and the SAME caller passes an unscoped route, so the refusal is
        # the scope and not a broken bearer path.
        with patch("app.services.auth_service.resolve_sso_user",
                   return_value=blob):
            code2, text2 = _call(app_, _probe_open,
                                 headers={"Authorization": "Bearer t"})
        assert code2 == 200, text2


class TestItIsAdditive:
    """The claim that existing routes are untouched, asserted rather
    than assumed. These are the checks that would fail if someone later
    made scopes globally mandatory."""

    @pytest.mark.parametrize("scopes", [[], None, ["unrelated:thing"]])
    def test_an_unscoped_route_admits_a_key_with_ANY_scopes(
            self, app_, db, scopes):
        raw, _ = _mk_key(db, scopes)
        code, text = _call(app_, _probe_open,
                           headers={"Authorization": f"ApiKey {raw}"})
        assert code == 200, text

    def test_the_dev_bypass_passes_a_scoped_route(self, app_, db):
        """Matching every other gate in this module, so the suite and
        local development are not required to mint keys.

        An earlier version of this test skipped when a probe ROUTE was
        absent, so it only ran when another test had registered it first
        and reported success in isolation by skipping. A test that passes
        by not running is worse than no test.
        """
        code, text = _call(app_, _probe_scoped, auth_disabled=True)
        assert code == 200, text
