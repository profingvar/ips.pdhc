"""Map an alert.pdhc implant assertion to FHIR Device + DeviceUsage. EPS B6 (#886).

EPS makes section 46264-8 (medical devices and implants) **1..1**, and
alert.pdhc's `Förekomst av implantat` selection is that list as real
clinician-selected data rather than something to generate. `alert_assertion`
already carries `code_system`, `code`, `national_term`, `asserted_at`,
`negation` and `provenance` — which is everything this mapping needs.

## There is deliberately NO HTTP client here

Measured 2026-11-02: **alert.pdhc runs nowhere.** No container locally, none on
miserver, no `/usr/local/www/alert.pdhc`, and no row in CLAUDE.md's service
table. It has a Dockerfile and a compose file, so it is buildable; it is not
deployed.

Writing a client against it would reproduce the xlate defect (#833): a
module-level default base URL manufactures a configured-looking service out of
an unset variable, so "nobody wired this up" becomes indistinguishable from
"it blipped", and a permanent condition gets reported as retryable. The
transport is therefore left out and the transformation — the part that can be
built and proven today — is all that is here.

Note the direction already implied by configuration: alert.pdhc carries
`IPS_BASE_URL` and `IPS_API_KEY` and never calls them (#892 found them as
config nothing reads). So the intended wire is alert PUSHING here, not ips
pulling. `ASSERTION_CONTRACT` below is the shape this expects, so the wire is a
small step rather than a redesign.

## The national term must survive, and the code alone cannot carry it

From alert's own `registration.py`: *"Twelve codes bind two or three, which is
why this is a tuple and not a string: `Z95.0` in `Förekomst av implantat`
covers ICD, pacemaker AND pacemaker electrode … a record holding only the code
cannot say what the clinician picked."*

So a mapping that fills `Device.type.coding` and drops `national_term` loses
WHICH device was selected — a real clinical loss, not a formatting one. The
term goes in `Device.type.text`, because FHIR defines `CodeableConcept.text` as
the human-readable representation *as seen and selected by the user*, which is
exactly what a national term is.

## negation is the ABSENT case, not a Device

`negation` on an alert assertion means *it has been established that the
patient does NOT have it*. That is the IPS absent/unknown case, and the
section already declares `absent_code="no-known-devices"`. Emitting a Device
with a negation flag would make every consumer that reads the section see an
implant the patient does not have.

## asserted_at, never recorded_at

alert keeps the two apart for the same reason #895 does: `asserted_at` is when
the statement holds FROM, `recorded_at` is when we learned of it. A
`DeviceUsage` timing is a clinical fact about the patient, so it takes the
former. Using `recorded_at` would date every implant to the day it was
imported.

## A SIMULATED assertion must stay distinguishable

`provenance` is `documented` or `simulated` (alert enforces it with a check
constraint). The simulated marker survives into the resource, because this is
the MDR-relevant surface: a simulated alert that cannot be told from a real one
is the defect `euips_sections`'s own note on the alerts section warns about.
"""
from __future__ import annotations

from app.services import euips_sections as euips

#: The selection whose members are implants. Named, not reproduced: the
#: Socialstyrelsen specification behind it is copyright-protected, so this
#: cites the selection and reads codes from alert's own rows rather than
#: carrying a copy of the table.
IMPLANT_SUBGROUP = "Förekomst av implantat"

#: The shape this module expects from an alert.pdhc assertion. Written down
#: because there is no wire yet, so this is the contract a future transport has
#: to satisfy — and the thing to compare against `alert_assertion`'s columns
#: when one is built.
ASSERTION_CONTRACT = (
    "patient_guid", "subgroup", "code_system", "code", "national_term",
    "asserted_at", "negation", "provenance",
)

#: Carried into the resource so a simulated assertion cannot be mistaken for a
#: documented one. The value is alert's own, not re-spelled here.
SIMULATED = "simulated"

_PROVENANCE_SYSTEM = "https://alert.pdhc/provenance"


def is_implant(assertion: dict) -> bool:
    """Is this assertion a member of the implant selection?

    Matches on `subgroup`, which is what alert stores, rather than on the code:
    an ICD-10-SE `Z95.x` code can be reached from more than one selection, and
    the selection is what the clinician picked from.
    """
    return (assertion or {}).get("subgroup") == IMPLANT_SUBGROUP


def missing_contract_fields(assertion: dict) -> list[str]:
    """Which contract fields this assertion lacks.

    Returned rather than raised so a caller can report a bad batch without
    losing the good rows — and so a missing field is named instead of
    surfacing as a KeyError three frames away.
    """
    a = assertion or {}
    return [f for f in ASSERTION_CONTRACT if f not in a]


def to_fhir(assertion: dict, *, patient_ref: str,
            device_id: str | None = None,
            usage_id: str | None = None) -> list[dict]:
    """Device + DeviceUsage for one implant assertion, or the absent assertion.

    Ids are passed in rather than generated, so the caller controls identity
    and the function stays pure — a generator inside would make the output
    untestable for equality and would mint ids for resources a caller may
    discard.
    """
    missing = missing_contract_fields(assertion)
    if missing:
        raise ValueError(
            f"assertion is missing contract fields {missing}; see "
            f"ASSERTION_CONTRACT")
    if not is_implant(assertion):
        raise ValueError(
            f"not an implant assertion: subgroup="
            f"{assertion.get('subgroup')!r}, expected {IMPLANT_SUBGROUP!r}")

    simulated = assertion.get("provenance") == SIMULATED
    meta = {"tag": [{
        "system": _PROVENANCE_SYSTEM,
        "code": assertion.get("provenance"),
        "display": ("SIMULATED — not a clinical finding"
                    if simulated else "documented in a record"),
    }]}

    if assertion.get("negation"):
        # Established ABSENT. The section's own absent code, not a Device with
        # a flag: a Device would make every consumer see an implant that is
        # not there.
        body = {
            "resourceType": "Device",
            "text": {"status": "generated", "div":
                     "<div xmlns=\"http://www.w3.org/1999/xhtml\">"
                     "No known implants.</div>"},
            "status": "unknown",
            "type": euips.absent_coding("devices"),
            "patient": {"reference": patient_ref},
            "meta": meta,
        }
        if device_id:
            body["id"] = device_id
        return [body]

    term = assertion.get("national_term")
    device = {
        "resourceType": "Device",
        "status": "active",
        "patient": {"reference": patient_ref},
        "type": {
            "coding": [{"system": assertion["code_system"],
                        "code": assertion["code"]}],
            # The national term, which the code alone cannot carry: twelve
            # codes in this selection bind two or three terms. FHIR defines
            # `text` as the representation the USER selected, which is what a
            # national term is.
            "text": term,
        },
        "text": {"status": "generated", "div":
                 f"<div xmlns=\"http://www.w3.org/1999/xhtml\">{term}</div>"},
        "meta": meta,
    }
    if device_id:
        device["id"] = device_id

    usage = {
        "resourceType": "DeviceUsage",
        "status": "active",
        "patient": {"reference": patient_ref},
        # asserted_at, never recorded_at: this is a clinical fact about the
        # patient, not a bookkeeping timestamp. recorded_at would date every
        # implant to the day it was imported.
        "timingDateTime": assertion["asserted_at"],
        "text": {"status": "generated", "div":
                 f"<div xmlns=\"http://www.w3.org/1999/xhtml\">"
                 f"{term} in use.</div>"},
        "meta": meta,
    }
    if usage_id:
        usage["id"] = usage_id
    if device_id:
        usage["device"] = {"reference": f"Device/{device_id}"}
    return [device, usage]
