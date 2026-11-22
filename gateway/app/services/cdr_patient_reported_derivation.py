"""#1044 — what the patient reported reaches the EPS only once care endorsed it.

The patient fills in the EPS form (`plans/PROMs/eps_patient_v1.json`:
allergies, medication, previous illnesses, vaccinations, contact persons).
Each answer is stored in the CDR as a patient-generated ORIGINAL, and a
professional approves, amends-and-approves or rejects it there. An approval
writes a NEW CDR row, the ENDORSEMENT row: care's, `data_origin` NULL,
`endorses_guid` pointing at the original, authored by the professional.

THE RULE (contract s4.4), and the only one that decides what is a source:

    of patient-reported material, ONLY an endorsement row is a source:
    `endorses_guid` set AND `data_origin` NULL.

So an original derives nothing whatever its `review_status`, a pending or
rejected answer derives nothing, and the value used is the endorsement row's
own (the amended one when care amended). `is_source` is that rule and nothing
else reads the two fields.

FILE-FED, like `cdr_condition_derivation` (#984): the input is a JSON export
of CDR rows, one per answer:

    {cdr, guid, patient_guid, link_id, value, data_origin, endorses_guid,
     reviewed_by_user_guid, reviewed_by_name, reviewed_at,
     [author_org_guid], [group], [review_status]}

`data_origin` MUST BE STATED on every row (null for care's). An export that
omits the key cannot be told apart from one where everything is care's, so it
is refused rather than read as "all NULL".

WHAT IS REFUSED (the whole run, before anything is written), each because
writing around it would hide a broken record:

* a row with `endorses_guid` set and `data_origin` not NULL: a
  patient-generated row dressed as an endorsement;
* an endorsement row with no author: there would be nobody to attest;
* an endorsement whose original is in the same file and is not `endorsed`;
* two endorsement rows for one original;
* a row that does not state `data_origin`.

ONE ENTRY PER ANCHOR. An answer is one field (`allergy.substance`,
`allergy.reaction`, ...). The field that names the thing is the ANCHOR and
becomes one EPS resource; the other fields are DETAILS of it. A detail is
attached to the anchor of the same patient, section and `group` (the
repeating-group instance, when the export states it). Without `group`, a
detail is attached only when the section has exactly ONE endorsed anchor for
that patient; otherwise it is reported as `unattached` and NOT guessed onto
an entry. A detail whose anchor was rejected is likewise unattached.

FREE TEXT STAYS TEXT. No SNOMED, ATC or vaccine code is derived from a
string; an entry is `code.text` only. The only codes written are the ones the
patient CHOSE from a closed list (severity) or that the section itself
defines ("no known ...", see `euips_sections.absent_coding`).

NOTHING IS DELETED, as in #984. An entry this module derived earlier whose
endorsement row is not in the present export is left in place and REPORTED as
`orphaned` on every run until someone decides about it. An entry that
differs from what the export says gets a NEW VERSION (#934). Re-running on
the same export plans nothing.
"""
from __future__ import annotations

import json
import os
import uuid
from html import escape

from app.services import euips_sections as euips

PATIENT_GENERATED = "patient_generated"
SECTIONS = ("allergy", "medication", "history", "vaccination", "contact")

#: The CDR rows are answers stored as observations, so the link names that
#: table. Same convention as #984's `https://cdr.pdhc.se/fhir/Condition`, and
#: `euips_summary._cdr_ref` reads any `https://cdr.pdhc.se/fhir/` identifier.
CDR_IDENTIFIER_SYSTEM = "https://cdr.pdhc.se/fhir/Observation"
ENDORSED_TAG = {"system": "https://ips.pdhc.se/CodeSystem/provenance",
                "code": "endorsed-patient-reported",
                "display": "Reported by the patient, endorsed by care (#1044)"}
#: A PDHC extension, not a guideline element: who endorsed, and that the
#: patient is the informant. One shape on all five resource types, so the
#: summary and the Composition attester read it the same way everywhere.
ENDORSEMENT_EXT = "https://ips.pdhc.se/fhir/StructureDefinition/endorsement"
SSO_USER_SYSTEM = "https://sso.pdhc.se/user"
_ATTESTATION_MODE = "http://hl7.org/fhir/composition-attestation-mode"
_PARTICIPANT_TYPE = "http://terminology.hl7.org/CodeSystem/provenance-participant-type"
_NS = uuid.UUID("7b1d2c3e-1044-4a44-b044-e9d0a5e11044")

ANCHOR = {"allergy": "substance", "medication": "name", "history": "condition",
          "vaccination": "vaccine", "contact": "name"}
RESOURCE_TYPE = {"allergy": "AllergyIntolerance", "medication": "MedicationStatement",
                 "history": "Condition", "vaccination": "Immunization",
                 "contact": "RelatedPerson"}
DERIVED_TYPES = tuple(RESOURCE_TYPE.values())
#: "none known", endorsed, becomes the section's own absent assertion where
#: IPS defines one. Past illnesses and contacts have none: plain absence is
#: the correct representation there and nothing is written.
ABSENT_SECTION = {"allergy": "allergies", "medication": "medications",
                  "vaccination": "immunisations"}

#: Closed answer lists of the form, code -> the short word used in a note. A
#: test holds the CODES equal to the Questionnaire's.
CHOICES = {
    "status": {"has": None, "none": None, "unknown": None},
    "severity": {"mild": "Lindrig", "moderate": "Måttlig", "severe": "Allvarlig",
                 "unknown": "Vet inte"},
    "prescribed": {"yes": "Ja", "no": "Nej", "unknown": "Vet inte"},
}
#: The form itself, a byte-identical copy of plans/PROMs/eps_patient_v1.json
#: (a test compares them). Carried here because the deployed image holds this
#: repo only, and gateway forwards the DISPLAY of a coded answer: the displays
#: must be read from the form, not retyped.
QUESTIONNAIRE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                  "resources", "eps_patient_v1.json")
_DISPLAY_TO_CODE: dict[tuple[str, str], str] = {}


def learn_displays(questionnaire: dict | None = None) -> None:
    """Register every answerOption display of the form, per field."""
    if questionnaire is None:
        with open(QUESTIONNAIRE_PATH, encoding="utf-8") as fh:
            questionnaire = json.load(fh)
    def walk(items):
        for it in items or []:
            section, _, field = str(it.get("linkId", "")).partition(".")
            for o in it.get("answerOption") or []:
                c = o.get("valueCoding") or {}
                if c.get("code") and c.get("display"):
                    _DISPLAY_TO_CODE[(field, c["display"].strip().lower())] = c["code"]
            walk(it.get("item"))
    walk(questionnaire.get("item"))


# ------------------------------------------------------------------ the rule

def is_source(row: dict) -> bool:
    """Contract s4.4. The ONE place the rule lives."""
    return bool(row.get("endorses_guid")) and row.get("data_origin") is None


# ------------------------------------------------------------------- reading

def _first(row: dict, *keys):
    for k in keys:
        if row.get(k) not in (None, ""):
            return row[k]
    return None


def _link_id(row: dict) -> str:
    # gateway stores a form answer's linkId as the row's transaction_guid.
    return str(_first(row, "link_id", "linkId", "transaction_guid") or "")


def _split(row: dict) -> tuple[str | None, str | None]:
    section, _, field = _link_id(row).partition(".")
    return (section, field) if section in SECTIONS and field else (None, None)


def _text(value) -> str | None:
    if isinstance(value, dict):
        value = value.get("display") or value.get("code")
    if value is None or isinstance(value, bool):
        return None
    out = str(value).strip()
    return out or None


def _choice(field: str, value) -> str | None:
    """The CODE of a closed answer, from its code or its display. None when
    it is neither: an unrecognised answer is not mapped to the nearest one."""
    if isinstance(value, bool) and field == "prescribed":
        return "yes" if value else "no"
    code = value.get("code") if isinstance(value, dict) else None
    text = _text(value)
    for cand in (code, text):
        if cand and str(cand).strip().lower() in CHOICES[field]:
            return str(cand).strip().lower()
    if not _DISPLAY_TO_CODE:
        learn_displays()
    return _DISPLAY_TO_CODE.get((field, (text or "").lower()))


def endorser(row: dict) -> dict:
    return {"user_guid": _first(row, "reviewed_by_user_guid", "author_user_guid"),
            "name": _first(row, "reviewed_by_name", "author_name"),
            "org_guid": _first(row, "author_org_guid", "org_guid"),
            "at": _first(row, "reviewed_at", "endorsed_at", "created_at")}


def eps_id_for(cdr_guid: str) -> str:
    return str(uuid.uuid5(_NS, f"cdr/Observation/{cdr_guid}"))


# ---------------------------------------------------------------- validation

def sources(rows: list[dict]) -> list[dict]:
    """The endorsement rows of `rows`, or ValueError (see module docstring)."""
    by_guid = {r.get("guid"): r for r in rows}
    seen: dict[str, str] = {}
    out = []
    for r in rows:
        if "data_origin" not in r:
            raise ValueError(f"CDR row {r.get('guid')} does not state data_origin; an "
                             "export that omits it cannot show a row is care's")
        if not r.get("endorses_guid"):
            continue                    # an original, or not patient-reported at all
        if not is_source(r):
            raise ValueError(f"CDR row {r.get('guid')} has endorses_guid set but data_origin "
                             f"{r.get('data_origin')!r}: a patient-generated row is never an "
                             "EPS source")
        who = endorser(r)
        if not (who["user_guid"] and who["name"] and who["at"]):
            raise ValueError(f"endorsement row {r.get('guid')} names no author "
                             "(reviewed_by_user_guid, reviewed_by_name, reviewed_at)")
        orig = by_guid.get(r["endorses_guid"])
        if orig is not None and orig.get("review_status") not in (None, "endorsed"):
            raise ValueError(f"endorsement row {r.get('guid')} endorses {r['endorses_guid']}, "
                             f"whose review_status is {orig.get('review_status')!r}")
        if r["endorses_guid"] in seen:
            raise ValueError(f"original {r['endorses_guid']} has two endorsement rows: "
                             f"{seen[r['endorses_guid']]} and {r.get('guid')}")
        seen[r["endorses_guid"]] = r.get("guid")
        out.append(r)
    return out


# ------------------------------------------------------------------ building

def _narrative(text: str) -> dict:
    return {"status": "generated",
            "div": f'<div xmlns="http://www.w3.org/1999/xhtml">{escape(text)}</div>'}


def _cc(system: str, code: str, display: str) -> dict:
    return {"coding": [{"system": system, "code": code, "display": display}], "text": display}


def _who_ref(who: dict) -> dict:
    return {"type": "Practitioner", "display": who["name"],
            "identifier": {"system": SSO_USER_SYSTEM, "value": who["user_guid"]}}


def _endorsement_extension(patient_ref: str, endorsers: list[dict]) -> dict:
    ext = [{"url": "informant", "valueReference": {"reference": patient_ref}}]
    for who in endorsers:
        inner = [{"url": "who", "valueReference": _who_ref(who)},
                 {"url": "at", "valueDateTime": who["at"]}]
        if who.get("org_guid"):
            inner.append({"url": "organisation", "valueReference": {
                "reference": f"Organization/{who['org_guid']}"}})
        ext.append({"url": "endorsedBy", "extension": inner})
    return {"url": ENDORSEMENT_EXT, "extension": ext}


def _participants(patient_ref: str, endorsers: list[dict]) -> list[dict]:
    out = [{"function": _cc(_PARTICIPANT_TYPE, "informant", "Informant"),
            "actor": {"reference": patient_ref}}]
    out += [{"function": _cc(_PARTICIPANT_TYPE, "verifier", "Verifier"),
             "actor": _who_ref(w)} for w in endorsers]
    return out


def _wrap(body: dict, anchor: dict, details: dict[str, dict]) -> dict:
    """The common envelope: id, CDR links, tag, endorsement, narrative."""
    rows = [anchor] + [details[k] for k in sorted(details)]
    patient_ref = f"Patient/{anchor['patient_guid']}"
    endorsers, seen = [], set()
    for r in rows:
        w = endorser(r)
        if w["user_guid"] not in seen:
            seen.add(w["user_guid"])
            endorsers.append(w)
    out = {"resourceType": body["resourceType"], "id": eps_id_for(anchor["guid"]),
           "meta": {"tag": [dict(ENDORSED_TAG)]},
           "identifier": [{"system": CDR_IDENTIFIER_SYSTEM, "value": r["guid"],
                           "assigner": {"display": r.get("cdr")}} for r in rows],
           "extension": [_endorsement_extension(patient_ref, endorsers)]}
    out.update(body)
    names = ", ".join(w["name"] for w in endorsers)
    out["text"] = _narrative(f"{out.pop('_summary')}. Uppgift från patienten, godkänd av "
                             f"{names} {str(anchor_at(anchor))[:10]}.")
    if out["resourceType"] in ("AllergyIntolerance", "Condition"):
        out["participant"] = _participants(patient_ref, endorsers)
    return out


def anchor_at(row: dict) -> str:
    return endorser(row)["at"]


def _note(lines: list[str]) -> dict:
    return {"note": [{"text": t} for t in lines]} if lines else {}


def _detail(details: dict[str, dict], field: str) -> str | None:
    return _text(details[field].get("value")) if field in details else None


def build(section: str, anchor: dict, details: dict[str, dict]) -> dict:
    """One EPS resource from an endorsed anchor and its endorsed details."""
    ref = {"reference": f"Patient/{anchor['patient_guid']}"}
    what = _text(anchor.get("value"))
    at = anchor_at(anchor)
    notes: list[str] = []

    if section == "allergy":
        body = {"resourceType": "AllergyIntolerance", "patient": ref,
                "clinicalStatus": _cc(
                    "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                    "active", "Active"),
                "code": {"text": what}, "recordedDate": at}
        reaction = _detail(details, "reaction")
        sev = _choice("severity", details["severity"].get("value")) if "severity" in details else None
        if reaction:
            r = {"manifestation": [{"concept": {"text": reaction}}]}
            if sev in ("mild", "moderate", "severe"):
                r["severity"] = sev
            body["reaction"] = [r]
        elif sev in ("mild", "moderate", "severe"):
            # reaction.manifestation is 1..*, so a severity with no described
            # reaction has no coded home.
            notes.append(f"Allvarlighetsgrad enligt patienten: {CHOICES['severity'][sev].lower()}")
        summary = what + (f". Reaktion: {reaction}" if reaction else "")

    elif section == "medication":
        body = {"resourceType": "MedicationStatement", "status": "recorded", "subject": ref,
                "medication": {"concept": {"text": what}},
                "informationSource": [dict(ref)], "dateAsserted": at}
        dose = ", ".join(x for x in (_detail(details, "dose"), _detail(details, "frequency")) if x)
        if dose:
            body["dosage"] = [{"text": dose}]
        ind = _detail(details, "indication")
        if ind:
            body["reason"] = [{"concept": {"text": ind}}]
        if "prescribed" in details:
            p = _choice("prescribed", details["prescribed"].get("value"))
            if p:
                notes.append(f"Utskrivet av vården enligt patienten: {CHOICES['prescribed'][p].lower()}")
        summary = what + (f", {dose}" if dose else "")

    elif section == "history":
        # PATIENT HISTORY, not a care diagnosis: `inactive`, so it belongs to
        # past illnesses and can never match the active problem list, and no
        # verificationStatus, because nobody verified a diagnosis.
        body = {"resourceType": "Condition", "subject": ref,
                "clinicalStatus": _cc("http://terminology.hl7.org/CodeSystem/condition-clinical",
                                      "inactive", "Inactive"),
                "code": {"text": what}, "recordedDate": at}
        year = _detail(details, "year")
        if year and year.isdigit() and len(year) == 4:
            body["onsetDateTime"] = year
        elif year:
            notes.append(f"År enligt patienten: {year}")
        summary = what + (f" ({year})" if year else "")

    elif section == "vaccination":
        when = _detail(details, "date")
        body = {"resourceType": "Immunization", "status": "completed", "patient": ref,
                "vaccineCode": {"text": what}, "primarySource": False,
                "informationSource": {"reference": dict(ref)}}
        if when:
            body["occurrenceDateTime"] = when
        else:
            body["occurrenceString"] = "okänt datum"
        summary = what + (f", {when}" if when else "")

    elif section == "contact":
        body = {"resourceType": "RelatedPerson", "active": True, "patient": ref,
                "name": [{"text": what}]}
        rel = _detail(details, "relation")
        if rel:
            body["relationship"] = [{"text": rel}]
        phone = _detail(details, "phone")
        if phone:
            body["telecom"] = [{"system": "phone", "value": phone}]
        summary = what + (f" ({rel})" if rel else "")
    else:                                               # pragma: no cover
        raise ValueError(f"unknown section {section!r}")

    body.update(_note(notes))
    body["_summary"] = summary
    return _wrap(body, anchor, details)


def build_absent(section: str, row: dict) -> dict:
    """"No known ..." endorsed by care: the section's own absent assertion."""
    key = ABSENT_SECTION[section]
    ref = {"reference": f"Patient/{row['patient_guid']}"}
    coding, at = euips.absent_coding(key), anchor_at(row)
    if section == "allergy":
        body = {"resourceType": "AllergyIntolerance", "patient": ref, "code": coding,
                "clinicalStatus": _cc(
                    "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                    "active", "Active"), "recordedDate": at}
    elif section == "medication":
        body = {"resourceType": "MedicationStatement", "status": "recorded", "subject": ref,
                "medication": {"concept": coding}, "informationSource": [dict(ref)],
                "dateAsserted": at}
    else:
        body = {"resourceType": "Immunization", "status": "completed", "patient": ref,
                "vaccineCode": coding, "primarySource": False,
                "informationSource": {"reference": dict(ref)},
                "occurrenceString": "inga kända"}
    body["_summary"] = {"allergy": "Inga kända allergier", "medication": "Inga kända läkemedel",
                        "vaccination": "Inga kända vaccinationer"}[section]
    return _wrap(body, row, {})


# ------------------------------------------------------------------ planning

def is_derived(resource: dict) -> bool:
    return any(t.get("code") == ENDORSED_TAG["code"]
               for t in (resource.get("meta") or {}).get("tag") or [])


def desired(rows: list[dict]) -> tuple[dict[str, tuple], dict]:
    """(entries, report). entries: eps id -> (resource_type, patient_guid, json)."""
    src = sources(rows)
    report = {"rows": len(rows), "sources": len(src),
              "originals_ignored": sum(1 for r in rows if r.get("data_origin") == PATIENT_GENERATED),
              "not_eps_form": [], "unattached": [], "no_information": [],
              "none_without_absent_code": [], "unrecognised": [], "empty": []}
    anchors: dict[tuple, list[dict]] = {}
    details: list[tuple[str, str, dict]] = []
    out: dict[str, tuple] = {}
    for r in src:
        section, field = _split(r)
        if section is None:
            report["not_eps_form"].append(r["guid"])
        elif field == "status":
            code = _choice("status", r.get("value"))
            if code == "none" and section in ABSENT_SECTION:
                js = build_absent(section, r)
                out[js["id"]] = (js["resourceType"], r["patient_guid"], js)
            elif code == "none":
                report["none_without_absent_code"].append(r["guid"])
            elif code == "unknown":
                report["no_information"].append(r["guid"])
            elif code != "has":
                report["unrecognised"].append(r["guid"])
        elif field == ANCHOR[section]:
            if _text(r.get("value")) is None:
                report["empty"].append(r["guid"])
            else:
                anchors.setdefault((r["patient_guid"], section, r.get("group")), []).append(r)
        else:
            details.append((section, field, r))

    attached: dict[str, dict[str, dict]] = {}
    for section, field, r in details:
        mine = anchors.get((r["patient_guid"], section, r.get("group"))) or []
        if len(mine) != 1 or field in attached.get(mine[0]["guid"], {}):
            report["unattached"].append(r["guid"])
            continue
        attached.setdefault(mine[0]["guid"], {})[field] = r
    for (_, section, _), group in anchors.items():
        for a in group:
            js = build(section, a, attached.get(a["guid"], {}))
            out[js["id"]] = (js["resourceType"], a["patient_guid"], js)
    return out, report


def plan(rows: list[dict], current: dict[str, dict]) -> tuple[list[tuple], dict]:
    """(changes, report). changes: (action, resource_type, id, patient_guid, json),
    action "create" or "update" (a new version).

    `current` maps resource_id -> active resource_json, for the derived
    resource types. Nothing is deleted: a derived entry whose endorsement is
    not in `rows` is reported under `orphaned` and left as it is.
    """
    want, report = desired(rows)
    changes = []
    for rid in sorted(want):
        rtype, pg, js = want[rid]
        if rid not in current:
            changes.append(("create", rtype, rid, pg, js))
        elif current[rid] != js:
            changes.append(("update", rtype, rid, pg, js))
    report["orphaned"] = sorted(rid for rid, js in current.items()
                                if is_derived(js) and rid not in want)
    return changes, report


# ----------------------------------------------------- reading it back (EPS)

def endorsement_of(resource: dict) -> dict | None:
    """{"origin", "informant", "endorsed_by": [{name, user_guid, org_guid, at}]}
    for an entry this module derived, else None."""
    if not isinstance(resource, dict):
        return None
    for e in resource.get("extension") or []:
        if not isinstance(e, dict) or e.get("url") != ENDORSEMENT_EXT:
            continue
        by = []
        for sub in e.get("extension") or []:
            if sub.get("url") != "endorsedBy":
                continue
            parts = {x.get("url"): x for x in sub.get("extension") or []}
            who = (parts.get("who") or {}).get("valueReference") or {}
            org = ((parts.get("organisation") or {}).get("valueReference") or {}).get("reference")
            by.append({"name": who.get("display"),
                       "user_guid": (who.get("identifier") or {}).get("value"),
                       "org_guid": org.split("/")[-1] if org else None,
                       "at": (parts.get("at") or {}).get("valueDateTime")})
        return {"origin": "patient_reported", "informant": "patient", "endorsed_by": by}
    return None


def attesters(resources: list[dict]) -> list[dict]:
    """`Composition.attester` entries for the professionals who endorsed
    patient-reported content in `resources`: one per person, mode
    `professional`, at their LATEST endorsement. Same structure as the legal
    attester in `euips_header.composition_header`; the party is a display
    plus the SSO user identifier, not a reference to a Practitioner resource
    this service does not hold.
    """
    latest: dict[str, dict] = {}
    for rj in resources:
        for who in (endorsement_of(rj) or {}).get("endorsed_by", ()):
            if not who.get("user_guid"):
                continue
            prev = latest.get(who["user_guid"])
            if prev is None or str(who.get("at") or "") > str(prev.get("at") or ""):
                latest[who["user_guid"]] = who
    return [{"mode": {"coding": [{"system": _ATTESTATION_MODE, "code": "professional",
                                  "display": "Professional"}]},
             "time": w["at"], "party": _who_ref(w)}
            for _, w in sorted(latest.items())]
