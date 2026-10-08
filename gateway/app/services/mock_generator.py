"""Generate a synthetic patient cohort for one clinic.

Extracted from `admin.generate_mock_data` on 2026-10-08. The logic lived
inside a `@bp.route` POST handler, reading `request.form` and reporting through
`flash()`, so clicking a button in a browser with an SSO session was the ONLY
way to generate patients — unusable from a CLI, a migration or a verification
script, which is exactly what rebuilding the cohort needed.

The route still calls this and still flashes; the web flow is unchanged. It
simply is no longer the only caller.

Nothing was reimplemented. A second generator would have been two
implementations of one rule — the shape that cost #784 and #786 a day each,
and the reason `_is_uuid` was hoisted in #791 rather than copied.
"""
import random
import uuid
from datetime import datetime, timezone

from app.models.base import db
from app.models.clinic import Clinic
from app.models.fhir_resource import FhirResource
from app.models.ips_card import IpsCard
from app.models.ips_snapshot import IpsSnapshot
from app.models.patient_index import PatientIndex, PatientClinicAssignment
from app.services import (euips_eu_additions, euips_header, euips_optional,
                          euips_recommended, euips_required, euips_sections)
from app.services import personnummer as pnr
from app.services.fhir_service import create_resource
from app.services.ips_generator import generate_ips_bundle

#: Matches sim.pdhc's typical cohort smoke runs, and the old form's cap.
MAX_PER_RUN = 150


# ── the Swedish name pool, moved here with the generator (2026-10-08) ──
# It had no reader left in admin.py once `generate` moved, and leaving it
# behind would have been a second home for generator data.
_SWEDISH_FAMILY = [
    "Andersson", "Johansson", "Karlsson", "Nilsson", "Eriksson",
    "Larsson", "Olsson", "Persson", "Svensson", "Gustafsson",
    "Pettersson", "Jonsson", "Jansson", "Hansson", "Bengtsson",
    "Jönsson", "Lindberg", "Jakobsson", "Magnusson", "Olofsson",
    "Lindström", "Lindqvist", "Lindgren", "Berg", "Axelsson",
    "Berglund", "Bergström", "Lundberg", "Lundgren", "Lundqvist",
    "Mattsson", "Berggren", "Sandberg", "Henriksson", "Forsberg",
    "Sjöberg", "Wallin", "Engström", "Eklund", "Holmgren",
]

_SWEDISH_GIVEN_M = [
    "Erik", "Lars", "Karl", "Anders", "Per", "Mikael", "Johan",
    "Olof", "Nils", "Sven", "Jan", "Hans", "Gunnar", "Bo", "Bengt",
    "Magnus", "Stefan", "Daniel", "Tomas", "Mats", "Niklas", "Fredrik",
    "Henrik", "Andreas", "David", "Martin", "Oscar", "Jonas",
    "Alexander", "Filip",
]

_SWEDISH_GIVEN_F = [
    "Anna", "Eva", "Maria", "Karin", "Sara", "Lena", "Birgitta",
    "Christina", "Ingrid", "Margareta", "Elisabeth", "Marianne",
    "Kerstin", "Astrid", "Linda", "Susanne", "Ulla", "Inger",
    "Helena", "Monica", "Cecilia", "Hanna", "Lisa", "Emma",
    "Sofia", "Julia", "Lina", "Klara", "Elin", "Alva",
]

def _build_unique_patient_pool(count: int) -> list[dict]:
    """Sample up to ``count`` unique (family, given, gender, birth)
    dicts from the combinatorial Swedish-name pool.

    The shape mirrors the original `_SWEDISH_NAMES` entries so the
    callsite stays unchanged.
    """
    import random
    male_pool = [(f, g, "male") for f in _SWEDISH_FAMILY for g in _SWEDISH_GIVEN_M]
    female_pool = [(f, g, "female") for f in _SWEDISH_FAMILY for g in _SWEDISH_GIVEN_F]
    pool = male_pool + female_pool
    random.shuffle(pool)
    n = min(count, len(pool))
    out: list[dict] = []
    for family, given, gender in pool[:n]:
        # Birth years 1940–2010, random month/day. We don't try to be
        # epidemiologically realistic — sim.pdhc owns the data semantics
        # and just needs a valid birthDate to attach observations to.
        year = random.randint(1940, 2010)
        month = random.randint(1, 12)
        day = random.randint(1, 28)
        out.append({
            "family": family,
            "given": given,
            "gender": gender,
            "birth": f"{year:04d}-{month:02d}-{day:02d}",
        })
    return out


def generate(clinic_guid, count=4, skip_clinical=False):
    """Create `count` synthetic patients assigned to `clinic_guid`.

    Returns a report dict. A caller that cannot resolve the clinic should
    REFUSE rather than call this: patients with no assignment are invisible to
    every organisation-scoped reader, which is the 28-patient problem this
    work exists to end. The CLI refuses; the admin form always passes a clinic
    chosen from a list.
    """
    import random

    count = min(int(count), MAX_PER_RUN)

    # Resolve clinic — carries both org_guid and name
    clinic = db.session.query(Clinic).filter_by(guid=clinic_guid).first() if clinic_guid else None
    org_guid = clinic.organisation_guid if clinic else ""
    org_name = clinic.name if clinic else "Demo Clinic"

    patients_pool = _build_unique_patient_pool(count)
    created_count = 0
    created_guids: list = []        # #793: for the conformance count below
    # #797: ONE batch guid for this POST. Without it a batch cannot be undone
    # except by recording its GUIDs by hand, which is what #791 added the
    # column for.
    #
    # Name uniqueness is per BATCH, not global: _build_unique_patient_pool
    # samples without replacement from 2400 combinations, so 100 is safe within
    # one batch but two batches can repeat a name. Left that way deliberately
    # -- a simulator wants plausible Swedish names more than globally unique
    # ones, and the batch guid is what distinguishes the cohorts. Recorded as a
    # decision rather than left as a surprise.
    batch_guid = uuid.uuid4()

    for mp in patients_pool:
        resource_id = str(uuid.uuid4())
        # #789: was `f"19{mp['birth'].replace('-','')}-{randint(1000,9999)}"`.
        # mp['birth'] is already YYYY-MM-DD, so the "19" doubled the century
        # (1919611015-9638, 15 chars instead of 13), and the last digit is a
        # Luhn checksum rather than a free number — valid in 6 of 60 sampled
        # live rows, exactly chance. Worst case was a 2000s birth becoming
        # "19"+"20xx", an identifier contradicting its own birth_date.
        personnummer = pnr.build(mp["birth"])

        # #792: city is now a variable because the Coverage insurer is the
        # patient's REGION, derived from where they live. Drawn independently
        # it would put a Stockholm resident on Region Skåne's books.
        city = random.choice(["Stockholm", "Göteborg", "Malmö", "Uppsala",
                              "Lund"])
        # #792: mostly sv-SE with a realistic minority tail, so the
        # non-Swedish paths are exercised rather than merely supported. Stored
        # on the Patient so the Composition can read it back and a regenerated
        # summary keeps the same language.
        language = euips_header.pick_language(random)

        patient_fhir = {
            "resourceType": "Patient",
            "id": resource_id,
            "language": language,
            "name": [{"family": mp["family"], "given": [mp["given"]], "use": "official"}],
            "gender": mp["gender"],
            "birthDate": mp["birth"],
            "identifier": [{
                "system": euips_header.PERSONNUMMER_SYSTEM,
                "value": personnummer,
            }],
            "managingOrganization": {
                "reference": f"Organization/{org_guid}" if org_guid else None,
                "display": org_name,
            },
            "address": [{
                "use": "home",
                "city": city,
                "country": euips_header.COUNTRY_OF_ORIGIN,
            }],
            "telecom": [{
                "system": "phone",
                "value": f"+4670{random.randint(1000000, 9999999)}",
                "use": "mobile",
            }],
            "communication": euips_header.patient_communication(language),
        }

        # #792: contact persons, and a legal guardian ONLY for a minor. The
        # birth-year range is 1940-2010, so roughly 3% of a cohort are minors
        # today and the guardian path actually fires -- it is not dead code,
        # and it does not fabricate a guardian for a 60-year-old, which the
        # ticket names as a data-quality bug a simulator must not manufacture.
        related = euips_header.related_person_resources(
            f"Patient/{resource_id}", family=mp["family"],
            birth_date=mp["birth"], rnd=random)
        # Inline copy on the Patient as well as the referencable resources,
        # built from ONE list so the two cannot disagree.
        patient_fhir["contact"] = euips_header.patient_contact(related)
        create_resource("Patient", patient_fhir)
        patient = db.session.query(PatientIndex).filter_by(resource_id=resource_id).first()
        if not patient:
            continue
        patient.generation_batch_guid = batch_guid      # #797

        # Link to clinic via PatientClinicAssignment (same reason as the
        # admin create_patient path: cross-service consumers query the
        # /api/v1/clinics/<guid>/patients endpoint which joins on this
        # table, not on FHIR managingOrganization).
        if clinic:
            db.session.add(PatientClinicAssignment(
                patient_guid=patient.guid,
                clinic_guid=clinic.guid,
            ))

        # #792: document-header resources, in BOTH modes. The header is what
        # makes the bundle a document; a patient handed to sim.pdhc for its
        # clinical content still needs a custodian, a contact and insurance.
        # They are header facts, not clinical ones, so skip_clinical does not
        # apply -- the same reasoning as the required sections above.
        for body in related:
            create_resource("RelatedPerson", body,
                            patient_guid=patient.guid)
        create_resource(
            "Coverage",
            euips_header.coverage_resource(
                f"Patient/{resource_id}",
                personnummer=personnummer, city=city),
            patient_guid=patient.guid)

        # #793: the three euIPS REQUIRED sections, ALWAYS, in BOTH modes.
        # The guideline forbids an empty required section -- "you must state
        # 'no known allergies' rather than leave the section empty" -- and
        # measured 2026-10-07 this generator had left 110 of 150 patients with
        # no statement at all in any section.
        #
        # In skip_clinical mode they are emitted as explicit absent
        # assertions, not skipped. skip_clinical exists so sim.pdhc can own the
        # clinical data without two sources of truth, which is a good reason;
        # it is not a reason to create a non-conformant patient in the
        # meantime. sim's real content supersedes them later, because
        # status_for_resources prefers real content over a stale absent
        # assertion.
        for body in euips_required.required_sections_for(
                f"Patient/{resource_id}", absent_only=skip_clinical):
            create_resource(body["resourceType"], body,
                            patient_guid=patient.guid)

        if not skip_clinical:
            # #794: the four RECOMMENDED sections — immunisations, procedures,
            # medical devices (which never existed before) and diagnostic
            # results with their actual Observations. Emitted in dependency
            # order, so an Observation is written before the DiagnosticReport
            # that references it and no dangling reference is ever created.
            #
            # Unlike the required three these may legitimately be absent, so a
            # section can come back as content, as an explicit "none known", or
            # as nothing at all. All three are valid here.
            for body in euips_recommended.recommended_sections_for(
                    f"Patient/{resource_id}", mp["birth"]):
                create_resource(body["resourceType"], body,
                                patient_guid=patient.guid)

            # #795: the seven OPTIONAL sections. Needs the patient's sex as
            # well as their birth date, because a CURRENT pregnancy is
            # female-only and age-bounded -- while pregnancy HISTORY is valid
            # for an 80-year-old woman, so the two are gated separately.
            for body in euips_optional.optional_sections_for(
                    f"Patient/{resource_id}", mp["birth"], mp["gender"]):
                create_resource(body["resourceType"], body,
                                patient_guid=patient.guid)

            # #796: the three EU additions — medical alerts, travel history,
            # patient-provided information. Every resource carries
            # meta.tag urn:pdhc:provenance#simulated, because these are the
            # platform's FIRST Flag resources and request.pdhc's computed
            # alerting path is the MDR-relevant surface: a simulated alert must
            # never be mistakable for a computed one.
            for body in euips_eu_additions.eu_addition_sections_for(
                    f"Patient/{resource_id}"):
                create_resource(body["resourceType"], body,
                                patient_guid=patient.guid)

            # Create IPS card + snapshot (linked to clinic)
            card = IpsCard(
                patient_guid=patient.guid,
                clinic_guid=clinic.guid if clinic else None,
                title=f"IPS — {mp['given']} {mp['family']}",
                mode="full",
            )
            db.session.add(card)
            db.session.flush()

            now = datetime.now(timezone.utc)
            bundle = generate_ips_bundle(patient, mode="full", composition_date=now)
            snapshot = IpsSnapshot(
                card_guid=card.guid,
                bundle_json=bundle,
                composition_date=now,
                mode="full",
                resource_count=len(bundle.get("entry", [])),
            )
            db.session.add(snapshot)
        created_guids.append(patient.guid)
        created_count += 1

    db.session.commit()
    # #793: report euIPS conformance rather than listing resource types. The
    # operator's question is "are these valid patient summaries", and the old
    # message asserted a list of sections without checking any of them.
    conformant = 0
    for guid in created_guids:
        rows = (db.session.query(FhirResource)
                .filter(FhirResource.patient_guid == guid).all())
        if euips_sections.is_conformant(
                euips_sections.status_for_resources(rows)):
            conformant += 1
    detail = ("required sections only (skip_clinical)" if skip_clinical
              else "full euIPS section set")
    resources = (db.session.query(FhirResource)
                 .filter(FhirResource.patient_guid.in_(created_guids)).count()
                 if created_guids else 0)
    return {
        "clinic_guid": str(clinic_guid),
        "clinic_name": org_name,
        "organisation_guid": str(org_guid),
        "care_organisation_guid": (clinic.care_organisation_guid
                                   if clinic else None),
        "batch_guid": str(batch_guid),
        "created": created_count,
        "conformant": conformant,
        "resources": resources,
        "skip_clinical": bool(skip_clinical),
        "patient_guids": [str(g) for g in created_guids],
    }
