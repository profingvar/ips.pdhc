"""#902 — ips's admin surface was gated on a SESSION and nothing else.

The ticket was filed with its uncertainty stated: whether a session-only
gate was EXPOSURE depended on whether sso.pdhc would issue a usable token
for ips to an arbitrary user. That was the one thing that had to be
measured first, and the last security ticket filed here from
configuration alone had to be withdrawn (#844 -> #845).

MEASURED 2026-11-02, in code on both sides. sso does NOT gate it:

  - `sso.pdhc/app/src/routes/auth.py:123` — `/api/auth/me/service`
    authenticates the USER (`@require_auth`) and authenticates the
    SERVICE (constant-time client-id/secret compare), then builds the
    access blob with no check at all that this user may use this service.
  - sso has no per-user service allowlist. `allowed_services` lives only
    on `Organisation`, for the machine/partner path, never on a human
    user's token.
  - `app/api/sso_routes.py` stored the returned blob on any 200. It read
    `user_type` and `is_su_admin` into the session and the gate consulted
    neither.

So this was exposure, not a defence-in-depth gap: any authenticated
platform user who completed ips's SSO callback — A PATIENT INCLUDED — got
all 23 admin routes, ten of which write and one of which (`mock-data/purge`)
deletes patients, clinical resources and clinic assignments.

THE TELL THAT IT HID FOR SO LONG: the full suite was 990 passing both
before and after this gate was written. Not one existing test exercised
it, because every test runs under AUTH_DISABLED, where the gate returns
immediately. A security gate with no test is indistinguishable from no
gate, so every check below that matters runs with AUTH_DISABLED **off**.

THE SPLIT. CLAUDE.md §11 says ips requires `is_su_admin` OR
(`user_type == 'professional'` AND `'analysis' in effective_phases`). ips
implemented none of it — not here and not in `require_auth`, which has
zero references to `effective_phases`. Enforcing all of it at once could
lock legitimate users out of their own tool, and who logs in today is not
knowable from this repo. So the professional/SU requirement is
unconditional (no legitimate administrator of a patient registry is a
patient) and the phase requirement is shadow-logged behind
`IPS_ADMIN_REQUIRE_ANALYSIS_PHASE` until the operator has the evidence to
flip it.
"""
from __future__ import annotations

import uuid

import pytest

from app.services import admin_access_policy as pol

SU = {"user_guid": str(uuid.uuid4()), "user_type": "professional",
      "is_su_admin": True, "effective_phases": []}
PRO_WITH_PHASE = {"user_guid": str(uuid.uuid4()), "user_type": "professional",
                  "is_su_admin": False, "effective_phases": ["analysis"]}
PRO_NO_PHASE = {"user_guid": str(uuid.uuid4()), "user_type": "professional",
                "is_su_admin": False, "effective_phases": ["care"]}
PATIENT = {"user_guid": str(uuid.uuid4()), "user_type": "patient",
           "is_su_admin": False, "effective_phases": []}
RELATIVE = {"user_guid": str(uuid.uuid4()), "user_type": "relative",
            "is_su_admin": False, "effective_phases": []}


# =====================================================================
# 1. The decision — pure
# =====================================================================

class TestDecision:
    def test_no_session_is_refused(self):
        allowed, reason, shadow = pol.admin_access_decision(None)
        assert allowed is False
        assert reason == pol.REASON_NO_SESSION
        assert shadow is None

    @pytest.mark.parametrize("bad", [None, {}, "", "a-string", 0, []])
    def test_malformed_input_is_refused(self, bad):
        """An admin surface is the wrong place to be generous about a
        value one cannot read."""
        allowed, reason, _ = pol.admin_access_decision(bad)
        assert allowed is False
        assert reason == pol.REASON_NO_SESSION

    def test_a_PATIENT_is_refused(self):
        """The sharpest form of #902: before this, a patient who logged
        in could list every patient in the registry."""
        allowed, reason, _ = pol.admin_access_decision(PATIENT)
        assert allowed is False
        assert reason == pol.REASON_NOT_PROFESSIONAL

    def test_a_RELATIVE_is_refused(self):
        """#890's new identity type must not inherit an admin surface
        just by existing."""
        allowed, reason, _ = pol.admin_access_decision(RELATIVE)
        assert allowed is False
        assert reason == pol.REASON_NOT_PROFESSIONAL

    def test_an_unrecognised_user_type_is_refused(self):
        allowed, reason, _ = pol.admin_access_decision(
            {"user_type": "partner", "is_su_admin": False})
        assert allowed is False
        assert reason == pol.REASON_NOT_PROFESSIONAL

    def test_a_patient_who_is_somehow_su_admin_passes(self):
        """§11's rule is `is_su_admin OR (...)`, so the SU branch is
        deliberately independent of user_type. Asserted so that the
        'or' is not quietly turned into an 'and' by a later edit."""
        allowed, reason, _ = pol.admin_access_decision(
            {**PATIENT, "is_su_admin": True})
        assert allowed is True
        assert reason is None

    def test_an_su_is_exempt_from_the_phase_even_when_enforced(self):
        allowed, reason, shadow = pol.admin_access_decision(
            SU, enforce_phase=True)
        assert (allowed, reason, shadow) == (True, None, None)

    def test_a_professional_with_the_analysis_phase_passes(self):
        for enforce in (False, True):
            allowed, reason, shadow = pol.admin_access_decision(
                PRO_WITH_PHASE, enforce_phase=enforce)
            assert (allowed, reason, shadow) == (True, None, None)


class TestTheShadowHalf:
    def test_a_professional_without_the_phase_passes_but_is_SHADOWED(self):
        """The flag is off: allowed today, flagged as a future refusal.
        This is the whole point of shipping in halves — the operator
        gets the evidence without a lockout."""
        allowed, reason, shadow = pol.admin_access_decision(
            PRO_NO_PHASE, enforce_phase=False)
        assert allowed is True
        assert reason is None
        assert shadow == pol.REASON_PHASE_MISSING

    def test_the_same_user_is_REFUSED_once_the_flag_is_set(self):
        allowed, reason, shadow = pol.admin_access_decision(
            PRO_NO_PHASE, enforce_phase=True)
        assert allowed is False
        assert reason == pol.REASON_PHASE_MISSING
        assert shadow is None

    @pytest.mark.parametrize(
        "who", [PATIENT, RELATIVE, None], ids=["patient", "relative", "none"])
    def test_shadow_is_never_set_alongside_a_real_denial(self, who):
        """Otherwise the shadow log would count users the flag does not
        newly affect, and the operator's evidence would be inflated."""
        for enforce in (False, True):
            allowed, reason, shadow = pol.admin_access_decision(
                who, enforce_phase=enforce)
            assert allowed is False
            assert reason is not None
            assert shadow is None

    def test_the_canonical_session_phases_field_is_PREFERRED(self):
        """A dated bug, caught by comparing with the three sibling
        services #11 names.

        `effective_phases` is on sso's LEGACY_BLOB_FIELDS kill-switch
        list (#409) and is staged to stop being emitted. dashboard,
        rosetta and cdr all read `session_phases or effective_phases`
        (#415/#416/#417). A gate reading only the legacy field would see
        an EMPTY phase list the day that flag flips and would then refuse
        every professional on the platform.
        """
        post_reform = {"user_type": "professional", "is_su_admin": False,
                       "session_phases": ["analysis"]}       # no legacy key
        allowed, reason, shadow = pol.admin_access_decision(
            post_reform, enforce_phase=True)
        assert (allowed, reason, shadow) == (True, None, None)

    def test_the_legacy_field_still_works_for_a_pre_reform_token(self):
        """The other direction: dual-emit is still on today, so a blob
        carrying only the legacy field must keep working."""
        pre_reform = {"user_type": "professional", "is_su_admin": False,
                      "effective_phases": ["analysis"]}      # no canonical key
        allowed, reason, shadow = pol.admin_access_decision(
            pre_reform, enforce_phase=True)
        assert (allowed, reason, shadow) == (True, None, None)

    def test_the_canonical_field_WINS_when_both_are_present(self):
        """`session_phases or effective_phases` — asserted as an order,
        not merely as a union, so a later edit cannot turn it into one."""
        both = {"user_type": "professional", "is_su_admin": False,
                "session_phases": ["care"],            # canonical: no analysis
                "effective_phases": ["analysis"]}      # legacy: analysis
        allowed, reason, _ = pol.admin_access_decision(
            both, enforce_phase=True)
        assert allowed is False
        assert reason == pol.REASON_PHASE_MISSING

    def test_the_sso_callback_stores_BOTH_phase_fields(self):
        """The gate can only prefer a field the session actually
        carries."""
        import inspect
        from app.api import sso_routes
        src = inspect.getsource(sso_routes)
        assert '"session_phases"' in src
        assert '"effective_phases"' in src

    def test_the_flag_name_is_the_one_the_gate_reads(self):
        assert pol.PHASE_FLAG == "IPS_ADMIN_REQUIRE_ANALYSIS_PHASE"

    def test_a_shadow_denial_names_the_user_in_the_log(self, caplog):
        """A silent counter would not answer the question the flag
        exists to answer: WHO would be affected."""
        import logging
        with caplog.at_level(logging.WARNING):
            pol.log_shadow_denial(
                PRO_NO_PHASE, "admin.patients", pol.REASON_PHASE_MISSING)
        assert PRO_NO_PHASE["user_guid"] in caplog.text
        assert pol.PHASE_FLAG in caplog.text


# =====================================================================
# 2. The public-endpoint set — the #804 substring fix
# =====================================================================

class TestPublicEndpoints:
    def test_the_four_doc_downloads_are_public(self):
        for ep in ("admin.docs_api_download", "admin.docs_capability_download",
                   "admin.docs_manual_download",
                   "admin.docs_technical_download"):
            assert ep in pol.PUBLIC_ADMIN_ENDPOINTS

    @pytest.mark.parametrize("ep", [
        "admin.patients_download",
        "admin.download_all_patients",
        "admin.export_download",
        "admin.patients",
    ])
    def test_an_endpoint_merely_CONTAINING_download_is_not_public(self, ep):
        """The old gate was `if "download" in request.endpoint`, which
        would have exempted every one of these. That is the #804 shape:
        matching a name instead of naming a capability. An explicit set
        cannot be widened by someone choosing a route name."""
        assert ep not in pol.PUBLIC_ADMIN_ENDPOINTS

    def test_THE_GATE_refuses_a_download_named_endpoint_not_in_the_set(
            self, client, db):
        """The behavioural half, and the one that matters.

        The two checks above assert a fact about a set this file's author
        also wrote — they prove the set is narrow, not that the GATE
        consults it. The old gate was
        `if "download" in request.endpoint: return None`, and both of
        them would pass against it unchanged.

        So: drive the gate directly with a crafted endpoint name that
        CONTAINS "download" but is not in the set, and demand it does not
        wave the request through. `request.endpoint` reads
        `request.url_rule.endpoint`, so substituting the rule is enough —
        no blueprint surgery, which Flask refuses once the app has served
        a request.

        Against the substring gate this returns None (admitted). Against
        the set it must return a response.
        """
        from unittest.mock import patch
        from flask import request as freq
        from app.admin import _require_admin

        class _Rule:
            endpoint = "admin.patients_download"   # contains "download"

        app = client.application
        with patch.dict(app.config, {"AUTH_DISABLED": False}), \
                app.test_request_context("/admin/patients"):
            freq.url_rule = _Rule()
            assert freq.endpoint == "admin.patients_download"
            assert freq.endpoint not in pol.PUBLIC_ADMIN_ENDPOINTS
            out = _require_admin()

        assert out is not None, (
            "an endpoint merely NAMED *download* was waved through — the "
            "gate is matching the name, not the set"
        )

    def test_AND_a_real_doc_download_IS_still_waved_through(self, client, db):
        """The other direction, with the same mechanism: the exemption
        must still work, or the test above would pass simply because the
        gate refuses everything."""
        from unittest.mock import patch
        from flask import request as freq
        from app.admin import _require_admin

        class _Rule:
            endpoint = "admin.docs_api_download"

        app = client.application
        with patch.dict(app.config, {"AUTH_DISABLED": False}), \
                app.test_request_context("/admin/docs/api/download"):
            freq.url_rule = _Rule()
            assert _require_admin() is None

    def test_the_gate_no_longer_contains_the_substring_check(self):
        """Belt to the braces above: the exact expression is gone."""
        import inspect
        from app import admin as admin_module
        src = inspect.getsource(admin_module._require_admin)
        assert '"download" in request.endpoint' not in src
        assert "PUBLIC_ADMIN_ENDPOINTS" in src

    def test_the_set_holds_only_documentation_endpoints(self):
        """Nothing that could carry patient data may be in here."""
        assert all("docs_" in ep for ep in pol.PUBLIC_ADMIN_ENDPOINTS)


# =====================================================================
# 3. The wiring, with AUTH_DISABLED OFF — because that is the only way
#    to see what production does
# =====================================================================

@pytest.fixture
def live(client):
    """Turn the dev bypass off for the duration of one test."""
    from unittest.mock import patch
    app = client.application
    with patch.dict(app.config, {"AUTH_DISABLED": False}):
        yield client


def _login(client, who):
    with client.session_transaction() as sess:
        sess["sso_user"] = who


class TestTheGateLive:
    def test_no_session_REDIRECTS_to_login(self, live, db):
        r = live.get("/admin/")
        assert r.status_code == 302
        assert "/sso/login" in r.headers["Location"] or "login" in \
            r.headers["Location"]

    def test_a_patient_gets_403_NOT_a_redirect_loop(self, live, db):
        """A refusal must not be sent to the login page: they would log
        in again through SSO and be refused again, for ever."""
        _login(live, PATIENT)
        r = live.get("/admin/")
        assert r.status_code == 403, r.status_code

    def test_a_patient_cannot_LIST_every_patient(self, live, db):
        """#902's headline."""
        _login(live, PATIENT)
        assert live.get("/admin/patients").status_code == 403

    def test_a_patient_cannot_reach_the_destructive_PURGE_route(
            self, live, db):
        """mock-data/purge deletes patients, clinical resources and
        clinic assignments. It had the same session-only gate as the
        dashboard."""
        _login(live, PATIENT)
        r = live.post("/admin/mock-data/purge",
                      data={"batch_guid": str(uuid.uuid4())})
        assert r.status_code == 403

    @pytest.mark.parametrize("route", [
        "/admin/", "/admin/patients", "/admin/push", "/admin/docs",
    ])
    def test_a_patient_is_refused_on_every_sampled_route(
            self, live, db, route):
        """The gate is a single before_request, so one refusal should
        cover the surface — asserted rather than assumed."""
        _login(live, PATIENT)
        assert live.get(route).status_code == 403

    def test_an_su_is_admitted(self, live, db):
        _login(live, SU)
        assert live.get("/admin/").status_code == 200

    def test_a_professional_with_the_phase_is_admitted(self, live, db):
        _login(live, PRO_WITH_PHASE)
        assert live.get("/admin/").status_code == 200

    def test_a_professional_without_the_phase_is_admitted_TODAY(
            self, live, db):
        """The shadow half, live: still allowed, because enforcing it
        now could lock out a legitimate user nobody has identified."""
        _login(live, PRO_NO_PHASE)
        assert live.get("/admin/").status_code == 200

    def test_and_REFUSED_once_the_operator_sets_the_flag(self, live, db):
        from unittest.mock import patch
        _login(live, PRO_NO_PHASE)
        with patch.dict(live.application.config,
                        {pol.PHASE_FLAG: True}):
            assert live.get("/admin/").status_code == 403

    def test_the_doc_download_stays_reachable_without_a_session(
            self, live, db):
        """The exemption still works — it is now an explicit set rather
        than a substring, but it must not have been broken in the
        change."""
        r = live.get("/admin/docs/api/download")
        assert r.status_code == 200, r.status_code

    def test_an_admitted_request_LOADS_a_user(self, live, db):
        """#902 step 3. Previously nothing was loaded on this surface —
        no g.current_user, no resolved blob — which is why #896's export
        had to be moved to the API blueprint to find a user to filter
        on."""
        from flask import g as flask_g
        # Asserted by calling the gate inside a request context, because
        # `g` does not survive the request a test client makes. An
        # earlier version of this test also registered a probe route,
        # which Flask refuses after the first request has been handled —
        # dead scaffolding, removed.
        with live.application.test_request_context("/admin/"):
            from flask import session as fsession
            fsession["sso_user"] = SU
            from app.admin import _require_admin
            assert _require_admin() is None
            assert flask_g.admin_user == SU

    def test_the_dev_bypass_still_works_when_AUTH_DISABLED(self, client, db):
        """The no-op half: every other test in this repo depends on it,
        and 990 of them pass, but it is asserted here on purpose because
        it is the reason the gate hid."""
        assert client.get("/admin/").status_code == 200
