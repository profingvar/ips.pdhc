"""#921 — a machine must not be audited as a person.

The defect, measured in production on the first real implant push:

    event_type              | actor_type | actor_label | actor_guid
    implant_assertions_push | user       | alert.pdhc  | NULL

`_service_account_user` builds a TRANSIENT `User` for a key-only caller,
which is the right shape for AUTHORISATION — it is `is_superuser=False` and
carries no privileges. But `log_event` classified the actor by PRESENCE
(`"user" if actor else "system"`), and a service account is not None. So:

  - machine traffic was indistinguishable from a person's in the one place
    Rule 24's full operation log exists to answer that, and
  - because the transient User is never persisted it has no guid, the row
    read `actor_type='user'` with `actor_guid=NULL` — a combination that
    should not be reachable for a real user.

Both halves are fixed: `actor_type='service'`, and `actor_guid` carries the
`api_keys` guid, which is what an incident responder would actually look up.

ONE TEST GOES THROUGH THE REAL ROUTE, which needed `AUTH_DISABLED` flipped
off for that test — the testing config sets it True, so `require_auth`
returns before it ever sets `g.api_key`, and a test that left it on would be
asserting on a context the production path never builds. The rest exercise
`log_event` directly with `g` set exactly as `require_auth` sets it, and say
so rather than implying more coverage than they have.
"""
import uuid

import pytest

from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.base import db as _db
from app.models.user import User
from app.services import audit_service
from app.services.audit_service import (ACTOR_SERVICE, ACTOR_SYSTEM,
                                        ACTOR_TYPES, ACTOR_USER, log_event)
from app.services.auth_service import (SERVICE_ACCOUNT_ROLE, hash_api_key,
                                       _service_account_user)


def _key(db, *, label="alert.pdhc", scopes=("implants:write",)):
    raw = f"testkey-{uuid.uuid4()}"
    k = ApiKey(user_guid=None, key_hash=hash_api_key(raw), label=label,
               prefix=raw[:8], scopes=list(scopes))
    db.session.add(k)
    db.session.commit()
    return raw, k


class TestTheVocabulary:
    def test_service_is_a_named_value(self):
        assert ACTOR_SERVICE == "service"
        assert ACTOR_SERVICE in ACTOR_TYPES

    def test_the_five_kinds_are_listed_in_one_place(self):
        """Four values were literals across five files with nothing listing
        them, which is how a fifth kind came to have no value at all. The
        point of the tuple is that the sixth is added deliberately."""
        assert set(ACTOR_TYPES) == {"user", "system", "service",
                                    "patient", "proxy"}

    def test_the_role_name_is_shared_not_respelled(self):
        """`audit_service` imports it from `auth_service` rather than
        repeating the string, so the two agree by construction. A literal in
        two modules is a literal that drifts."""
        import inspect
        src = inspect.getsource(audit_service.log_event)
        assert "SERVICE_ACCOUNT_ROLE" in src
        assert '"service_account"' not in src


class TestLogEventDirectly:
    """`g` is set exactly as `require_auth` sets it. These do not prove the
    wiring — the route test below does that."""

    def test_a_service_account_is_audited_as_a_SERVICE(self, app, client, db):
        raw, key = _key(db)
        with app.test_request_context("/api/v1/x", method="POST"):
            from flask import g
            g.api_key = key
            g.current_user = _service_account_user(key)
            row = log_event("probe_921")
        assert row.actor_type == ACTOR_SERVICE

    def test_and_carries_the_API_KEY_guid_rather_than_NULL(self, app, client,
                                                           db):
        raw, key = _key(db)
        with app.test_request_context("/api/v1/x", method="POST"):
            from flask import g
            g.api_key = key
            g.current_user = _service_account_user(key)
            row = log_event("probe_921")
        assert row.actor_guid is not None, "this was the NULL in the defect"
        assert str(row.actor_guid) == str(key.guid)

    def test_the_label_still_names_the_consumer(self, app, client, db):
        """The label was already useful — it is the key's label — and the fix
        must not lose it while correcting the type."""
        raw, key = _key(db, label="alert.pdhc")
        with app.test_request_context("/api/v1/x"):
            from flask import g
            g.api_key = key
            g.current_user = _service_account_user(key)
            row = log_event("probe_921")
        assert row.actor_label == "alert.pdhc"

    def test_CONTROL_a_real_user_is_still_a_USER(self, app, client, db):
        u = User(username="someone@example.invalid", display_name="Someone",
                 role="professional", is_active=True)
        db.session.add(u)
        db.session.commit()
        with app.test_request_context("/api/v1/x"):
            from flask import g
            g.current_user = u
            row = log_event("probe_921")
        assert row.actor_type == ACTOR_USER
        assert str(row.actor_guid) == str(u.guid)

    def test_CONTROL_no_actor_is_still_SYSTEM(self, app, client, db):
        with app.test_request_context("/api/v1/x"):
            row = log_event("probe_921")
        assert row.actor_type == ACTOR_SYSTEM
        assert row.actor_guid is None
        assert row.actor_label == "system"

    def test_the_incoherent_combination_is_unreachable(self, app, client, db):
        """`actor_type='user'` with a NULL `actor_guid` is what the defect
        produced. A real user always has a guid, and a service is no longer
        labelled a user, so the pair should not occur."""
        raw, key = _key(db)
        rows = []
        with app.test_request_context("/api/v1/x"):
            from flask import g
            g.api_key = key
            g.current_user = _service_account_user(key)
            rows.append(log_event("probe_921_a"))
        with app.test_request_context("/api/v1/x"):
            rows.append(log_event("probe_921_b"))
        for r in rows:
            assert not (r.actor_type == ACTOR_USER and r.actor_guid is None)


class TestThroughTheRealRoute:
    def test_a_scoped_key_push_is_audited_as_a_service(self, app, client, db,
                                                       monkeypatch):
        """The dish, not the ingredient.

        `AUTH_DISABLED` is flipped off for this test only: the testing config
        sets it True, so `require_auth` returns before it sets `g.api_key`,
        and a test that left it on would assert on a context the production
        path never builds.

        One assertion for a patient ips does not know, so the row is REJECTED
        and nothing is created — the push is audited either way, which is what
        makes this safe to assert on.
        """
        monkeypatch.setitem(app.config, "AUTH_DISABLED", False)
        raw, key = _key(db)

        resp = client.post(
            "/api/v1/implants/assertions",
            headers={"Authorization": f"ApiKey {raw}"},
            json={"assertions": [{
                "patient_guid": str(uuid.uuid4()),
                "subgroup": "Förekomst av implantat",
                "code_system": "icd10",
                "code": "Z95.0",
                "national_term": "probe 921",
                "asserted_at": "2026-03-14T09:30:00+00:00",
                "negation": False,
                "provenance": "simulated",
            }]},
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body["created"] == [], "the probe must create nothing"

        row = (_db.session.query(AuditLog)
               .filter_by(event_type="implant_assertions_push")
               .order_by(AuditLog.created_at.desc()).first())
        assert row is not None, "the push was not audited at all"
        assert row.actor_type == ACTOR_SERVICE, (
            f"audited as {row.actor_type!r} — this is #921 in production")
        assert str(row.actor_guid) == str(key.guid)
        assert row.actor_label == "alert.pdhc"
        assert row.detail.get("api_key_prefix") == key.prefix
