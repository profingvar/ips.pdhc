"""Everything eps holds about ONE patient, in the platform's extract shape.

#1059, record.pdhc stage 6b (plan s4.4, decisions D9/D10). Contract:
`plans/record_pdhc_extract_contract.md` (schema `pdhc.patient-extract/1`).
record.pdhc asks every service that holds patient data for its part and
writes one PDF; eps's part is identity, care units, contacts, related
persons, spärrar, consents, nödöppning, Mitt patientkort, the EPS summary and
the EPS documents generated here.

## Every patient-linked table is either a section or a named exclusion

`TABLE_COVERAGE` maps each table that holds data about a patient to the
section(s) it is exported in; `TABLE_EXCLUSIONS` names the rest with the
reason. `uncovered_tables()` finds every table linked to a patient (a column
whose name contains "patient", a foreign key to `patient_index`, or a foreign
key to a table that is itself linked) and returns the ones in neither map. A
test asserts that set is empty, so a model with patient data added later
fails the suite until someone decides where it goes.

## Versions

* `fhir_resources` is append-only (#934): every version is a row, older ones
  `superseded`, a retired one `retired` (#1049). All are exported, oldest
  first.
* Every other table here is ONE row per fact that is updated in place (a
  block is lifted on its own row, a consent revoked on its own row, an
  assignment ended on its own row). There is no history table in eps, so
  each such item has one version and the section's `note_sv` says so. The
  row's own lifecycle columns (created / lifted / revoked / ended, each with
  its own time and actor) are given as `events` on the item, from the row
  itself, never reconstructed from elsewhere.
* `audit_log` is the change log, and it is deliberately not mined for
  versions: it records that something happened, not the row's content.

## Two times

`event_time` is when the thing happened or became true, `recorded_at` when
eps stored it. Only columns that MEAN that are used; when a table has no such
column the value is `null` (contract: never a guess). The per-table choice is
in `docs/technical.md` (#1059).

## Personnummer appears in `identity` only

The contract says so. A copy elsewhere (a stored EPS document bundle, a
RelatedPerson's own identifier) has its value replaced by `REDACTED_PNR`, and
the section note says so. A test asserts the number occurs nowhere else.

## No secrets

No API-key hash, token, session id, push-destination credentials or headers
are read into the extract. `push_destinations` contributes its name and
type only; a push job's free-text `error_message` is left out because a
transport error can quote a URL.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Iterable

from app.models.base import db
from app.models.clinic import Clinic
from app.models.emergency_access import EmergencyAccess
from app.models.fhir_resource import FhirResource
from app.models.ips_card import IpsCard
from app.models.ips_snapshot import IpsSnapshot
from app.models.patient_block import PatientBlock
from app.models.patient_consent import PatientConsent
from app.models.patient_index import PatientClinicAssignment, PatientIndex
from app.models.patient_proxy_grant import PatientProxyGrant
from app.models.push_destination import PushDestination
from app.models.push_job import PushJob
from app.services import euips_sections as euips
from app.services import euips_summary
from app.services.cdr_patient_reported_derivation import (
    card_version_of, endorsement_of, is_derived)
from app.services.personnummer import PERSONNUMMER_SYSTEM

SCHEMA = "pdhc.patient-extract/1"
SERVICE = "eps.pdhc"
REDACTED_PNR = "[personnummer: se avsnittet Identitet]"

#: D9: besides SU, the professions that may take out an extract.
EXTRACT_ROLES = frozenset({"doctor", "nurse"})

# ----------------------------------------------------------- coverage map

#: table -> the section key(s) it is exported in.
TABLE_COVERAGE: dict[str, tuple[str, ...]] = {
    "patient_index": ("identity",),
    "fhir_resources": ("identity", "contacts", "related_persons",
                       "patient_card", "conditions", "summary"),
    "patient_clinic_assignments": ("care_units",),
    "patient_blocks": ("blocks",),
    "patient_consents": ("consents",),
    "emergency_access": ("emergency_access",),
    "patient_proxy_grants": ("proxy_grants",),
    "ips_cards": ("eps_documents",),
    "ips_snapshots": ("eps_documents",),
    "push_jobs": ("eps_deliveries",),
}

#: table -> why it is NOT in the extract. Every reason must hold up to
#: "the patient asked for everything eps has about them".
TABLE_EXCLUSIONS: dict[str, str] = {
    "patient_state_facts": (
        "a derived projection (#895), rebuilt from patient_index, "
        "fhir_resources (Patient versions), patient_clinic_assignments, "
        "patient_blocks, patient_consents and emergency_access, all of which "
        "ARE in the extract; exporting it would show every fact twice"),
    "audit_log": (
        "who read or changed the record. D10: that is the optional part of "
        "the extract and record.pdhc takes it from the loggkontroll endpoint "
        "GET /api/v1/audit/patients/<guid> (#1045), not from here"),
}

ROOT_TABLE = "patient_index"


def _linked_by_columns(table) -> bool:
    return any("patient" in c.name.lower() for c in table.columns)


def _fk_targets(table) -> set[str]:
    # target_fullname is the declared "table.column" string, so this works on
    # a Table whose FK target is in another MetaData (the control tests).
    return {fk.target_fullname.split(".")[0] for fk in table.foreign_keys}


def patient_linked_tables(tables: Iterable) -> set[str]:
    """Names of the tables that hold data about a patient, to a fixpoint."""
    tables = list(tables)
    linked = {ROOT_TABLE}
    linked |= {t.name for t in tables if _linked_by_columns(t)}
    changed = True
    while changed:
        changed = False
        for t in tables:
            if t.name not in linked and _fk_targets(t) & linked:
                linked.add(t.name)
                changed = True
    return linked


def uncovered_tables(tables: Iterable | None = None) -> set[str]:
    """Patient-linked tables neither exported nor excluded by name."""
    if tables is None:
        tables = db.metadata.tables.values()
    return patient_linked_tables(tables) - set(TABLE_COVERAGE) - set(TABLE_EXCLUSIONS)


# -------------------------------------------------------------- formatting

def _iso(dt) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    return str(dt)


def _d(dt) -> str:
    """A date for a Swedish summary line, or 'okänt'."""
    s = _iso(dt)
    return s[:10] if s else "okänt"


def _s(v) -> str | None:
    return str(v) if v is not None else None


def _author(guid=None, name=None, role=None) -> dict | None:
    if guid is None and name is None:
        return None
    return {"guid": _s(guid), "name": name, "role": role, "service": SERVICE}


def _version(n: int, *, event_time, recorded_at, author, status, summary_sv,
             fhir, **extra) -> dict:
    v = {"version": n, "event_time": _iso(event_time) if isinstance(event_time, datetime) else event_time,
         "recorded_at": _iso(recorded_at), "author": author, "status": status,
         "summary_sv": summary_sv, "fhir": fhir}
    v.update(extra)
    return v


def _item(resource_type: str, id_, versions: list[dict], **extra) -> dict:
    it = {"resource_type": resource_type, "id": _s(id_),
          "current_status": versions[-1]["status"] if versions else None,
          "versions": versions}
    it.update(extra)
    return it


def _section(key: str, title_sv: str, items: list[dict], note_sv: str | None = None,
             **extra) -> dict:
    s = {"key": key, "title_sv": title_sv, "count": len(items), "items": items}
    if note_sv:
        s["note_sv"] = note_sv
    s.update(extra)
    return s


def redact_personnummer(obj):
    """A deep copy of `obj` with every personnummer identifier's value
    replaced. Used on everything outside the identity section."""
    out = copy.deepcopy(obj)

    def walk(o):
        if isinstance(o, dict):
            if o.get("system") == PERSONNUMMER_SYSTEM and "value" in o:
                o["value"] = REDACTED_PNR
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(out)
    return out


# --------------------------------------------------------------- FHIR rows

def _fhir_rows(pi: PatientIndex) -> list[FhirResource]:
    """Every version of every fhir_resources row about this patient."""
    q = db.session.query(FhirResource).filter(db.or_(
        FhirResource.patient_guid == pi.guid,
        db.and_(FhirResource.resource_type == "Patient",
                FhirResource.resource_id == pi.resource_id)))
    return q.order_by(FhirResource.resource_type, FhirResource.resource_id,
                      FhirResource.version_id).all()


def _group(rows: list[FhirResource]) -> dict[tuple, list[FhirResource]]:
    out: dict[tuple, list[FhirResource]] = {}
    for r in rows:
        out.setdefault((r.resource_type, r.resource_id), []).append(r)
    return out


def fhir_category(rtype: str, versions: list[FhirResource]) -> str:
    """Which section a fhir_resources resource (all its versions) belongs to.
    Exactly one, so nothing is counted twice."""
    if rtype == "Patient":
        return "identity"
    if any(is_derived(v.resource_json or {}) for v in versions):
        return "patient_card"
    if rtype == "RelatedPerson":
        return "related_persons"
    if euips.canonical_resource_type(rtype) == "Condition":
        return "conditions"
    return "summary"


def _name(rj: dict) -> str | None:
    for n in rj.get("name") or []:
        if isinstance(n, dict):
            if n.get("text"):
                return n["text"]
            parts = list(n.get("given") or []) + ([n["family"]] if n.get("family") else [])
            if parts:
                return " ".join(parts)
    return None


def _addresses(rj: dict) -> list[str]:
    out = []
    for a in rj.get("address") or []:
        if isinstance(a, dict):
            txt = a.get("text") or ", ".join(
                [*(a.get("line") or []), " ".join(x for x in (a.get("postalCode"), a.get("city")) if x)])
            if txt.strip(", "):
                out.append(txt.strip(", "))
    return out


def _telecoms(rj: dict) -> list[str]:
    return [f"{t.get('system') or 'kontakt'} {t.get('value')}"
            for t in rj.get("telecom") or [] if isinstance(t, dict) and t.get("value")]


def _pnr(rj: dict) -> str | None:
    for i in rj.get("identifier") or []:
        if isinstance(i, dict) and i.get("system") == PERSONNUMMER_SYSTEM:
            return i.get("value")
    return None


_SEX_SV = {"male": "man", "female": "kvinna", "other": "annat", "unknown": "okänt"}


def _patient_summary(rj: dict) -> str:
    parts = [f"Namn: {_name(rj) or 'saknas'}"]
    pnr = _pnr(rj)
    parts.append(f"personnummer {pnr}" if pnr else "inget personnummer")
    others = [f"{i.get('system')}|{i.get('value')}" for i in rj.get("identifier") or []
              if isinstance(i, dict) and i.get("system") != PERSONNUMMER_SYSTEM]
    if others:
        parts.append("övriga identifierare " + "; ".join(others))
    parts.append(f"född {rj.get('birthDate') or 'okänt'}")
    parts.append(f"kön {_SEX_SV.get(rj.get('gender'), rj.get('gender') or 'okänt')}")
    if _addresses(rj):
        parts.append("adress " + " / ".join(_addresses(rj)))
    if _telecoms(rj):
        parts.append("kontakt " + ", ".join(_telecoms(rj)))
    if rj.get("deceasedBoolean") or rj.get("deceasedDateTime"):
        parts.append(f"avliden {rj.get('deceasedDateTime') or ''}".strip())
    return ", ".join(parts)


def _contact_summary(contacts: list) -> str:
    if not contacts:
        return "Inga kontaktpersoner i denna version"
    out = []
    for c in contacts:
        if not isinstance(c, dict):
            continue
        name = (c.get("name") or {}).get("text") or " ".join(
            list((c.get("name") or {}).get("given") or []) +
            ([(c.get("name") or {}).get("family")] if (c.get("name") or {}).get("family") else []))
        rel = ", ".join(x.get("text") or (x.get("coding") or [{}])[0].get("display")
                        or (x.get("coding") or [{}])[0].get("code") or ""
                        for x in c.get("relationship") or [] if isinstance(x, dict))
        tel = ", ".join(_telecoms(c))
        out.append(" ".join(x for x in (name or "namn saknas",
                                         f"({rel})" if rel else "", tel) if x))
    return "Kontaktpersoner: " + "; ".join(out)


def _entry_summary(row: FhirResource, label: str) -> tuple[str, dict]:
    e = euips_summary.entry(row)
    what = e["display"] or e["narrative_text"] or e["code"] or "utan benämning"
    bits = [f"{label}: {what}"]
    if e["code"]:
        bits.append(f"kod {e['code']}" + (f" ({e['system']})" if e["system"] else ""))
    if e["value"] is not None:
        bits.append(f"värde {e['value']}" + (f" {e['unit']}" if e["unit"] else ""))
    if e["status"]:
        bits.append(f"status {e['status']}")
    if e["date"]:
        bits.append(f"datum {e['date'][:10]}")
    if e["cdr_backed"]:
        bits.append(f"förankrad i CDR ({(e['cdr'] or {}).get('name') or 'cdr'})")
    else:
        bits.append("ej förankrad i CDR")
    return ", ".join(bits), e


_TYPE_SV = {"Condition": "Diagnos", "AllergyIntolerance": "Allergi/överkänslighet",
            "MedicationStatement": "Läkemedel", "MedicationRequest": "Läkemedelsordination",
            "Immunization": "Vaccination", "Procedure": "Åtgärd", "Observation": "Observation",
            "Device": "Medicinteknisk produkt", "DeviceUsage": "Användning av produkt",
            "DeviceUseStatement": "Användning av produkt",
            "DiagnosticReport": "Undersökningssvar", "CarePlan": "Vårdplan",
            "Flag": "Varning", "Consent": "Samtycke (FHIR)", "RelatedPerson": "Närstående",
            "ClinicalImpression": "Bedömning", "QuestionnaireResponse": "Formulärsvar"}


def _eps_sections(row: FhirResource) -> list[str]:
    rj = row.resource_json if isinstance(row.resource_json, dict) else {}
    if euips.is_absent_assertion(rj):
        k = euips.absent_section_key(rj)
        return [k] if k else []
    return [s.key for s in euips.SECTIONS if euips.section_matches(s, row.resource_type, rj)]


def _clinical_items(groups: list[list[FhirResource]], *, card: bool = False) -> list[dict]:
    items = []
    for versions in groups:
        last = versions[-1]
        vs = []
        for r in versions:
            rj = r.resource_json if isinstance(r.resource_json, dict) else {}
            summary, e = _entry_summary(r, _TYPE_SV.get(r.resource_type, r.resource_type))
            extra = {}
            author = None
            if card:
                end = endorsement_of(rj) or {}
                extra["card_version"] = card_version_of(rj)
                extra["endorsed_by"] = end.get("endorsed_by") or []
                extra["informant"] = end.get("informant")
                by = extra["endorsed_by"]
                if by:
                    author = _author(by[0].get("user_guid"), by[0].get("name"), "endorser")
                names = ", ".join(w.get("name") or "okänd" for w in by)
                summary += (f"; uppgift från patienten, godkänd av {names or 'okänd'}"
                            + (f", kortversion {extra['card_version']}" if extra["card_version"] else ""))
            if r.status == "retired":
                summary += "; borttagen ur sammanfattningen (ersatt av nyare godkänd kortversion)"
            vs.append(_version(r.version_id, event_time=e["date"], recorded_at=r.created_at,
                               author=author, status=r.status, summary_sv=summary,
                               fhir=redact_personnummer(rj), **extra))
        cdr = euips_summary._cdr_ref(last.resource_json if isinstance(last.resource_json, dict) else {})
        items.append(_item(last.resource_type, last.resource_id, vs,
                           cdr_backed=cdr is not None, cdr=cdr,
                           eps_sections=_eps_sections(last)))
    return items


# ----------------------------------------------------------------- sections

def _identity(pi: PatientIndex, patient_versions: list[FhirResource]) -> dict:
    items = []
    if patient_versions:
        vs = [_version(r.version_id, event_time=None, recorded_at=r.created_at, author=None,
                       status=r.status, summary_sv=_patient_summary(r.resource_json or {}),
                       fhir=copy.deepcopy(r.resource_json))
              for r in patient_versions]
        items.append(_item("Patient", patient_versions[-1].resource_id, vs))
    d = pi.to_dict()
    flags = [f"aktiv {'ja' if pi.is_active else 'nej'}",
             f"arkiverad {_d(pi.archived_at) if pi.archived_at else 'nej'}",
             f"EHDS sekundäranvändning avböjd {'ja' if pi.ehds_opt_out else 'nej'}",
             f"kvalitetsregister avböjt {'ja' if pi.quality_registry_opt_out else 'nej'}",
             f"forskningssamtycken {len(pi.consented_research_projects or [])}"]
    items.append(_item("PatientIndex", pi.guid, [_version(
        1, event_time=None, recorded_at=pi.created_at, author=None,
        status="active" if pi.is_active else "inactive",
        summary_sv="eps patientregister: " + ", ".join(flags), fhir=None, row=d,
        updated_at=_iso(pi.updated_at))]))
    return _section(
        "identity", "Identitet", items,
        "Patient-resursen har full versionshistorik i eps (alla versioner visas). "
        "Patientregistrets rad (patient_index) uppdateras på plats: en version, "
        "senast ändrad enligt updated_at. Ingen författare lagras per version. "
        "Personnummer visas bara här.")


def _contacts(patient_versions: list[FhirResource]) -> dict:
    items = []
    if any((r.resource_json or {}).get("contact") for r in patient_versions):
        vs = [_version(r.version_id, event_time=None, recorded_at=r.created_at, author=None,
                       status=r.status,
                       summary_sv=_contact_summary((r.resource_json or {}).get("contact") or []),
                       fhir=redact_personnummer((r.resource_json or {}).get("contact") or []))
              for r in patient_versions]
        items.append(_item("Patient.contact", patient_versions[-1].resource_id, vs))
    return _section(
        "contacts", "Kontaktpersoner (Patient.contact)", items,
        "Kontaktpersonerna är en del av Patient-resursen; varje version av den "
        "visas med sin lista.")


def _care_units(pi: PatientIndex) -> dict:
    rows = (db.session.query(PatientClinicAssignment, Clinic)
            .outerjoin(Clinic, Clinic.guid == PatientClinicAssignment.clinic_guid)
            .filter(PatientClinicAssignment.patient_guid == pi.guid)
            .order_by(PatientClinicAssignment.assigned_at).all())
    items = []
    for a, c in rows:
        name = c.name if c else "okänd enhet"
        unit = _s(c.organisation_guid) if c else None
        status = "ended" if a.ended_at else "active"
        summary = (f"Listad vid {name}" + (f" (vårdenhet {unit})" if unit else "")
                   + f" från {_d(a.assigned_at)}"
                   + (f" till {_d(a.ended_at)}" if a.ended_at else ", pågående")
                   + (f"; ursprung {a.origin}" if a.origin else ""))
        items.append(_item("PatientClinicAssignment", a.guid, [_version(
            1, event_time=a.assigned_at, recorded_at=None, author=None, status=status,
            summary_sv=summary, fhir=None,
            row={"clinic_guid": _s(a.clinic_guid), "clinic_name": name,
                 "care_unit_guid": unit, "assigned_at": _iso(a.assigned_at),
                 "ended_at": _iso(a.ended_at), "origin": a.origin})],
            events=[e for e in ({"event": "assigned", "at": _iso(a.assigned_at)},
                                {"event": "ended", "at": _iso(a.ended_at)} if a.ended_at else None) if e]))
    return _section(
        "care_units", "Vårdenheter (listning)", items,
        "Alla listningar, även avslutade. En listning uppdateras på plats när den "
        "avslutas (ended_at): en version per listning. Tabellen har ingen "
        "registreringstid skild från listningens start, så recorded_at är null.")


def _blocks(pi: PatientIndex) -> dict:
    rows = (db.session.query(PatientBlock).filter_by(patient_guid=pi.guid)
            .order_by(PatientBlock.created_at).all())
    items = []
    for b in rows:
        ev = [{"event": "created", "at": _iso(b.created_at), "by": _s(b.created_by_user_guid),
               "reason": b.created_reason}]
        if b.lifted_at:
            ev.append({"event": "lifted", "at": _iso(b.lifted_at), "by": _s(b.lifted_by_user_guid),
                       "kind": b.lift_kind, "reason": b.lifted_reason,
                       "lift_expires_at": _iso(b.lift_expires_at)})
        summary = (f"Spärr mot {b.source_scope_type} {b.source_scope_id} från {_d(b.created_at)}"
                   + (f", tidsbegränsad till {_d(b.expires_at)}" if b.expires_at else ""))
        if b.lifted_at:
            kind = {"consent": "med patientens samtycke",
                    "indispensable_care": "för oundgänglig vård"}.get(b.lift_kind, b.lift_kind or "")
            summary += f"; hävd {_d(b.lifted_at)} {kind}".rstrip()
            if b.lift_expires_at:
                summary += f" till {_d(b.lift_expires_at)}"
        summary += f"; gäller nu: {'ja' if b.is_active() else 'nej'}"
        items.append(_item("PatientBlock", b.guid, [_version(
            1, event_time=b.created_at, recorded_at=b.created_at,
            author=_author(b.created_by_user_guid), status="active" if b.is_active() else "inactive",
            summary_sv=summary, fhir=None, row=b.to_dict())], events=ev))
    return _section(
        "blocks", "Spärrar", items,
        "Alla spärrar, även hävda och utgångna. En spärr hävs på sin egen rad: "
        "en version per spärr, med skapande och hävning som händelser med egna "
        "tider och utförare.")


def _consents(pi: PatientIndex) -> dict:
    rows = (db.session.query(PatientConsent).filter_by(patient_guid=pi.guid)
            .order_by(PatientConsent.granted_at).all())
    items = []
    for c in rows:
        ev = [{"event": "granted", "at": _iso(c.granted_at), "by": _s(c.granted_by_user_guid),
               "via": c.granted_via}]
        if c.revoked_at:
            ev.append({"event": "revoked", "at": _iso(c.revoked_at),
                       "by": _s(c.revoked_by_user_guid), "reason": c.revoked_reason})
        summary = (f"Samtycke till sammanhållen vård för vårdgivare {c.grantee_caregiver_guid}, "
                   f"lämnat {_d(c.granted_at)} via {c.granted_via}"
                   + (f" (avtal {c.contract_guid})" if c.contract_guid else "")
                   + (f", tidsbegränsat till {_d(c.expires_at)}" if c.expires_at else "")
                   + (f"; avgränsat till {len(c.consented_concept_guids)} begrepp"
                      if c.consented_concept_guids else "")
                   + (f"; återkallat {_d(c.revoked_at)}" if c.revoked_at else "")
                   + f"; gäller nu: {'ja' if c.is_active() else 'nej'}")
        items.append(_item("PatientConsent", c.guid, [_version(
            1, event_time=c.granted_at, recorded_at=None, author=_author(c.granted_by_user_guid),
            status="active" if c.is_active() else "inactive", summary_sv=summary, fhir=None,
            row=c.to_dict())], events=ev))
    return _section(
        "consents", "Samtycken", items,
        "Samtycken till sammanhållen vård, även återkallade och de som kommit "
        "från contract.pdhc (granted_via = contract, #558). Ett samtycke "
        "återkallas på sin egen rad: en version per samtycke. Tabellen saknar "
        "separat registreringstid, så recorded_at är null. Patientens avböjanden "
        "(EHDS, kvalitetsregister) och forskningssamtycken står i avsnittet "
        "Identitet (patientregistret).")


def _emergency(pi: PatientIndex) -> dict:
    rows = (db.session.query(EmergencyAccess).filter_by(patient_guid=pi.guid)
            .order_by(EmergencyAccess.created_at).all())
    items = []
    for e in rows:
        d = e.to_dict()   # no session_id: to_dict leaves it out
        summary = (f"Nödöppning för vårdenhet {e.reader_care_unit_guid} av "
                   f"{e.actor_label or e.actor_user_guid or 'okänd'} {_d(e.attested_at)}, "
                   f"skäl: {e.reason}; gällde till {_d(e.expires_at)}"
                   + (f"; patienten underrättad {_d(e.notified_at)}" if e.notified_at
                      else "; patienten ännu inte underrättad"))
        items.append(_item("EmergencyAccess", e.guid, [_version(
            1, event_time=e.attested_at, recorded_at=e.created_at,
            author=_author(e.actor_user_guid, e.actor_label),
            status="active" if e.is_active() else "expired", summary_sv=summary,
            fhir=None, row=d)]))
    return _section(
        "emergency_access", "Nödöppningar", items,
        "Nödöppningar skrivs en gång och ändras aldrig (de löper ut): en version var.")


def _proxy(pi: PatientIndex) -> dict:
    rows = (db.session.query(PatientProxyGrant).filter_by(patient_guid=pi.guid)
            .order_by(PatientProxyGrant.granted_at).all())
    items = []
    for p in rows:
        ev = [{"event": "granted", "at": _iso(p.granted_at), "by": _s(p.granted_by_user_guid),
               "via": p.granted_via}]
        if p.revoked_at:
            ev.append({"event": "revoked", "at": _iso(p.revoked_at),
                       "by": _s(p.revoked_by_user_guid), "role": p.revoked_by_role,
                       "reason": p.revoked_reason})
        summary = (f"Ombud {p.proxy_label or p.proxy_user_guid} ({p.scope}) från "
                   f"{_d(p.valid_from)}" + (f" till {_d(p.valid_to)}" if p.valid_to else "")
                   + (f"; återkallat {_d(p.revoked_at)} av {p.revoked_by_role or 'okänd'}"
                      if p.revoked_at else "")
                   + f"; gäller nu: {'ja' if p.is_active() else 'nej'}")
        items.append(_item("PatientProxyGrant", p.guid, [_version(
            1, event_time=p.valid_from, recorded_at=p.granted_at,
            author=_author(p.granted_by_user_guid),
            status="active" if p.is_active() else "inactive", summary_sv=summary,
            fhir=None, row=p.to_dict())], events=ev))
    return _section(
        "proxy_grants", "Ombud (närståendes behörighet)", items,
        "Behörigheter patienten gett närstående att agera för hen (#889). "
        "Återkallas på sin egen rad: en version per behörighet.")


def _snapshot_summary(s: IpsSnapshot, card: IpsCard) -> str:
    return (f"EPS-dokument ({s.mode}) skapat {_d(s.created_at)}, sammanställningsdatum "
            f"{_d(s.composition_date)}, {s.resource_count if s.resource_count is not None else '?'} "
            f"resurser" + (f", kort '{card.title}'" if card.title else ""))


def _eps_documents(pi: PatientIndex) -> dict:
    cards = (db.session.query(IpsCard).filter_by(patient_guid=pi.guid)
             .order_by(IpsCard.created_at).all())
    items = []
    for card in cards:
        snaps = (db.session.query(IpsSnapshot).filter_by(card_guid=card.guid)
                 .order_by(IpsSnapshot.created_at).all())
        vs = [_version(i, event_time=s.composition_date, recorded_at=s.created_at,
                       author=_author(s.generated_by_guid), status="final",
                       summary_sv=_snapshot_summary(s, card),
                       fhir=redact_personnummer(s.bundle_json), snapshot_guid=str(s.guid))
              for i, s in enumerate(snaps, start=1)]
        if not vs:
            vs = [_version(1, event_time=None, recorded_at=card.created_at,
                           author=_author(card.created_by_guid), status=card.status,
                           summary_sv=f"EPS-kort '{card.title or ''}' utan genererat dokument",
                           fhir=None)]
        items.append(_item("IpsCard", card.guid, vs, card=card.to_dict()))
    return _section(
        "eps_documents", "Genererade EPS-dokument", items,
        "Varje EPS-kort med alla dokument (ögonblicksbilder) som genererats från "
        "det, äldst först; en ögonblicksbild ändras aldrig. Personnumret i "
        "dokumentens Patient-resurs är ersatt med en hänvisning till avsnittet "
        "Identitet.")


def _eps_deliveries(pi: PatientIndex) -> dict:
    rows = (db.session.query(PushJob, IpsSnapshot, PushDestination)
            .join(IpsSnapshot, IpsSnapshot.guid == PushJob.snapshot_guid)
            .join(IpsCard, IpsCard.guid == IpsSnapshot.card_guid)
            .outerjoin(PushDestination, PushDestination.guid == PushJob.destination_guid)
            .filter(IpsCard.patient_guid == pi.guid)
            .order_by(PushJob.created_at).all())
    items = []
    for j, s, dest in rows:
        dname = dest.name if dest else "okänd mottagare"
        summary = (f"EPS-dokument från {_d(s.created_at)} skickat till {dname}"
                   + (f" ({dest.destination_type})" if dest else "")
                   + f", status {j.status}"
                   + (f", svarskod {j.response_code}" if j.response_code is not None else "")
                   + (f", klart {_d(j.completed_at)}" if j.completed_at else ""))
        items.append(_item("PushJob", j.guid, [_version(
            1, event_time=j.completed_at or j.last_attempt_at, recorded_at=j.created_at,
            author=_author(j.initiated_by_guid), status=j.status, summary_sv=summary, fhir=None,
            row={"snapshot_guid": str(j.snapshot_guid), "destination_guid": str(j.destination_guid),
                 "destination_name": dname,
                 "destination_type": dest.destination_type if dest else None,
                 "status": j.status, "attempts": j.attempts,
                 "last_attempt_at": _iso(j.last_attempt_at),
                 "completed_at": _iso(j.completed_at), "response_code": j.response_code,
                 "created_at": _iso(j.created_at)})]))
    return _section(
        "eps_deliveries", "Överföringar av EPS-dokument", items,
        "Varje överföring av ett EPS-dokument till en mottagare. Mottagarens "
        "adress, inloggningsuppgifter och felmeddelanden tas inte med.")


# --------------------------------------------------------------------- build

def build(pi: PatientIndex) -> dict:
    """The extract for one patient. The caller has already decided access."""
    rows = _fhir_rows(pi)
    groups = _group(rows)
    by_cat: dict[str, list[list[FhirResource]]] = {}
    for (rtype, _), versions in sorted(groups.items()):
        by_cat.setdefault(fhir_category(rtype, versions), []).append(versions)
    patient_versions = [v for vs in by_cat.get("identity", []) for v in vs]
    patient_versions.sort(key=lambda r: (r.resource_id != pi.resource_id, r.version_id))
    # A Patient row under another resource_id would be a second patient; it
    # is still eps's data about this guid, so it is not dropped.
    own = [r for r in patient_versions if r.resource_id == pi.resource_id]
    stray = [g for g in by_cat.get("identity", []) if g[0].resource_id != pi.resource_id]

    sections = [
        _identity(pi, own),
        _care_units(pi),
        _contacts(own),
        _section("related_persons", "Närstående (RelatedPerson)",
                 _clinical_items(by_cat.get("related_persons", [])),
                 "Närstående som egna resurser, alla versioner. Närstående som "
                 "patienten själv angett och vården godkänt står under Mitt patientkort."),
        _proxy(pi),
        _blocks(pi),
        _consents(pi),
        _emergency(pi),
        _section("patient_card", "Mitt patientkort (godkända uppgifter i EPS)",
                 _clinical_items(by_cat.get("patient_card", []), card=True),
                 "eps håller de poster som härletts ur patientens GODKÄNDA kortversioner, "
                 "alla versioner inklusive borttagna (retired). Varje inskickad "
                 "kortversion, väntande och avvisade, och vårdens granskningsbeslut "
                 "finns i cdr1 (avsnittet endorsements, #1044/#1049), inte i eps.",
                 source_of_rest="cdr1.pdhc"),
        _section("conditions", "Diagnoser (EPS-sammanfattning)",
                 _clinical_items(by_cat.get("conditions", [])),
                 "Diagnoser i EPS, alla versioner. cdr_backed säger om en CDR-post "
                 "ligger bakom (#984/#985); CDR är journalen."),
        _section("summary", "Övrig EPS-sammanfattning",
                 _clinical_items(by_cat.get("summary", []) + stray),
                 "Allergier, läkemedel, vaccinationer, åtgärder, produkter, "
                 "observationer m.m. i EPS, alla versioner."),
        _eps_documents(pi),
        _eps_deliveries(pi),
    ]
    notes = [
        "Inga versioner är utelämnade: fhir_resources sparar varje version; "
        "övriga tabeller i eps saknar versionshistorik och visas i en version "
        "med radens egna händelser (se note_sv per avsnitt).",
        "Vem som läst eller ändrat uppgifterna i eps ingår inte här; den valbara "
        "delen hämtas från GET /api/v1/audit/patients/<guid> (D10, #1045).",
        "patient_state_facts (en härledd tidsaxelprojektion, #895) tas inte med; "
        "varje uppgift i den finns i sitt källavsnitt.",
    ]
    return {
        "schema": SCHEMA,
        "service": SERVICE,
        "patient_guid": str(pi.guid),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "complete": True,
        "sections": sections,
        "notes": notes,
    }


# -------------------------------------------------------------------- access

def d9_allows(patient_guid: str, blob: dict | None) -> bool:
    """D9: an SU, or a doctor or nurse AFFILIATED (sso `affiliations`, role
    doctor/nurse) to an active care unit where the patient is actively
    listed. Applied ON TOP of `patient_export.exportable`, the platform's
    patient-scope rule: an extract is a stricter question than a read."""
    from app.services import patient_export as px
    if px.is_admin():
        return True
    if not blob or blob.get("user_type") != "professional":
        return False
    units = {str(a.get("care_unit_guid")).strip().lower()
             for a in blob.get("affiliations") or []
             if isinstance(a, dict) and a.get("care_unit_guid")
             and str(a.get("role") or "").lower() in EXTRACT_ROLES}
    if not units:
        return False
    hit = (PatientClinicAssignment.active_only(
               db.session.query(PatientClinicAssignment.guid)
               .join(Clinic, Clinic.guid == PatientClinicAssignment.clinic_guid)
               .filter(PatientClinicAssignment.patient_guid == patient_guid))
           .filter(Clinic.is_active.is_(True))
           .filter(db.func.lower(Clinic.organisation_guid).in_(sorted(units)))
           .first())
    return hit is not None
