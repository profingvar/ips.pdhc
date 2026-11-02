"""EPS C3 (#889) — a patient-granted next-of-kin privilege.

#889 called the policy branch "the cost" and estimated 8-15 days on the
premise that `care_access_policy` is "read by eleven services", so a new
branch meant eleven consumers. Measured 2026-11-02, that premise needed
correcting in two directions, one cheaper and one much more expensive.

CHEAPER. A patient reading their own record does not go through
`care_access_policy` at all. That module answers "may this CARE identity
read data authored by that care identity?" and every argument is a care
identity; the patient surface is gated by `auth_service.require_patient`,
which never calls it. Inside ips, `evaluate_care_access` has exactly TWO
call sites, both in `care_access_routes.py`. So a relative reading AS the
patient needs no new zone, and the eleven consumers are untouched.

MORE EXPENSIVE, and this is the real finding. `require_patient` does not
gate a data surface. It gates the patient's SELF-DETERMINATION CONTROLS.
Of the seventeen routes behind the patient identity, TEN are POST, and
they are: create-block, LIFT-block, extend-block, create-consent and
revoke-consent (each in both the JSON and the HTML surface).

So a relative admitted through that decorator without a method gate could
lift the patient's spärr and then read what the spärr had been hiding.
That is an escalation chain, not an over-broad read — and it is the third
time this platform has met the shape: #729 and #760 both found an
identity added so it could READ that could also WRITE. EPS A3 forbids it
directly: only the patient may INCREASE access, and lifting a spärr
increases access.

Hence the design under test:

  - the refusal of non-safe methods lives in ONE decorator, not per
    route, because per-route is how one gets missed;
  - named reserved actions refuse categorically as well, so a future
    scope widening cannot silently un-refuse them;
  - the single write a relative may perform anywhere in ips is ending
    their OWN grant (A3 clause 4), behind its own narrow decorator that
    never sets `g.patient_guid`.

The control that matters most here is the one that asserts a POST is
refused WHILE A VALID GRANT IS ACTIVE. A test that refuses an ungranted
relative's POST proves nothing about the method gate, because the grant
check would refuse it anyway.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.audit_log import AuditLog
from app.models.base import db as _db, utcnow
from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex
from app.models.patient_proxy_grant import (
    PatientProxyGrant, SCOPE_READ_AS_PATIENT, SCOPE_SEPARATE_CHANNEL,
    ENDED_BY_PATIENT, ENDED_BY_PROXY,
)
from app.services import care_access_policy as cap

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


def _mk_patient(db, family="Fullmaktsson"):
    fhir = FhirResource(resource_type="Patient", resource_id=str(uuid.uuid4()),
                        resource_json={"resourceType": "Patient"})
    db.session.add(fhir)
    db.session.flush()
    p = PatientIndex(fhir_resource_guid=fhir.guid,
                     resource_id=str(uuid.uuid4()),
                     family_name=family, given_name="Test")
    db.session.add(p)
    db.session.flush()
    return p


@pytest.fixture
def seed(client, db):
    patient = _mk_patient(db)
    other = _mk_patient(db, family="Annanson")
    clinic = Clinic(name="889 Clinic", organisation_guid=str(uuid.uuid4()),
                    is_active=True)
    db.session.add(clinic)
    db.session.commit()
    return {
        "patient": patient,
        "other": other,
        "clinic": clinic,
        "proxy": uuid.uuid4(),      # the relative's sso users.guid
        "stranger": uuid.uuid4(),
    }


def _grant(db, seed, *, proxy=None, patient=None,
           valid_from=None, valid_to=None, revoked=False):
    g = PatientProxyGrant(
        patient_guid=(patient or seed["patient"]).guid,
        proxy_user_guid=(proxy or seed["proxy"]),
        scope=SCOPE_READ_AS_PATIENT,
        valid_from=valid_from or (utcnow() - timedelta(days=1)),
        valid_to=valid_to,
    )
    if revoked:
        g.revoked_at = utcnow()
        g.revoked_by_role = ENDED_BY_PATIENT
    db.session.add(g)
    db.session.commit()
    return g


def _block_for(db, patient, clinic_guid=None):
    """A spärr row belonging to one patient, so a read can be checked by
    WHOSE rows came back rather than by a guid echoed in the envelope."""
    from app.models.patient_block import PatientBlock
    b = PatientBlock(
        patient_guid=patient.guid,
        source_scope_type="clinic",
        source_scope_id=clinic_guid or uuid.uuid4(),
    )
    db.session.add(b)
    db.session.commit()
    return b


def _as_proxy(seed, proxy=None):
    return {"X-Dev-Proxy-User-Guid": str(proxy or seed["proxy"])}


def _as_patient(seed, patient=None):
    return {"X-Dev-Patient-Guid": str((patient or seed["patient"]).guid)}


# =====================================================================
# 1. The policy function — pure, no DB
# =====================================================================

class _FakeGrant:
    def __init__(self, patient_guid, proxy_user_guid, active=True):
        self.patient_guid = patient_guid
        self.proxy_user_guid = proxy_user_guid
        self._active = active

    def is_active(self, at=None):
        return self._active


class TestPolicy:
    def test_an_active_grant_allows_a_read(self):
        p, x = uuid.uuid4(), uuid.uuid4()
        allowed, basis, reason = cap.evaluate_proxy_access(
            patient_guid=p, proxy_user_guid=x,
            grants=[_FakeGrant(p, x, active=True)], method="GET",
        )
        assert allowed is True
        assert basis == cap.BASIS_PATIENT_PROXY
        assert reason is None

    def test_an_UNGRANTED_relative_is_refused(self):
        """#889's named deliverable."""
        allowed, basis, reason = cap.evaluate_proxy_access(
            patient_guid=uuid.uuid4(), proxy_user_guid=uuid.uuid4(),
            grants=[], method="GET",
        )
        assert allowed is False
        assert basis is None
        assert reason == cap.REASON_NO_PROXY_GRANT

    def test_a_grant_for_a_DIFFERENT_patient_does_not_carry_over(self):
        x = uuid.uuid4()
        allowed, _, reason = cap.evaluate_proxy_access(
            patient_guid=uuid.uuid4(), proxy_user_guid=x,
            grants=[_FakeGrant(uuid.uuid4(), x, active=True)], method="GET",
        )
        assert allowed is False
        assert reason == cap.REASON_NO_PROXY_GRANT

    def test_an_inactive_grant_is_refused_and_says_so_distinctly(self):
        """Two codes, because the AUDIT wants to tell 'never granted'
        from 'no longer granted'. The HTTP layer must not."""
        p, x = uuid.uuid4(), uuid.uuid4()
        allowed, _, reason = cap.evaluate_proxy_access(
            patient_guid=p, proxy_user_guid=x,
            grants=[_FakeGrant(p, x, active=False)], method="GET",
        )
        assert allowed is False
        assert reason == cap.REASON_PROXY_GRANT_INACTIVE
        assert cap.REASON_PROXY_GRANT_INACTIVE != cap.REASON_NO_PROXY_GRANT

    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
    def test_a_write_is_refused_WITH_AN_ACTIVE_GRANT(self, method):
        """THE control of this file.

        An ungranted relative's POST would be refused by the grant check,
        so refusing that proves nothing about the method gate. This holds
        the grant valid and still demands a refusal.
        """
        p, x = uuid.uuid4(), uuid.uuid4()
        grants = [_FakeGrant(p, x, active=True)]
        # same inputs, GET -> allowed. Establishes that the only
        # difference below is the method.
        assert cap.evaluate_proxy_access(
            patient_guid=p, proxy_user_guid=x, grants=grants, method="GET",
        )[0] is True
        allowed, basis, reason = cap.evaluate_proxy_access(
            patient_guid=p, proxy_user_guid=x, grants=grants, method=method,
        )
        assert allowed is False
        assert basis is None
        assert reason == cap.REASON_PROXY_WRITE_REFUSED

    @pytest.mark.parametrize("action", sorted(cap.PROXY_RESERVED_ACTIONS))
    def test_a_reserved_action_is_refused_even_on_a_safe_method(self, action):
        """Belt and braces: should a future scope ever grant a proxy a
        write, these must still refuse, so the refusal cannot be lost by
        widening a scope."""
        p, x = uuid.uuid4(), uuid.uuid4()
        allowed, _, reason = cap.evaluate_proxy_access(
            patient_guid=p, proxy_user_guid=x,
            grants=[_FakeGrant(p, x, active=True)],
            method="GET", action=action,
        )
        assert allowed is False
        assert reason == cap.REASON_PROXY_ACTION_RESERVED

    def test_block_lift_is_among_the_reserved_actions(self):
        """Named explicitly, because it is the escalation that motivated
        the whole gate: lift the spärr, then read what it hid."""
        assert "block_lift" in cap.PROXY_RESERVED_ACTIONS

    @pytest.mark.parametrize("missing", ["patient", "proxy"])
    def test_missing_input_falls_to_the_safe_value(self, missing):
        p = None if missing == "patient" else uuid.uuid4()
        x = None if missing == "proxy" else uuid.uuid4()
        allowed, _, reason = cap.evaluate_proxy_access(
            patient_guid=p, proxy_user_guid=x, grants=[], method="GET",
        )
        assert allowed is False
        assert reason == cap.REASON_NO_PROXY_GRANT

    def test_the_basis_is_its_own_value_not_a_reuse(self):
        """#889: 'its own basis value (not a reuse of same_unit /
        same_org / emergency)'."""
        assert cap.BASIS_PATIENT_PROXY not in {
            cap.BASIS_SAME_UNIT, cap.BASIS_SAME_ORG,
            cap.BASIS_CROSS_ORG_CONSENT, cap.BASIS_EMERGENCY,
        }

    def test_the_care_zone_rule_is_untouched(self):
        """The additive rule: adding an axis must not move an existing
        answer. Zone 1 is still allowed on same_unit with a block present."""
        unit = uuid.uuid4()
        allowed, zone, basis, reason = cap.evaluate_care_access(
            reader_care_unit_guid=unit,
            reader_care_organisation_guid=uuid.uuid4(),
            author_clinic_guid=unit,
            author_caregiver_guid=uuid.uuid4(),
            active_blocks=[],
            has_sharing_consent=False,
        )
        assert (allowed, zone, basis, reason) == (
            True, 1, cap.BASIS_SAME_UNIT, None
        )


class TestMutationRule:
    """EPS A3: both parties may REDUCE; only the patient may INCREASE."""

    @pytest.mark.parametrize("mutation", ["create", "widen"])
    def test_only_the_patient_may_increase(self, mutation):
        assert cap.proxy_mutation_allowed(
            actor_role="patient", mutation=mutation) is True
        assert cap.proxy_mutation_allowed(
            actor_role="proxy", mutation=mutation) is False

    def test_both_parties_may_revoke(self):
        assert cap.proxy_mutation_allowed(
            actor_role="patient", mutation="revoke") is True
        assert cap.proxy_mutation_allowed(
            actor_role="proxy", mutation="revoke") is True

    def test_an_unknown_actor_or_mutation_is_refused(self):
        assert cap.proxy_mutation_allowed(
            actor_role="professional", mutation="revoke") is False
        assert cap.proxy_mutation_allowed(
            actor_role="patient", mutation="delete_everything") is False


# =====================================================================
# 2. The model — the validity interval, both ends
# =====================================================================

class TestValidityInterval:
    def test_an_open_ended_grant_is_active(self, db, seed):
        g = _grant(db, seed)
        assert g.is_active() is True

    def test_a_grant_whose_valid_from_is_in_the_FUTURE_is_not_active_yet(
            self, db, seed):
        """The reason the interval carries both ends. `expires_at` alone
        cannot express 'while I am in hospital next month'."""
        g = _grant(db, seed, valid_from=utcnow() + timedelta(days=7))
        assert g.is_active() is False

    def test_an_expired_grant_is_not_active(self, db, seed):
        g = _grant(db, seed,
                   valid_from=utcnow() - timedelta(days=10),
                   valid_to=utcnow() - timedelta(days=1))
        assert g.is_active() is False

    def test_a_revoked_grant_is_not_active_even_inside_its_interval(
            self, db, seed):
        g = _grant(db, seed, valid_to=utcnow() + timedelta(days=30),
                   revoked=True)
        assert g.is_active() is False

    def test_is_active_accepts_an_explicit_as_at(self, db, seed):
        g = _grant(db, seed,
                   valid_from=utcnow() - timedelta(days=10),
                   valid_to=utcnow() - timedelta(days=5))
        assert g.is_active(at=utcnow() - timedelta(days=7)) is True
        assert g.is_active(at=utcnow()) is False

    def test_a_naive_as_at_does_not_blow_up(self, db, seed):
        """SQLite stores no timezone, so a naive datetime reaches
        is_active in tests. Mixing naive and aware does not merely break
        an assertion, it corrupts the comparison."""
        g = _grant(db, seed)
        assert g.is_active(at=datetime.utcnow()) is True

    def test_the_upper_bound_is_exclusive(self, db, seed):
        end = utcnow() + timedelta(days=1)
        g = _grant(db, seed, valid_to=end)
        assert g.is_active(at=end) is False

    def test_to_dict_is_json_serialisable(self, db, seed):
        import json
        g = _grant(db, seed)
        json.dumps(g.to_dict())   # raises if a UUID leaked through


# =====================================================================
# 3. The wiring — #901's lesson: a chain nobody walks is inert
# =====================================================================

READ_ROUTES = ["/api/v1/patient/blocks", "/api/v1/patient/consents"]


class TestReadAsPatient:
    @pytest.mark.parametrize("route", READ_ROUTES)
    def test_the_patient_still_reads_their_own_record(
            self, client, db, seed, route):
        """The no-op half. Admitting a proxy must change nothing for the
        patient."""
        r = client.get(route, headers=_as_patient(seed))
        assert r.status_code == 200, r.get_data(as_text=True)

    @pytest.mark.parametrize("route", READ_ROUTES)
    def test_an_UNGRANTED_relative_is_refused(self, client, db, seed, route):
        """#889's named deliverable, at the HTTP boundary."""
        r = client.get(route, headers={
            **_as_proxy(seed),
            "X-Acting-For-Patient": str(seed["patient"].guid),
        })
        assert r.status_code == 403, r.get_data(as_text=True)

    def test_a_GRANTED_relative_reads_the_patients_record(
            self, client, db, seed):
        """Checked by WHOSE rows came back.

        An earlier version of this test asserted a `patient_guid` in the
        response envelope. The list routes do not emit one, and even if
        they did, echoing the requested guid proves only that the server
        read the header. Seeding a row for the subject AND one for a
        different patient makes the claim falsifiable in both
        directions.
        """
        mine = _block_for(db, seed["patient"])
        theirs = _block_for(db, seed["other"])
        _grant(db, seed)
        r = client.get(READ_ROUTES[0], headers={
            **_as_proxy(seed),
            "X-Acting-For-Patient": str(seed["patient"].guid),
        })
        assert r.status_code == 200, r.get_data(as_text=True)
        guids = {row["guid"] for row in r.get_json()["items"]}
        assert str(mine.guid) in guids
        assert str(theirs.guid) not in guids

    @pytest.mark.parametrize("route", READ_ROUTES)
    def test_a_granted_relative_is_admitted_on_every_wired_read_route(
            self, client, db, seed, route):
        _grant(db, seed)
        r = client.get(route, headers={
            **_as_proxy(seed),
            "X-Acting-For-Patient": str(seed["patient"].guid),
        })
        assert r.status_code == 200, r.get_data(as_text=True)

    def test_a_grant_for_one_patient_does_not_open_another(
            self, client, db, seed):
        _grant(db, seed)   # for seed['patient']
        r = client.get(READ_ROUTES[0], headers={
            **_as_proxy(seed),
            "X-Acting-For-Patient": str(seed["other"].guid),
        })
        assert r.status_code == 403

    def test_a_sole_active_grant_defaults_the_subject(self, client, db, seed):
        """Mirrors sso's own 'sole affiliation' rule: default when there
        is no ambiguity."""
        mine = _block_for(db, seed["patient"])
        _grant(db, seed)
        r = client.get(READ_ROUTES[0], headers=_as_proxy(seed))
        assert r.status_code == 200, r.get_data(as_text=True)
        assert str(mine.guid) in {
            row["guid"] for row in r.get_json()["items"]
        }

    def test_two_active_grants_require_the_header(self, client, db, seed):
        _grant(db, seed)
        _grant(db, seed, patient=seed["other"])
        r = client.get(READ_ROUTES[0], headers=_as_proxy(seed))
        assert r.status_code == 400
        # ips's _auth_error returns a FHIR OperationOutcome, not
        # {"error": ...} — the route helpers' shape is different from the
        # auth layer's.
        diagnostics = r.get_json()["issue"][0]["diagnostics"]
        assert "X-Acting-For-Patient" in diagnostics

    def test_revoking_the_grant_closes_the_read_on_the_NEXT_request(
            self, client, db, seed):
        """#890's load-bearing property: the grant is resolved from the
        database per request, never baked into a token. So revocation
        needs no logout and no invalidation."""
        g = _grant(db, seed)
        hdrs = {**_as_proxy(seed),
                "X-Acting-For-Patient": str(seed["patient"].guid)}
        assert client.get(READ_ROUTES[0], headers=hdrs).status_code == 200

        g.revoked_at = utcnow()
        g.revoked_by_role = ENDED_BY_PATIENT
        db.session.commit()

        assert client.get(READ_ROUTES[0], headers=hdrs).status_code == 403

    def test_a_future_grant_does_not_open_the_read_yet(self, client, db, seed):
        _grant(db, seed, valid_from=utcnow() + timedelta(days=7))
        r = client.get(READ_ROUTES[0], headers={
            **_as_proxy(seed),
            "X-Acting-For-Patient": str(seed["patient"].guid),
        })
        assert r.status_code == 403

    def test_both_denial_codes_produce_the_SAME_response_body(
            self, client, db, seed):
        """Telling a caller 'there was a grant but it is revoked' would
        confirm that this patient once named this person."""
        hdrs = {**_as_proxy(seed),
                "X-Acting-For-Patient": str(seed["patient"].guid)}
        never = client.get(READ_ROUTES[0], headers=hdrs)

        g = _grant(db, seed)
        g.revoked_at = utcnow()
        db.session.commit()
        revoked = client.get(READ_ROUTES[0], headers=hdrs)

        assert never.status_code == revoked.status_code == 403
        assert never.get_json() == revoked.get_json()


class TestProxyCannotWrite:
    """The escalation chain, closed at the HTTP boundary."""

    def test_a_granted_proxy_cannot_CREATE_a_block(self, client, db, seed):
        _grant(db, seed)
        r = client.post("/api/v1/patient/blocks", headers={
            **_as_proxy(seed),
            "X-Acting-For-Patient": str(seed["patient"].guid),
        }, json={"scope_type": "clinic",
                 "scope_id": str(seed["clinic"].guid)})
        # Refused. 401 rather than 403 is a DEV-MODE artefact: the create
        # route is still @require_patient, whose AUTH_DISABLED branch
        # demands X-Dev-Patient-Guid and never looks at a blob. The
        # production shape is asserted separately below.
        assert r.status_code in (401, 403, 405), r.get_data(as_text=True)

    def test_a_granted_proxy_cannot_reach_the_block_LIFT_route(
            self, client, db, seed):
        """The specific escalation: lift the spärr, then read what it
        had been hiding."""
        _grant(db, seed)
        r = client.post(
            f"/api/v1/patient/blocks/{uuid.uuid4()}/lift",
            headers={**_as_proxy(seed),
                     "X-Acting-For-Patient": str(seed["patient"].guid)},
            json={},
        )
        # The lift route is still @require_patient, so a relative blob
        # is refused there outright — belt (the route) and braces (the
        # decorator's method gate, asserted in TestPolicy).
        assert r.status_code in (401, 403), r.get_data(as_text=True)

    def test_a_granted_proxy_cannot_revoke_a_CONSENT(self, client, db, seed):
        _grant(db, seed)
        r = client.post(
            f"/api/v1/patient/consents/{uuid.uuid4()}/revoke",
            headers={**_as_proxy(seed),
                     "X-Acting-For-Patient": str(seed["patient"].guid)},
            json={},
        )
        assert r.status_code in (401, 403)

    def test_PRODUCTION_shape_a_relative_blob_is_403_on_require_patient(
            self, client, db, seed):
        """The promise made by the comment above, kept.

        Every other test here runs through AUTH_DISABLED's dev headers,
        where `require_patient` never looks at a blob — so none of them
        exercises the production refusal. This one turns the dev branch
        OFF and feeds a real relative blob through `resolve_sso_user`,
        which is the only way to see the code production would return.
        """
        from unittest.mock import patch
        app = client.application
        blob = {"user_type": "relative", "user_guid": str(seed["proxy"])}
        _grant(db, seed)
        with patch.dict(app.config, {"AUTH_DISABLED": False}), \
                patch("app.services.auth_service.resolve_sso_user",
                      return_value=blob):
            r = client.post(
                "/api/v1/patient/blocks",
                headers={"Authorization": "Bearer t"},
                json={"scope_type": "clinic",
                      "scope_id": str(seed["clinic"].guid)},
            )
        assert r.status_code == 403, r.get_data(as_text=True)

    def test_PRODUCTION_shape_a_relative_blob_READS_through_the_new_gate(
            self, client, db, seed):
        """The other half: the same blob, on a wired read route, through
        the production path. Without this the test above could pass
        because a relative blob is refused EVERYWHERE, which would mean
        the feature does not work at all."""
        from unittest.mock import patch
        app = client.application
        blob = {"user_type": "relative", "user_guid": str(seed["proxy"])}
        _grant(db, seed)
        with patch.dict(app.config, {"AUTH_DISABLED": False}), \
                patch("app.services.auth_service.resolve_sso_user",
                      return_value=blob):
            r = client.get(
                READ_ROUTES[0],
                headers={"Authorization": "Bearer t",
                         "X-Acting-For-Patient": str(seed["patient"].guid)},
            )
        assert r.status_code == 200, r.get_data(as_text=True)

    def test_a_granted_proxy_cannot_list_the_patients_OTHER_grants(
            self, client, db, seed):
        """Who else has access to this record is the patient's own
        business, so the grant list stays patient-only."""
        _grant(db, seed)
        r = client.get("/api/v1/patient/proxy-grants", headers={
            **_as_proxy(seed),
            "X-Acting-For-Patient": str(seed["patient"].guid),
        })
        assert r.status_code in (401, 403)


# =====================================================================
# 4. Managing the grant
# =====================================================================

class TestGrantManagement:
    def test_the_patient_creates_lists_and_revokes(self, client, db, seed):
        proxy = str(uuid.uuid4())
        r = client.post("/api/v1/patient/proxy-grants",
                        headers=_as_patient(seed),
                        json={"proxy_user_guid": proxy,
                              "proxy_label": "min dotter Anna"})
        assert r.status_code == 201, r.get_data(as_text=True)
        guid = r.get_json()["guid"]
        assert r.get_json()["is_active"] is True

        r = client.get("/api/v1/patient/proxy-grants",
                       headers=_as_patient(seed))
        assert r.status_code == 200
        assert r.get_json()["count"] == 1

        r = client.post(f"/api/v1/patient/proxy-grants/{guid}/revoke",
                        headers=_as_patient(seed), json={"reason": "klart"})
        assert r.status_code == 200
        body = r.get_json()
        assert body["is_active"] is False
        assert body["revoked_by_role"] == ENDED_BY_PATIENT

    def test_a_second_active_grant_to_the_same_person_is_refused(
            self, client, db, seed):
        proxy = str(uuid.uuid4())
        h = _as_patient(seed)
        assert client.post("/api/v1/patient/proxy-grants", headers=h,
                           json={"proxy_user_guid": proxy}
                           ).status_code == 201
        r = client.post("/api/v1/patient/proxy-grants", headers=h,
                        json={"proxy_user_guid": proxy})
        assert r.status_code == 409

    def test_revoking_then_granting_again_WORKS(self, client, db, seed):
        """#891's lesson: ending a relationship is history, not a
        terminal state. A database UNIQUE over the pair would have made
        this impossible for ever."""
        proxy = str(uuid.uuid4())
        h = _as_patient(seed)
        first = client.post("/api/v1/patient/proxy-grants", headers=h,
                            json={"proxy_user_guid": proxy}).get_json()
        client.post(
            f"/api/v1/patient/proxy-grants/{first['guid']}/revoke",
            headers=h, json={})
        r = client.post("/api/v1/patient/proxy-grants", headers=h,
                        json={"proxy_user_guid": proxy})
        assert r.status_code == 201, r.get_data(as_text=True)
        assert r.get_json()["guid"] != first["guid"]

    def test_an_impossible_interval_is_refused(self, client, db, seed):
        r = client.post("/api/v1/patient/proxy-grants",
                        headers=_as_patient(seed),
                        json={"proxy_user_guid": str(uuid.uuid4()),
                              "valid_from": "2026-12-01T00:00:00Z",
                              "valid_to": "2026-11-01T00:00:00Z"})
        assert r.status_code == 400
        assert "valid_to" in r.get_json()["error"]

    def test_an_unknown_scope_is_refused_and_names_the_allowed_ones(
            self, client, db, seed):
        r = client.post("/api/v1/patient/proxy-grants",
                        headers=_as_patient(seed),
                        json={"proxy_user_guid": str(uuid.uuid4()),
                              "scope": "everything"})
        assert r.status_code == 400
        assert SCOPE_READ_AS_PATIENT in r.get_json()["allowed_scopes"]

    def test_the_separate_channel_scope_is_accepted_for_a3_clause_2(
            self, client, db, seed):
        """A3's second clause (a coming app) is accepted now so the
        column does not change when that app arrives."""
        r = client.post("/api/v1/patient/proxy-grants",
                        headers=_as_patient(seed),
                        json={"proxy_user_guid": str(uuid.uuid4()),
                              "scope": SCOPE_SEPARATE_CHANNEL})
        assert r.status_code == 201

    def test_another_patients_grant_is_ABSENT_not_refused(
            self, client, db, seed):
        g = _grant(db, seed, patient=seed["other"])
        r = client.post(f"/api/v1/patient/proxy-grants/{g.guid}/revoke",
                        headers=_as_patient(seed), json={})
        assert r.status_code == 404


class TestProxyEndsOwnAccess:
    """EPS A3 clause 4 — the only write a relative may make in ips."""

    def test_the_proxy_may_revoke_their_own_grant(self, client, db, seed):
        g = _grant(db, seed)
        r = client.post(
            f"/api/v1/patient/proxy-grants/mine/{g.guid}/revoke",
            headers=_as_proxy(seed), json={"reason": "vill inte längre"})
        assert r.status_code == 200, r.get_data(as_text=True)
        body = r.get_json()
        assert body["is_active"] is False
        assert body["revoked_by_role"] == ENDED_BY_PROXY

    def test_and_the_read_closes_immediately_afterwards(
            self, client, db, seed):
        g = _grant(db, seed)
        hdrs = {**_as_proxy(seed),
                "X-Acting-For-Patient": str(seed["patient"].guid)}
        assert client.get(READ_ROUTES[0], headers=hdrs).status_code == 200
        client.post(f"/api/v1/patient/proxy-grants/mine/{g.guid}/revoke",
                    headers=_as_proxy(seed), json={})
        assert client.get(READ_ROUTES[0], headers=hdrs).status_code == 403

    def test_a_proxy_cannot_revoke_SOMEONE_ELSES_grant(self, client, db, seed):
        g = _grant(db, seed)
        r = client.post(
            f"/api/v1/patient/proxy-grants/mine/{g.guid}/revoke",
            headers=_as_proxy(seed, proxy=seed["stranger"]), json={})
        assert r.status_code == 404

    def test_a_patient_cannot_use_the_proxy_self_route(self, client, db, seed):
        g = _grant(db, seed)
        r = client.post(
            f"/api/v1/patient/proxy-grants/mine/{g.guid}/revoke",
            headers=_as_patient(seed), json={})
        assert r.status_code in (401, 403)

    def test_the_self_route_never_sets_a_patient_context(
            self, client, db, seed):
        """require_proxy_self sets g.proxy_user_guid and nothing else, so
        a route behind it cannot accidentally read the patient surface."""
        from flask import g as flask_g
        from app.services.auth_service import require_proxy_self
        app = client.application
        seen = {}

        @require_proxy_self
        def _probe():
            seen["patient_guid"] = getattr(flask_g, "patient_guid", "unset")
            seen["proxy"] = getattr(flask_g, "proxy_user_guid", None)
            return "ok"

        with app.test_request_context(
                "/x", headers=_as_proxy(seed), method="POST"):
            _probe()
        assert seen["patient_guid"] is None
        assert seen["proxy"] == str(seed["proxy"])


# =====================================================================
# 5. Audit — the actor is the relative, the subject is the patient
# =====================================================================

class TestAudit:
    def test_a_proxy_read_is_audited_with_actor_and_subject_apart(
            self, client, db, seed):
        """Lag (2022:913) chain of custody. An audit keyed only on
        patient_guid cannot tell a relative's read from the patient's."""
        _grant(db, seed)
        client.get(READ_ROUTES[0], headers={
            **_as_proxy(seed),
            "X-Acting-For-Patient": str(seed["patient"].guid),
        })
        rows = AuditLog.query.filter_by(event_type="proxy_access_granted").all()
        assert len(rows) == 1
        row = rows[0]
        assert row.actor_type == "proxy"
        assert str(row.actor_guid) == str(seed["proxy"])
        assert str(row.patient_guid) == str(seed["patient"].guid)
        assert str(row.actor_guid) != str(row.patient_guid)

    def test_the_audit_row_SURVIVES_a_GET(self, client, db, seed):
        """The trap this platform has hit before: every other audit
        helper here does add+flush and lets the route's commit carry the
        row. A GET commits nothing, so a flushed row is rolled back —
        visible in a fixture that shares the session, gone in
        production. This asserts it is committed, by reading it back
        from a FRESH session."""
        _grant(db, seed)
        client.get(READ_ROUTES[0], headers={
            **_as_proxy(seed),
            "X-Acting-For-Patient": str(seed["patient"].guid),
        })
        db.session.rollback()      # discard anything merely flushed
        rows = AuditLog.query.filter_by(event_type="proxy_access_granted").all()
        assert len(rows) == 1, "the audit row did not survive the GET"

    def test_a_refusal_is_audited_with_its_precise_reason(
            self, client, db, seed):
        """The response hides which denial it was; the audit must not."""
        g = _grant(db, seed)
        g.revoked_at = utcnow()
        db.session.commit()
        client.get(READ_ROUTES[0], headers={
            **_as_proxy(seed),
            "X-Acting-For-Patient": str(seed["patient"].guid),
        })
        db.session.rollback()
        rows = AuditLog.query.filter_by(event_type="proxy_access_refused").all()
        assert len(rows) == 1
        assert rows[0].detail["reason"] == cap.REASON_PROXY_GRANT_INACTIVE

    def test_creating_a_grant_is_audited_as_the_patient(
            self, client, db, seed):
        client.post("/api/v1/patient/proxy-grants",
                    headers=_as_patient(seed),
                    json={"proxy_user_guid": str(uuid.uuid4())})
        rows = AuditLog.query.filter_by(event_type="proxy_grant_created").all()
        assert len(rows) == 1
        assert rows[0].actor_type == "patient"
