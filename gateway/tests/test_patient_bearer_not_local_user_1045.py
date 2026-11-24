"""#1045 (internal security review): a PATIENT's SSO bearer never resolves
to an eps `users` row.

`_local_user_for` maps an SSO blob to the local eps `users` row whose
username is the blob's email, and `require_auth` then acts with that row's
rights (role, is_superuser) on every API route it guards. It did so for ANY
SSO user type. A patient chooses their own email on the invite page; if it
equals an eps username that no SSO professional holds (a hand-made row, a
professional since removed from SSO), that patient's bearer became that eps
user here: list and create clinics, read rosters, and as an is_superuser row
everything.

Only a professional's or an SU's bearer may be a local eps user; a patient
uses the patient-portal doors (`require_patient`), which never read this
table. Real routes, real decorators; only the SSO call is patched.
"""
from unittest.mock import patch

import pytest

from app.models.user import User

EMAIL = "staff.1045@example.test"


@pytest.fixture
def staff_row(db):
    u = User(username=EMAIL, email=EMAIL, display_name="Staff 1045",
             role="admin", is_active=True, is_superuser=True)
    db.session.add(u)
    db.session.commit()
    return u


def _get(client, blob, path="/api/v1/clinics"):
    with patch.dict(client.application.config, {"AUTH_DISABLED": False}), \
            patch("app.services.auth_service.resolve_sso_user", return_value=blob):
        return client.get(path, headers={"Authorization": "Bearer t"})


def _blob(user_type, **extra):
    b = {"email": EMAIL, "user_guid": "6f1c2d3e-0000-4000-8000-000000001045",
         "user_type": user_type, "must_change_password": False}
    b.update(extra)
    return b


def test_a_patient_bearer_with_a_staff_email_is_not_that_staff_user(client, staff_row):
    assert _get(client, _blob("patient")).status_code == 401


def test_a_patient_bearer_cannot_create_a_clinic_as_that_user(client, staff_row):
    with patch.dict(client.application.config, {"AUTH_DISABLED": False}), \
            patch("app.services.auth_service.resolve_sso_user",
                  return_value=_blob("patient")):
        r = client.post("/api/v1/clinics", json={"name": "Patient-made"},
                        headers={"Authorization": "Bearer t"})
    assert r.status_code == 401


def test_a_professional_bearer_still_resolves_to_its_row(client, staff_row):
    """Control: the same row, the same email, a professional's blob."""
    assert _get(client, _blob("professional")).status_code == 200
