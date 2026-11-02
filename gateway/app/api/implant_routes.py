"""The alert.pdhc implant transport, ips side — EPS B6b (#903).

#886 built the TRANSFORMATION from an alert.pdhc implant assertion to
FHIR Device + DeviceUsage and deliberately shipped no transport. This is
the transport's receiving half.

== Why a receiver and not a client ==

alert.pdhc runs nowhere: no container locally or on miserver, no
directory under `/usr/local/www`, no row in CLAUDE.md's service table.
#903 refused to write an HTTP CLIENT against it, because a client needs a
base URL and a module-level default would manufacture a
configured-looking service out of an unset variable — the xlate defect
(#833), where "nobody wired this up" became indistinguishable from "it
blipped" and a permanent condition was reported as retryable.

A RECEIVER has no such problem. It names no URL, invents no default, and
is inert until something calls it. So this half can be built and proved
now, and whether alert is ever deployed stays a separate decision that
blocks nothing.

The direction is alert's own: alert carries `IPS_BASE_URL` and
`IPS_API_KEY` in its config and never reads them (#892 found them as
config nothing consumes). It also fits the deployment reality — ips has a
public subdomain and alert has none, so a pull would need the loopback
form CLAUDE.md §7 spent a ticket removing.

== Idempotence without a new table ==

The natural key is
`(patient_guid, code_system, code, national_term, asserted_at)`.
Note that `(code_system, code)` alone is NOT a key: twelve codes in this
selection bind two or three national terms, which is the same fact that
put the term in `CodeableConcept.text` in #886.

Rather than a receipts table, the resource ids are DERIVED from that key
with UUIDv5. `alert_implants.to_fhir` already takes `device_id` and
`usage_id` as parameters — its docstring says ids are passed in "so the
caller controls identity" — so idempotence becomes a lookup on
`FhirResource.resource_id`, with no second source of truth to drift.

== A batch reports; it does not fail whole ==

`missing_contract_fields()` returns rather than raises precisely so a bad
row can be named without losing the good ones. A transport that 400s the
whole batch on one malformed row makes the producer retry the rows that
already succeeded.

== Three cautions carried from #886 ==

  - The Socialstyrelsen specification behind the implant selection is
    copyright-protected. Codes are read from alert's own rows; nothing
    here carries a copy of the table.
  - `asserted_at`, never `recorded_at`. The latter would date every
    implant to the day it was imported.
  - A SIMULATED assertion stays distinguishable from a documented one.
    `to_fhir` carries `provenance` into `meta.tag` on every path,
    including the negated one, and this module does not touch it.
"""

import uuid

from flask import Blueprint, g, jsonify, request

from app.models.base import db
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex
from app.services import alert_implants
from app.services.audit_service import log_event
from app.services.auth_service import (
    require_auth, require_scope, SCOPE_IMPLANTS_WRITE,
)
from app.services.fhir_service import create_resource

bp = Blueprint("implant_api", __name__, url_prefix="/api/v1/implants")

#: Namespace for the derived resource ids. A fixed, arbitrary UUID: its
#: only job is to keep these ids from colliding with any other UUIDv5
#: space. Never change it — doing so would make every previously pushed
#: assertion look new and duplicate the whole history.
ID_NAMESPACE = uuid.UUID("6f1b4d2e-7c93-4f58-9a21-0b8e5c4d3a17")

MAX_BATCH = 500


def _natural_key(a: dict) -> str:
    """The identity of one assertion, as a stable string.

    `national_term` is part of the key, not decoration: a code in this
    selection can bind more than one term, so two assertions sharing a
    code are not the same assertion.
    """
    return "|".join(str(a.get(f) or "") for f in (
        "patient_guid", "code_system", "code", "national_term",
        "asserted_at",
    ))


def _derived_ids(a: dict) -> tuple[str, str]:
    key = _natural_key(a)
    return (
        str(uuid.uuid5(ID_NAMESPACE, key + "|device")),
        str(uuid.uuid5(ID_NAMESPACE, key + "|usage")),
    )


def _existing(resource_id: str) -> FhirResource | None:
    return db.session.query(FhirResource).filter_by(
        resource_id=resource_id).first()


@bp.route("/assertions", methods=["POST"])
@require_auth
@require_scope(SCOPE_IMPLANTS_WRITE)
def push_assertions():
    """POST /api/v1/implants/assertions — accept a batch from alert.pdhc.

    Body: ``{"assertions": [ <assertion>, ... ]}`` where each assertion
    matches ``alert_implants.ASSERTION_CONTRACT``.

    Returns 200 with a per-row account even when some rows were refused,
    because a batch that 400s on one bad row makes the producer retry the
    rows that already landed. A malformed BODY — not a malformed row — is
    still a 400.
    """
    data = request.get_json(silent=True) or {}
    rows = data.get("assertions")
    if not isinstance(rows, list):
        return jsonify({"error": "assertions must be a list"}), 400
    if not rows:
        return jsonify({"accepted": 0, "duplicates": 0, "rejected": [],
                        "created": []}), 200
    if len(rows) > MAX_BATCH:
        return jsonify({
            "error": f"batch too large: {len(rows)} > {MAX_BATCH}",
            "max_batch": MAX_BATCH,
        }), 413

    accepted, duplicates, rejected, created = 0, 0, [], []

    for i, a in enumerate(rows):
        if not isinstance(a, dict):
            rejected.append({"index": i, "reason": "not_an_object"})
            continue

        missing = alert_implants.missing_contract_fields(a)
        if missing:
            rejected.append({"index": i, "reason": "missing_fields",
                             "missing": missing})
            continue

        if not alert_implants.is_implant(a):
            # This route is the implant transport. Another subgroup is not
            # an error in the producer's data, it is the wrong endpoint,
            # and saying so is more useful than silently dropping it.
            rejected.append({"index": i, "reason": "not_an_implant_subgroup",
                             "subgroup": a.get("subgroup")})
            continue

        try:
            patient_guid = uuid.UUID(str(a["patient_guid"]))
        except (ValueError, TypeError):
            rejected.append({"index": i, "reason": "patient_guid_not_a_guid"})
            continue

        patient = db.session.query(PatientIndex).filter_by(
            guid=patient_guid).first()
        if patient is None:
            rejected.append({"index": i, "reason": "unknown_patient"})
            continue

        device_id, usage_id = _derived_ids(a)

        if _existing(device_id) is not None:
            # Already pushed. Not an error and not a second Device —
            # #903's step 4. The producer may retry freely.
            duplicates += 1
            continue

        try:
            resources = alert_implants.to_fhir(
                a, patient_ref=f"Patient/{patient.guid}",
                device_id=device_id, usage_id=usage_id,
            )
        except ValueError as exc:
            # to_fhir validates the contract again and refuses a
            # non-implant. Reaching here means the checks above and its
            # own disagree, which is worth naming rather than 500ing.
            rejected.append({"index": i, "reason": "transform_refused",
                             "detail": str(exc)})
            continue

        for body in resources:
            res = create_resource(
                body["resourceType"], body, patient_guid=patient.guid)
            created.append({"resourceType": res.resource_type,
                            "id": res.resource_id})
        accepted += 1

    log_event(
        "implant_assertions_push",
        detail={
            "mechanism": "alert_implant_transport",
            "api_key_prefix": getattr(
                getattr(g, "api_key", None), "prefix", None),
            "received": len(rows),
            "accepted": accepted,
            "duplicates": duplicates,
            "rejected": len(rejected),
        },
    )
    db.session.commit()

    return jsonify({
        "accepted": accepted,
        "duplicates": duplicates,
        "rejected": rejected,
        "created": created,
    }), 200
