"""Backfill the euIPS document header onto patients that predate #792.

The generator emits a header for every patient it creates from now on. The
patients already in the database do not have one: measured on production
2026-10-08, a real assigned patient had a custodian, author, attester and
language — all of which are DERIVED on read and therefore appeared immediately —
but `RelatedPerson: 0, Coverage: 0`, because those are stored resources and
nothing had written them.

That split is worth keeping in mind when reading this module: the header is
half derived and half stored, so deploying #792 fixed half of it everywhere and
none of the other half anywhere.

## Why this is a separate, opt-in command and not a migration

It WRITES CLINICAL-ADJACENT PATIENT DATA. A contact person and an insurance
policy are statements about a real person's circumstances, and this service's
rows feed cdr_6, analyse and every spärr decision downstream. A migration that
silently manufactured a next of kin for 150 patients is not something anyone
could later distinguish from data a clinician entered.

So: `--dry-run` is the default, it reports exactly what it would write, and the
operator chooses. Nothing here runs on deploy.

## Idempotence

A patient that already has a RelatedPerson or a Coverage is skipped for that
resource, not given a second one. Running it twice is a no-op, which matters
because the first thing anyone does with a backfill is run it again to see
whether it worked.
"""
import random
from datetime import datetime, timezone

from app.models.base import db
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex
from app.services import euips_header as hdr
from app.services.fhir_service import create_resource


def _existing_types(patient_guid) -> set[str]:
    rows = (db.session.query(FhirResource.resource_type)
            .filter(FhirResource.patient_guid == patient_guid)
            .filter(FhirResource.status == "active")
            .filter(FhirResource.resource_type.in_(
                ["RelatedPerson", "Coverage", "Patient"]))
            .all())
    return {r[0] for r in rows}


def _patient_json(patient_guid):
    row = (db.session.query(FhirResource)
           .filter(FhirResource.patient_guid == patient_guid)
           .filter(FhirResource.resource_type == "Patient")
           .filter(FhirResource.status == "active")
           .order_by(FhirResource.version_id.desc())
           .first())
    return (row.resource_json if row else None), row


def plan(limit: int | None = None) -> dict:
    """What a backfill WOULD do. Pure read.

    Returns per-patient actions plus a summary, so a dry run and a real run
    agree by construction — the real path consumes this plan rather than
    recomputing it.
    """
    q = db.session.query(PatientIndex).order_by(PatientIndex.created_at)
    if limit:
        q = q.limit(limit)

    actions = []
    for p in q.all():
        pj, _row = _patient_json(p.guid)
        if pj is None:
            actions.append({"patient_guid": str(p.guid),
                            "skip": "no active Patient resource"})
            continue
        have = _existing_types(p.guid)
        age = hdr.age_on(pj.get("birthDate"))
        family = ((pj.get("name") or [{}])[0].get("family") or "Okänd")
        city = ((pj.get("address") or [{}])[0].get("city") or None)
        pnr = ((pj.get("identifier") or [{}])[0].get("value") or None)
        actions.append({
            "patient_guid": str(p.guid),
            "family": family,
            "age": age,
            "city": city,
            "needs_related": "RelatedPerson" not in have,
            "needs_coverage": "Coverage" not in have,
            "needs_language": not pj.get("communication"),
            "needs_contact_inline": not pj.get("contact"),
            "guardian_applicable": age is not None
            and age < hdr.AGE_OF_MAJORITY,
            "personnummer": bool(pnr),
        })

    todo = [a for a in actions if not a.get("skip")]
    return {
        "patients": len(actions),
        "skipped": [a for a in actions if a.get("skip")],
        "need_related": sum(1 for a in todo if a["needs_related"]),
        "need_coverage": sum(1 for a in todo if a["needs_coverage"]),
        "need_language": sum(1 for a in todo if a["needs_language"]),
        "guardians_to_create": sum(
            1 for a in todo if a["needs_related"] and a["guardian_applicable"]),
        "actions": actions,
    }


def run(limit: int | None = None, dry_run: bool = True,
        seed: int | None = None) -> dict:
    """Apply the plan. `dry_run=True` (the default) writes nothing.

    `seed` makes the generated names and numbers reproducible, so a dry run
    followed by a real run produce the same values and the operator reviews
    what actually lands.
    """
    rnd = random.Random(seed) if seed is not None else random
    p = plan(limit)
    created = {"RelatedPerson": 0, "Coverage": 0}
    patched_language = 0
    patched_contact = 0

    if dry_run:
        p.update({"dry_run": True, "created": created,
                  "patched_language": 0, "patched_contact": 0})
        return p

    for a in p["actions"]:
        if a.get("skip"):
            continue
        guid = a["patient_guid"]
        pj, row = _patient_json(guid)
        if pj is None:
            continue
        patient_ref = "Patient/%s" % pj.get("id")
        body = dict(pj)

        related = []
        if a["needs_related"]:
            related = hdr.related_person_resources(
                patient_ref, family=a["family"],
                birth_date=pj.get("birthDate"), rnd=rnd)
            for rp in related:
                create_resource("RelatedPerson", rp, patient_guid=guid)
                created["RelatedPerson"] += 1

        if a["needs_coverage"]:
            create_resource(
                "Coverage",
                hdr.coverage_resource(
                    patient_ref,
                    personnummer=((pj.get("identifier") or [{}])[0]
                                  .get("value")),
                    city=a["city"]),
                patient_guid=guid)
            created["Coverage"] += 1

        # Patch the Patient resource in place for the two inline fields.
        # `language` is picked ONCE and stored, so the Composition reads it
        # back and a regenerated summary does not change language.
        changed = False
        if a["needs_language"]:
            lang = hdr.pick_language(rnd)
            body["language"] = lang
            body["communication"] = hdr.patient_communication(lang)
            patched_language += 1
            changed = True
        if a["needs_contact_inline"] and related:
            body["contact"] = hdr.patient_contact(related)
            patched_contact += 1
            changed = True
        if changed:
            # Reassign rather than mutate: resource_json is a JSON column and
            # an in-place mutation is not always seen as dirty by SQLAlchemy.
            row.resource_json = body

    db.session.commit()
    p.update({"dry_run": False, "created": created,
              "patched_language": patched_language,
              "patched_contact": patched_contact,
              "ran_at": datetime.now(timezone.utc).isoformat()})
    return p


def format_plan(p: dict) -> str:
    mode = "DRY RUN — nothing was written" if p.get("dry_run", True) \
        else "APPLIED"
    lines = [
        "euIPS header backfill (#792) — %s" % mode,
        "  patients examined      : %d" % p["patients"],
        "  need contact persons   : %d" % p["need_related"],
        "  need health insurance  : %d" % p["need_coverage"],
        "  need a document language: %d" % p["need_language"],
        "  of which legal guardians: %d  (minors only — an adult guardian "
        "would be invented)" % p["guardians_to_create"],
    ]
    if p["skipped"]:
        lines.append("  SKIPPED (no Patient resource): %d" % len(p["skipped"]))
    if not p.get("dry_run", True):
        lines += [
            "  created RelatedPerson  : %d" % p["created"]["RelatedPerson"],
            "  created Coverage       : %d" % p["created"]["Coverage"],
            "  patched language       : %d" % p["patched_language"],
            "  patched Patient.contact: %d" % p["patched_contact"],
        ]
    else:
        lines.append("  Re-run with --no-dry-run to apply. This WRITES "
                     "patient data; see the module docstring.")
    return "\n".join(lines)
