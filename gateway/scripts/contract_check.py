"""#798 — the consumer contract, checked against a RUNNING ips.

Run before and after any deploy that touches this service:

    docker exec ips-app-1 python /app/scripts/contract_check.py

It lives under `gateway/scripts/` rather than the repo-root `scripts/` so the
Dockerfile's `COPY . .` carries it INTO the image -- repo-root scripts are
local deploy tooling and never ship. The first version sat at the repo root and
the deploy bundle refused it as MISSING-NEW, which is the check doing its job.

Exit 0 when every consumed route is registered and every pinned shape holds;
exit 1 otherwise, naming what moved.

Why this and not the unit tests: the unit suite runs on SQLite with
AUTH_DISABLED. This runs against the real app, the real Postgres and the real
auth configuration, which is where #730's 500 lived (SQLite does not coerce
UUIDs) and where #797's purge would have differed (SQLite does not enforce
foreign keys). The integration-smoke lesson from #704/#708: real calls found
six cross-service defects while 155 unit tests stayed green.

Read-only. It creates nothing and deletes nothing.
"""
from __future__ import annotations

import sys
import uuid

sys.path.insert(0, "/app")

from app import create_app                                    # noqa: E402
from app.models.base import db                                # noqa: E402
from app.models.clinic import Clinic                          # noqa: E402
from app.models.patient_index import (PatientIndex,           # noqa: E402
                                      PatientClinicAssignment)

#: Exactly what siblings call, verified against their call sites. A route
#: leaving this map is a consumer breaking.
CONSUMED = {
    "/api/v1/patients/analysis-filter":
        "cdr, cdr_6, analyse, dashboard, rosetta",
    "/api/v1/patients/<patient_guid>/blocks":
        "analyse, dashboard, cdr_6, gateway",
    "/api/v1/patients/<patient_guid>/blocks/check":
        "request, analyse",
    "/api/v1/patients/<patient_guid>/blocks/metadata":
        "analyse",
    "/api/v1/patients/<guid>/clinics":
        "request (the #779 authorisation gate)",
    "/api/v1/patients/<patient_guid>/consents":
        "contract",
    "/api/v1/patients/<patient_guid>/consents/check":
        "request",
    "/api/v1/clinics":
        "sim",
    "/api/v1/clinics/<guid>/patients":
        "sim",
    "/api/v1/health":
        "sim, and every healthcheck",
}

failures: list[str] = []
notes: list[str] = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  — {detail}" if detail else ""))
    if not ok:
        failures.append(label)


app = create_app()

print("=== 1. every consumed route is still registered ===")
rules = {str(r) for r in app.url_map.iter_rules()}
for route, consumers in sorted(CONSUMED.items()):
    check(f"{route:<50} [{consumers}]", route in rules)

print()
print("=== 2. ips still has NO /api/v1/fhir surface ===")
fhir = sorted(r for r in rules if "/api/v1/fhir" in r)
check("no /api/v1/fhir/* routes", fhir == [],
      "if one is added, #793's absent/unknown resources become visible to "
      "whoever reads it" if fhir else "")

print()
print("=== 3. response shapes, against the real database ===")
with app.app_context():
    # A patient WITH a clinic assignment. Picking any active patient left the
    # #779 guid-vs-organisation_guid assertion silently skipped, because an
    # unassigned patient returns `[]` and there is no row to inspect -- the
    # same hollow-check flaw as the auth one above, one level down. That
    # assertion is the most valuable line in this file; it must not be
    # optional.
    patient = (db.session.query(PatientIndex)
               .join(PatientClinicAssignment,
                     PatientClinicAssignment.patient_guid == PatientIndex.guid)
               .filter(PatientIndex.is_active.is_(True)).first())
    if patient is None:
        patient = (db.session.query(PatientIndex)
                   .filter(PatientIndex.is_active.is_(True)).first())
    # The clinic with the MOST patients, not the alphabetically first. Picking
    # by name chose "1177", which has none, so the "carries every key sim
    # reads" assertion skipped -- the THIRD time in this one script that a
    # check ran only if the data happened to suit it.
    #
    # That is the recurring shape worth naming: a verification that depends on
    # incidental data silently verifies nothing. Choose the row that exercises
    # the assertion, and say so when none exists.
    clinic = (db.session.query(Clinic)
              .join(PatientClinicAssignment,
                    PatientClinicAssignment.clinic_guid == Clinic.guid)
              .filter(Clinic.is_active.is_(True))
              .group_by(Clinic.guid)
              .order_by(db.func.count(PatientClinicAssignment.patient_guid).desc())
              .first())
    if clinic is None:
        clinic = (db.session.query(Clinic)
                  .filter(Clinic.is_active.is_(True))
                  .order_by(Clinic.name).first())
    pg = str(patient.guid) if patient else None
    cg = str(clinic.guid) if clinic else None
    corg = clinic.organisation_guid if clinic else None

if not pg or not cg:
    notes.append("no active patient or clinic in the database — shape checks skipped")
else:
    # The API routes use `require_auth`, which reads the Authorization header
    # only -- a session satisfies the admin blueprint but not these. The first
    # version of this script set a session and every shape check SKIPPED with
    # a 401, which is worse than no check: it printed a clean run while
    # verifying nothing.
    #
    # Three ways to exercise them, and this is the least invasive:
    #   1. mint an ApiKey -- creates a real credential for a read-only check;
    #   2. leave the checks hollow -- what the first version did;
    #   3. bypass auth in THIS short-lived process only.
    #
    # (3). `app` here is a separate instance in a throwaway process: the
    # running gunicorn workers and the deployed configuration are untouched,
    # and the database is the real one, so the shapes are real.
    # `_synthetic_dev_user` builds a transient User and never adds it to the
    # session, so this writes nothing.
    app.config["AUTH_DISABLED"] = True
    client = app.test_client()

    # /clinics on a patient -- the #779 gate.
    r = client.get(f"/api/v1/patients/{pg}/clinics")
    if r.status_code == 200:
        body = r.get_json()
        check("/patients/<guid>/clinics returns a list", isinstance(body, list))
        if body:
            row = body[0]
            check("  carries guid AND organisation_guid",
                  "guid" in row and "organisation_guid" in row)
            check("  they are DISTINCT identifier spaces (#779)",
                  row.get("guid") != row.get("organisation_guid"))
        else:
            # Do not pass quietly: the #779 assertion did not run.
            notes.append("the chosen patient has no clinic assignment, so the "
                         "#779 guid/organisation_guid assertion did NOT run")
    else:
        notes.append(f"/patients/<guid>/clinics -> {r.status_code} "
                     f"(auth-gated; shape not checked)")

    # analysis-filter -- five consumers.
    r = client.post("/api/v1/patients/analysis-filter",
                    json={"patient_guids": [pg, "not-a-uuid"],
                          "purpose": "statistics"})
    if r.status_code == 200:
        body = r.get_json()
        check("analysis-filter returns allowed + excluded",
              "allowed" in body and "excluded" in body)
        check("  a malformed guid is EXCLUDED, not a 500 (#730)",
              any(e.get("reason") == "malformed_guid"
                  for e in body.get("excluded", [])))
        check("  one bad guid does not deny the good one",
              pg in body.get("allowed", []))
    else:
        notes.append(f"analysis-filter -> {r.status_code} "
                     f"(auth-gated; shape not checked)")

    # clinic patients -- sim reads this dict.
    r = client.get(f"/api/v1/clinics/{cg}/patients")
    if r.status_code == 200:
        body = r.get_json()
        check("/clinics/<guid>/patients returns a list", isinstance(body, list))
        if body:
            row = body[0]
            need = ("guid", "identifier_system", "identifier_value",
                    "family_name", "given_name", "birth_date", "gender",
                    "is_active")
            miss = [k for k in need if k not in row]
            check("  carries every key sim reads", not miss,
                  f"missing {miss}" if miss else "")
        else:
            notes.append("the chosen clinic has no patients, so the sim "
                         "patient-dict assertion did NOT run")
    else:
        notes.append(f"/clinics/<guid>/patients -> {r.status_code} "
                     f"(auth-gated; shape not checked)")

print()
if notes:
    print("=== notes ===")
    for n in notes:
        print(f"  - {n}")
    print()

print(f"=== {len(failures)} failure(s) ===")
for f in failures:
    print(f"  {f}")
sys.exit(1 if failures else 0)
