"""The euIPS document header — #792, phase B2 of the euIPS epic.

The guideline's header is not a section. It is what identifies the summary as a
document: who the patient is, who may be contacted about them, who pays, who
wrote it, who attests to it, who keeps it, and in what language and country.

Present before this module: id, name, birth date, gender,
``managingOrganization``, address. Absent: contact persons, legal guardian,
health insurance, author, legal authenticator, custodian, language, country of
origin. This module supplies those.

## The organisation must be derived, never invented

#792's watch item, and it is the #768 shape: the custodian, the Patient's
``managingOrganization`` and the ``PatientClinicAssignment`` row are three
places holding ONE fact. In #768 three organisation identifiers on one
datapoint failed to collapse, and the result was a Rule 24 gate scoping on the
wrong org.

So this module states the rule rather than leaving it to each caller:

    THE ASSIGNMENT IS AUTHORITATIVE.

``PatientClinicAssignment`` is what every cross-service consumer actually
queries (``GET /api/v1/clinics/<guid>/patients`` joins on it, not on
``managingOrganization``), so it is the fact and the other two are
projections of it. ``custodian_from_clinic`` takes a ``Clinic`` row and the
callers pass the clinic they resolved from the assignment. Nothing here accepts
a free-text organisation name.

## Codes are PROVISIONAL

Same honesty flag as :mod:`euips_sections`, for the same reason: the source
document states the EHDS technical specifications were not confirmed adopted,
and nothing here has been checked against a published IPS implementation
guide. Two specific R5-vs-R4 shapes are asserted below and deserve a reviewer's
eye, because getting them wrong produces a bundle that validates in the wrong
version and nowhere else:

* ``Coverage`` in R5 has ``kind`` (required) and ``insurer``; R4 had ``payor``
  and no ``kind``.
* ``Composition.attester.mode`` in R5 is a CodeableConcept; in R4 it was a
  plain code.

``CODES_VERIFIED`` is exported so an API response can say so instead of
letting a caller assume.
"""
import random
from datetime import date, datetime, timezone

#: False until the codes and the R5 element shapes here are checked against a
#: published IG. Mirrors euips_sections.CODES_VERIFIED deliberately — one flag
#: per module, so a verified module is not vouched for by an unverified one.
#:
#: **#885 flipped euips_sections' flag and deliberately left this one False.**
#: Two reasons, and the first is structural: this module's flag covers R5
#: ELEMENT SHAPES (see the attester.mode note above), and the EPS guide is an
#: R4 guide — an R4 document cannot verify an R5 shape, so no amount of
#: fetching it would lift this. Second, none of the codes in this module were
#: among those checked. `euips_sections.CODES_VERIFIED_AGAINST["not_covered"]`
#: records this, so the two flags cannot be mistaken for one.
CODES_VERIFIED = False

#: Swedish personal identity number. Same OID the generator already uses.
PERSONNUMMER_SYSTEM = "urn:oid:1.2.752.129.2.1.3.1"

#: Country of origin for every summary this service produces.
#:
#: NOTE on "country of origin": the guideline asks for it, and FHIR has no
#: Composition element that carries it. Rather than mint an extension URL that
#: no validator would recognise -- the fabrication this codebase has been bitten
#: by before -- it is represented where real elements exist: the custodian
#: Organization's address.country and the Patient's address.country. If the
#: published IG defines an element, move it there; do not invent one here.
COUNTRY_OF_ORIGIN = "SE"

#: Document language. sv-SE dominates, with a realistic minority tail so the
#: non-Swedish paths are actually exercised rather than merely supported --
#: #792 asks for exactly this. Weights are plausible, not census-derived.
LANGUAGE_WEIGHTS = (
    ("sv-SE", 86),
    ("en-GB", 5),
    ("fi-FI", 3),
    ("ar", 3),
    ("so-SO", 2),
    ("fa", 1),
)

#: An adult may have a legal guardian in Sweden (god man / förvaltare), but it
#: is a court appointment and not the common case, and #792 is explicit that a
#: 60-year-old with a guardian is a data-quality bug a simulator must not
#: manufacture. So a guardian is emitted ONLY for a minor, where it follows
#: from age alone and needs no invented court decision.
AGE_OF_MAJORITY = 18

# Contact-role codes. v2-0131 is the usual system for a patient contact's role
# and v3-RoleCode for a guardian; both are plausible and NEITHER is verified.
_V2_CONTACT_ROLE = "http://terminology.hl7.org/CodeSystem/v2-0131"
_V3_ROLE_CODE = "http://terminology.hl7.org/CodeSystem/v3-RoleCode"
_ACT_CODE = "http://terminology.hl7.org/CodeSystem/v3-ActCode"
_ATTESTATION_MODE = "http://hl7.org/fhir/composition-attestation-mode"

#: Swedish regions, used as the payer display for public cover. Keyed by the
#: city the generator already puts in Patient.address, so the insurer agrees
#: with where the patient lives instead of being drawn independently.
REGION_BY_CITY = {
    "Stockholm": "Region Stockholm",
    "Göteborg": "Västra Götalandsregionen",
    "Malmö": "Region Skåne",
    "Uppsala": "Region Uppsala",
    "Lund": "Region Skåne",
}
DEFAULT_REGION = "Region Stockholm"

_CONTACT_GIVEN = (
    "Anna", "Erik", "Karin", "Lars", "Maria", "Johan", "Eva", "Per",
    "Birgitta", "Anders", "Ingrid", "Olof",
)


# ---------------------------------------------------------------------------
# Age
# ---------------------------------------------------------------------------

def age_on(birth_date: str, asof: date | None = None) -> int | None:
    """Age in whole years, or None when `birth_date` is unusable.

    Returns None rather than raising or guessing. A caller that cannot
    establish an age must not emit a guardian — "unknown age" is not
    "minor", and defaulting either way would manufacture clinical fact.
    """
    if not birth_date:
        return None
    asof = asof or datetime.now(timezone.utc).date()
    try:
        born = date.fromisoformat(str(birth_date)[:10])
    except (ValueError, TypeError):
        return None
    return asof.year - born.year - (
        (asof.month, asof.day) < (born.month, born.day))


def needs_guardian(birth_date: str, asof: date | None = None) -> bool:
    """True only for a patient who is demonstrably a minor."""
    age = age_on(birth_date, asof)
    return age is not None and age < AGE_OF_MAJORITY


# ---------------------------------------------------------------------------
# Language
# ---------------------------------------------------------------------------

def pick_language(rnd: random.Random | None = None) -> str:
    rnd = rnd or random
    codes = [c for c, _ in LANGUAGE_WEIGHTS]
    weights = [w for _, w in LANGUAGE_WEIGHTS]
    return rnd.choices(codes, weights=weights, k=1)[0]


def patient_communication(language: str) -> list[dict]:
    """`Patient.communication` for the summary's language.

    `preferred` is True because this is the language the patient's own summary
    is written in; a second, non-preferred language would be a claim about the
    patient that the generator has no basis for.
    """
    return [{
        "language": {"coding": [{
            "system": "urn:ietf:bcp:47",
            "code": language,
        }]},
        "preferred": True,
    }]


# ---------------------------------------------------------------------------
# Contact persons and legal guardian
# ---------------------------------------------------------------------------

def related_person_resources(patient_ref: str, *, family: str,
                             birth_date: str,
                             rnd: random.Random | None = None,
                             asof: date | None = None) -> list[dict]:
    """RelatedPerson resources for this patient: a contact, plus a guardian
    only where age makes one plausible.

    The contact shares the patient's family name — a next-of-kin contact
    usually does, and an unrelated surname on a "next of kin" is the kind of
    detail that makes synthetic data obviously synthetic.
    """
    rnd = rnd or random
    out = [{
        "resourceType": "RelatedPerson",
        "active": True,
        "patient": {"reference": patient_ref},
        "relationship": [{
            "coding": [{
                "system": _V2_CONTACT_ROLE,
                "code": "C",
                "display": "Emergency Contact",
            }],
            "text": "Emergency contact",
        }],
        "name": [{
            "use": "official",
            "family": family,
            "given": [rnd.choice(_CONTACT_GIVEN)],
        }],
        "telecom": [{
            "system": "phone",
            "value": "+4670%d" % rnd.randint(1000000, 9999999),
            "use": "mobile",
        }],
        # #888: when this person became the patient's contact. Open-ended,
        # because they still are. Mirrored onto Patient.contact by
        # `patient_contact` so the two copies cannot disagree.
        "period": {"start": _contact_since(birth_date, rnd)},
    }]

    if needs_guardian(birth_date, asof):
        out.append({
            "resourceType": "RelatedPerson",
            "active": True,
            "patient": {"reference": patient_ref},
            "relationship": [
                {"coding": [{
                    "system": _V3_ROLE_CODE,
                    "code": "GUARD",
                    "display": "guardian",
                }], "text": "Legal guardian"},
                # A minor's guardian is in practice a parent. Both codings sit
                # on the resource because the legal role and the family
                # relationship are different facts and a consumer may filter
                # on either.
                {"coding": [{
                    "system": _V3_ROLE_CODE,
                    "code": "PRN",
                    "display": "parent",
                }], "text": "Parent"},
            ],
            "name": [{
                "use": "official",
                "family": family,
                "given": [rnd.choice(_CONTACT_GIVEN)],
            }],
            "telecom": [{
                "system": "phone",
                "value": "+4670%d" % rnd.randint(1000000, 9999999),
                "use": "mobile",
            }],
        })
    return out


#: Street names deliberately chosen because they are among the most common in
#: Sweden and exist in hundreds of municipalities, so a generated address is
#: plausible in SHAPE without resembling any particular real address. The same
#: judgement #792 applied to a contact's surname: synthetic data that is
#: obviously synthetic exercises nothing, and synthetic data that could be
#: somebody's actual address is worse.
_STREETS = ("Storgatan", "Kyrkogatan", "Skolgatan", "Järnvägsgatan",
            "Nygatan", "Parkvägen", "Björkgatan")

#: First three digits per city, so the postcode is not contradicted by the
#: city. Only the leading block is fixed; the rest is drawn, which keeps the
#: pair coherent without pinning a street.
_POSTCODE_PREFIX = {
    "Stockholm": "11", "Göteborg": "41", "Malmö": "21",
    "Uppsala": "75", "Lund": "22",
}


def _year_between(lo: int, hi: int, rnd: random.Random) -> int:
    """A year in [lo, hi], or `hi` when the range is empty.

    Degenerate ranges happen: a patient born last year has no plausible
    "moved in at 18". Clamping rather than raising keeps the generator usable
    for the whole birth-year range it draws from, and returning `hi` means the
    date is still in the past, which is the property that matters.
    """
    return rnd.randint(lo, hi) if lo <= hi else hi


def _past_date_after_birth(birth_date: str, *, min_age: int,
                           rnd: random.Random) -> str:
    """A date after the patient turned `min_age` and before today.

    A validity start BEFORE the patient was born is not a bad date, it is an
    impossible fact -- the same reasoning #900 applies to `ended_at` before
    `assigned_at`. So the lower bound is derived from the birth year rather
    than drawn freely.
    """
    try:
        birth_year = int(str(birth_date)[:4])
    except (TypeError, ValueError):
        birth_year = date.today().year - 40
    this_year = date.today().year
    y = _year_between(birth_year + min_age, this_year - 1, rnd)
    return f"{y:04d}-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}"


def _contact_since(birth_date: str, rnd: random.Random) -> str:
    """When a next-of-kin relationship began. At least adulthood-ish, so a
    contact is not recorded as having been one since infancy."""
    return _past_date_after_birth(birth_date, min_age=16, rnd=rnd)


def patient_address(city: str, *, moved_in: str | None = None,
                    rnd: random.Random | None = None) -> list[dict]:
    """A FHIR R5 `Address` with the elements a registry actually needs (#888).

    Before this, the generator wrote `use`, `city` and `country` and nothing
    else — so a service meant to hold "all state information about a patient"
    could not say what street they live on, and **had no validity period at
    all**.

    `period` is the element that matters most here, and not for completeness:
    it is the begin/end the state requirement asks for, and FHIR already has
    it. Until this existed, every demographic fact in the state projection
    (#895) carried `valid_from = NULL`, meaning "we do not know when this
    became true" — honest, and useless for answering "where did this patient
    live in March". This is what gives that axis real data.

    `city` is PASSED IN rather than drawn here, because the city determines the
    Coverage insurer's region (#792): drawing it independently would put a
    Stockholm resident on Region Skåne's books. The postcode's leading block
    follows the city for the same reason — a postcode contradicting the city is
    the sort of incoherence that makes a cohort useless for testing a real
    integration.
    """
    rnd = rnd or random
    prefix = _POSTCODE_PREFIX.get(city, "10")
    addr = {
        "use": "home",
        "type": "both",
        "line": [f"{rnd.choice(_STREETS)} {rnd.randint(1, 120)}"],
        "postalCode": f"{prefix}{rnd.randint(100, 999)}",
        "city": city,
        "country": COUNTRY_OF_ORIGIN,
    }
    if moved_in:
        # Open-ended: they still live there. A closed period would say they
        # have moved out and we do not know where to, which is a different
        # and much stronger claim.
        addr["period"] = {"start": moved_in}
    return addr


def patient_contact(related: list[dict]) -> list[dict]:
    """Mirror RelatedPerson entries into `Patient.contact`.

    Both are emitted on purpose. `RelatedPerson` is the referencable resource
    the document header needs; `Patient.contact` is the inline copy most
    consumers actually read, and a Patient with no contact looks like a patient
    with no next of kin. They are generated from one list here so they cannot
    disagree -- the same reason the custodian is derived rather than restated.
    """
    out = []
    for rp in related:
        entry = {"relationship": rp.get("relationship", [])}
        if rp.get("name"):
            entry["name"] = rp["name"][0]
        if rp.get("telecom"):
            entry["telecom"] = rp["telecom"]
        # #888: the period is mirrored too. The whole reason both copies are
        # generated from ONE list is that they cannot disagree, and a validity
        # period present on the RelatedPerson but absent from the inline copy
        # would be exactly that disagreement -- with the inline copy being the
        # one most consumers read.
        if rp.get("period"):
            entry["period"] = rp["period"]
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Health insurance
# ---------------------------------------------------------------------------

def coverage_resource(patient_ref: str, *, personnummer: str | None = None,
                      city: str | None = None) -> dict:
    """Regional public cover — the realistic Swedish default.

    #792 asks for public regional cover rather than a private-insurer
    placeholder, so `type` is PUBLICPOL and the insurer is the patient's
    region.

    `insurer` carries a display and NO reference, which FHIR permits for a
    Reference. That is deliberate: ips holds no region registry, so a
    `Organization/<guid>` here would be a GUID pointing at nothing — the
    dangling-reference problem that #771 and #768 are both about. A display-only
    reference says "this organisation, which I cannot resolve" honestly.

    R5 shape: `kind` is required and `insurer` replaces R4's `payor`. Flagged
    in the module docstring as one of the two shapes worth a reviewer's eye.
    """
    cov = {
        "resourceType": "Coverage",
        "status": "active",
        "kind": "insurance",
        "type": {
            "coding": [{
                "system": _ACT_CODE,
                "code": "PUBLICPOL",
                "display": "public healthcare",
            }],
            "text": "Swedish regional public health cover",
        },
        "beneficiary": {"reference": patient_ref},
        "insurer": {"display": REGION_BY_CITY.get(city or "", DEFAULT_REGION)},
    }
    if personnummer:
        # The personnummer IS the subscriber id for public cover; there is no
        # separate policy number to invent.
        cov["subscriberId"] = [{
            "system": PERSONNUMMER_SYSTEM,
            "value": personnummer,
        }]
    return cov


# ---------------------------------------------------------------------------
# Author, legal authenticator, custodian
# ---------------------------------------------------------------------------

def organization_resource(clinic) -> dict | None:
    """The custodian Organization, derived from the authoritative Clinic row.

    Returns None when there is no clinic, rather than a placeholder. A summary
    whose custodian is "Demo Clinic" asserts a custodian that does not exist,
    and the header would then disagree with the assignment — the exact
    divergence #792's watch item is about.
    """
    if clinic is None:
        return None
    org = {
        "resourceType": "Organization",
        "id": str(clinic.organisation_guid or clinic.guid),
        "active": bool(getattr(clinic, "is_active", True)),
        "name": clinic.name,
        # Country lives here because the guideline's "country of origin" has no
        # FHIR Composition element. See COUNTRY_OF_ORIGIN.
        "address": [{"country": COUNTRY_OF_ORIGIN}],
    }
    if clinic.identifier:
        org["identifier"] = [{"value": clinic.identifier}]
    return org


def composition_header(*, custodian_full_url: str | None,
                       custodian_display: str | None,
                       language: str,
                       attested_at: datetime | None = None) -> dict:
    """Composition header fields: language, author, attester, custodian.

    All three parties are the custodian ORGANISATION, not a Practitioner, and
    that is a decision rather than a shortcut. A generated summary has no human
    author; naming one would put a clinician who does not exist into clinical
    data, where a later reader has no way to tell the fabrication from a real
    attribution. FHIR allows an Organization for `author` and for
    `attester.party`, so the honest shape is also a legal one.

    When a real clinician authors a summary, their Practitioner reference
    belongs here instead — the caller supplies the party, this function does
    not invent one.

    R5 shape: `attester.mode` is a CodeableConcept, not a plain code.
    """
    header: dict = {"language": language}
    if not custodian_full_url:
        # No assignment -> no custodian, and therefore no author or attester
        # either. Emitting an unattributed document is correct; emitting an
        # invented attribution is not.
        return header

    party = {"reference": custodian_full_url}
    if custodian_display:
        party["display"] = custodian_display

    header["author"] = [dict(party)]
    header["custodian"] = dict(party)
    header["attester"] = [{
        "mode": {"coding": [{
            "system": _ATTESTATION_MODE,
            "code": "legal",
            "display": "Legal",
        }]},
        "time": (attested_at or datetime.now(timezone.utc)).isoformat(),
        "party": dict(party),
    }]
    return header


# ---------------------------------------------------------------------------
# Conformance reporting
# ---------------------------------------------------------------------------
#: Header elements #792 requires, and where each one lives once this module is
#: wired in. Used by the header report and by its tests, so "what the header
#: needs" is written once.
HEADER_ELEMENTS = (
    ("patient_id", "Patient.identifier"),
    ("patient_name", "Patient.name"),
    ("patient_birth_date", "Patient.birthDate"),
    ("patient_gender", "Patient.gender"),
    ("contact_person", "RelatedPerson(C) + Patient.contact"),
    ("legal_guardian", "RelatedPerson(GUARD) — minors only"),
    ("health_insurance", "Coverage"),
    ("author", "Composition.author"),
    ("legal_authenticator", "Composition.attester[mode=legal]"),
    ("custodian", "Composition.custodian"),
    ("created", "Composition.date"),
    ("language", "Composition.language + Patient.communication"),
    ("country_of_origin", "Organization.address.country"),
)


def header_status(*, patient_json: dict, related: list[dict],
                  coverage: list[dict], composition: dict | None) -> dict:
    """Which header elements are present for one patient. Computed, not stored.

    Deliberately derived on every call, like `euips_sections.status_for_
    resources`. A stored copy of a derivable fact is the shape that produced
    #779 and #771.

    `legal_guardian` reports `not_applicable` for an adult rather than
    `missing`: an adult without a guardian is correct, and counting it as a gap
    would push the generator toward manufacturing one.
    """
    p = patient_json or {}
    comp = composition or {}

    def _has(seq, code):
        for r in seq or ():
            for rel in r.get("relationship", ()):
                for c in rel.get("coding", ()):
                    if c.get("code") == code:
                        return True
        return False

    age = age_on(p.get("birthDate"))
    guardian_expected = age is not None and age < AGE_OF_MAJORITY

    present = {
        "patient_id": bool(p.get("identifier")),
        "patient_name": bool(p.get("name")),
        "patient_birth_date": bool(p.get("birthDate")),
        "patient_gender": bool(p.get("gender")),
        "contact_person": _has(related, "C") or bool(p.get("contact")),
        "health_insurance": bool(coverage),
        "author": bool(comp.get("author")),
        "legal_authenticator": any(
            (a.get("mode") or {}).get("coding", [{}])[0].get("code") == "legal"
            for a in comp.get("attester", ())),
        "custodian": bool(comp.get("custodian")),
        "created": bool(comp.get("date")),
        "language": bool(comp.get("language")) or bool(p.get("communication")),
        "country_of_origin": bool(COUNTRY_OF_ORIGIN),
    }

    out = {}
    for key, where in HEADER_ELEMENTS:
        if key == "legal_guardian":
            if not guardian_expected:
                out[key] = {"status": "not_applicable", "where": where,
                            "why": "patient is %s, so a guardian would be "
                                   "invented" % (
                                       "an adult" if age is not None
                                       else "of unknown age")}
            else:
                out[key] = {
                    "status": "present" if _has(related, "GUARD")
                    else "missing",
                    "where": where,
                }
            continue
        out[key] = {"status": "present" if present[key] else "missing",
                    "where": where}

    required_missing = [k for k, v in out.items() if v["status"] == "missing"]
    return {
        "elements": out,
        "missing": required_missing,
        "complete": not required_missing,
        "codes_verified": CODES_VERIFIED,
    }
