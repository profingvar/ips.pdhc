"""Patientkort — the view-model behind the shared patient card.

The operator asked (2026-11-25) for ONE look for the patient card in eps,
dashboard.pdhc and record.pdhc, starting in eps, and for every item on it to
say on mouseover WHERE it is stored, HOW it came about and its HISTORY. The
platform convention is per-repo copies, not a shared library (CLAUDE.md §4),
so the card is three files that travel together:

    app/services/patientkort_view.py      this module (pure: no Flask, no DB)
    app/templates/_patientkort.html       the Jinja partial; reads `pk` only
    static/css/patientkort.css            `pk-` prefixed styles, own tokens

A port copies all three and builds the SAME input from its own data. Nothing
in the partial reaches outside `pk`, so a port never has to fake eps models.
`collect()` in eps's admin module is the eps-specific half that turns models
into the plain input below; a port writes its own.

PURE BY DESIGN. `build()` takes plain dicts and lists and returns a plain
dict. It does no I/O, reads the clock only when `today` is omitted, and logs
nothing — a personnummer passes through it, and the card must never be a
place one reaches a log. No pop-out ever carries a personnummer or any other
field VALUE: history says WHICH fields changed, never from what to what.

HONESTY RULE. Provenance is built only from what eps records — resource
versions, audit rows, provenance tags, the endorsement extension, the
generation batch, assignment rows. Where eps records nothing the output says
so (`origin` empty, `who` None) and the partial renders "uppgift saknas i
eps". Nothing is inferred from timing or naming.

INPUT
-----

    patient = {
        "guid": str,                       # required — patient_index.guid
        "fhir_id": str | None,             # FHIR Patient.id
        "family_name", "given_name": str | None,
        "birth_date": date | "YYYY-MM-DD" | None,
        "gender": "female" | "male" | "other" | "unknown" | None,
        "identifier_value": str | None,    # personnummer, any accepted form
        "is_active": bool,                 # default True
        "archived": bool,                  # default False
        "created_at": datetime | str | None,   # patient_index.created_at
        "batch_guid": str | None,          # set only by eps's mock_generator
    }
    units = [{                             # OPEN care-unit assignments
        "guid": str,                       # the assignment row
        "name": str,                       # the vårdenhet
        "caregiver_name": str | None,      # the vårdgivare; None = unknown
        "is_own_caregiver": bool,          # the unit IS the vårdgivare
        "since": date | datetime | str | None,
        "clinic_guid", "unit_org_guid", "caregiver_org_guid": str | None,
        "origin": str | None,              # self_registered | invited | None
    }]
    sections = euips_summary.compose(rows)   # or None = could not be read
    blocks = [{"guid", "active": bool, "scope_type", "created_at",
               "created_by", "expires_at", "lifted_at", "lift_kind",
               "lift_expires_at"}] | None          # None = unknown
    consents = [{"guid", "active": bool, "granted_at", "granted_by",
                 "granted_via", "expires_at", "revoked_at"}] | None
    records = {                            # provenance sources, all optional
        "service": "eps.pdhc",
        "patient":   {"versions": [V], "audits": [A]},   # FHIR Patient
        "resources": {"<Type>/<id>": {"versions": [V], "audits": [A]}},
        "assignments": [{"guid", "clinic_name", "assigned_at", "ended_at",
                         "origin"}],                    # incl. ended ones
        "assignment_audits": [A],
    }
      V = {"guid", "version_id": int, "status": active|superseded|retired,
           "created_at", "resource_json": dict}
      A = {"event_type", "at", "actor_type", "actor_label",
           "resource_guid", "detail": dict}
    today = date; now is not needed.

OUTPUT — the `pk` dict the partial renders
-------------------------------------------

    {
      "name", "age_text", "sex_text", "birth_date",
      "personnummer": {"text": str | None, "synthetic": bool},
      "fields": [{"label", "value", "mono": bool, "tag": str | None,
                  "prov": P}],                 # Ålder/Kön/Personnummer/...
      "units":  [{"name", "caregiver_name", "is_own_caregiver", "since",
                  "prov": P}],
      "banners": [{"kind", "level": danger|warning|info, "text",
                   "prov": P | None}],
      "diagnoses": [{"code", "display", "system_label", "status_text",
                     "active", "cdr_backed", "cdr_name", "date", "prov": P}],
      "diagnoses_state": "ok" | "unavailable",
      "diagnosis_note": str | None,
      "sections": [{"key", "title", "count", "state": present|absent|missing,
                    "priority": bool, "entries": [{"display", "meta",
                    "prov": P}], "absent_text": str | None}],
      "sections_state": "ok" | "unavailable",
      "empty_sections": [str],
      "entries_shown": int,
      "ids": {"guid", "fhir_id"},
    }

    P (one pop-out) = {
      "id": "pk-p-<n>",                       # unique on the page
      "title": str,                           # what the item is
      "stored": [{"where": "eps.pdhc · FHIR Condition", "id": str | None}],
      "origin": [{"text", "who": str | None, "at": str | None}],
      "history": [{"at": str | None, "who": str | None, "text": str}],
      "history_more": int,                    # older entries not shown
    }
    `origin == []` and `who is None` mean "uppgift saknas i eps".
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable

PRESENT = "PRESENT"
EXPLICITLY_ABSENT = "EXPLICITLY_ABSENT"
SERVICE = "eps.pdhc"

#: Swedish titles, in display order. Always shown, with an honest empty state.
CORE_SECTIONS: tuple[tuple[str, str], ...] = (
    ("alerts", "Varningar"),
    ("allergies", "Allergier och intoleranser"),
    ("medications", "Läkemedel"),
    ("immunisations", "Vaccinationer"),
    ("diagnostic_results", "Resultat"),
    ("vital_signs", "Vitalparametrar"),
    ("procedures", "Åtgärder"),
    ("devices", "Implantat och hjälpmedel"),
)

#: Shown only when they hold something; otherwise named once in a line.
OTHER_SECTIONS: dict[str, str] = {
    "pregnancy": "Graviditet",
    "social_history": "Social anamnes",
    "functional_status": "Funktionsstatus",
    "plan_of_care": "Vårdplan",
    "advance_directives": "Viljeyttringar",
    "travel_history": "Resor",
    "patient_provided": "Patientens egna uppgifter",
}

PRIORITY = frozenset({"alerts", "allergies"})
DIAGNOSIS_SECTIONS = ("problems", "past_illnesses")
ENTRIES_SHOWN = 5
HISTORY_SHOWN = 6

_SEX = {"female": "Kvinna", "male": "Man", "other": "Annat", "unknown": "Okänt"}

_STATUS = {
    "active": "aktiv", "inactive": "inaktiv", "resolved": "läkt",
    "remission": "i remission", "recurrence": "återfall", "relapse": "återfall",
    "completed": "avslutad", "stopped": "avbruten", "on-hold": "vilande",
    "intended": "planerad", "not-taken": "ej tagen", "final": "slutlig",
    "preliminary": "preliminär", "amended": "ändrad",
    "entered-in-error": "felregistrerad", "not-done": "ej utförd",
    "in-progress": "pågående", "recorded": "registrerad",
}

_SYSTEM = {
    "http://snomed.info/sct": "SNOMED CT",
    "https://termbank.pdhc.se/CodeSystem/snomed": "SNOMED CT",
    "http://id.who.int/icd/release/11/mms": "ICD-11 MMS",
    "https://termbank.pdhc.se/CodeSystem/icd11-mms": "ICD-11 MMS",
    "http://hl7.org/fhir/sid/icd-10": "ICD-10",
    "http://loinc.org": "LOINC",
    "http://www.whocc.no/atc": "ATC",
}

#: Audit events that WRITE something, in Swedish. Reads (summary, export,
#: access log) are not provenance and are left out.
_EVENT = {
    "fhir_create": "Skapad via FHIR-API:t",
    "fhir_update": "Ändrad via FHIR-API:t",
    "clinic_patient_create": "Skapad via klinik-API:t",
    "patient_cohort_generate": "Genererad kohort via klinik-API:t",
    "patient_self_registered": "Patienten registrerade sig själv i patientappen",
    "patient_registered_at_unit": "Registrerad vid vårdenhet via inbjudan",
    "patient.assigned": "Kopplad till vårdenhet",
    "patient.assignment_ended": "Koppling till vårdenhet avslutad",
}

#: FHIR element -> what a reader calls it. Only the NAME of a changed field is
#: ever shown, never its value.
_FIELD = {
    "name": "namn", "birthDate": "födelsedatum", "gender": "kön",
    "identifier": "identifierare", "active": "aktiv-flagga", "meta": "metadata",
    "text": "narrativ", "extension": "tillägg", "code": "kod",
    "clinicalStatus": "klinisk status", "verificationStatus": "verifiering",
    "onsetDateTime": "debut", "abatementDateTime": "avslut",
    "recordedDate": "registreringsdatum", "status": "status",
    "medication": "läkemedel", "medicationCodeableConcept": "läkemedel",
    "valueQuantity": "värde", "effectiveDateTime": "tidpunkt",
    "vaccineCode": "vaccin", "reaction": "reaktion", "category": "kategori",
    "subject": "patientreferens", "patient": "patientreferens",
    "participant": "deltagare", "address": "adress", "telecom": "kontaktuppgift",
}

_PROV_SYSTEMS = ("https://ips.pdhc.se/CodeSystem/provenance", "urn:pdhc:provenance")
_TAG_TEXT = {
    "derived-from-cdr": "Härledd ur CDR av eps-kommandot derive-conditions-from-cdr",
    "endorsed-patient-reported": ("Rapporterad av patienten och vidimerad av vården "
                                  "(derive-patient-reported-from-cdr)"),
    "simulated": "Genererad av eps patientsimulator",
}

_ORIGIN = {"self_registered": "Patienten valde enheten vid egen registrering i patientappen",
           "invited": "Kopplad via inbjudan från enheten"}

DASH = "—"


# ── small pure helpers ──────────────────────────────────────────────────


def to_date(value: Any) -> date | None:
    """date, datetime or an ISO string -> date, else None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def stamp(value: Any) -> str | None:
    """A timestamp as "YYYY-MM-DD HH:MM" (date only when that is all there is)."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            d = to_date(value)
            return d.isoformat() if d else value
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _sort_key(value: Any) -> str:
    """Comparable key for timestamps of mixed type; missing sorts oldest."""
    s = stamp(value)
    return s or ""


def age_years(birth: Any, today: date) -> int | None:
    """Completed years on `today`; None for a missing or future birth date."""
    b = to_date(birth)
    if b is None or b > today:
        return None
    return today.year - b.year - ((today.month, today.day) < (b.month, b.day))


def format_name(family: str | None, given: str | None) -> str:
    family = (family or "").strip()
    given = (given or "").strip()
    if not family and not given:
        return "Namn saknas"
    return f"{family or DASH}, {given or DASH}"


def format_personnummer(value: str | None) -> dict:
    """{"text": "YYYYMMDD-NNNN" | raw | None, "synthetic": bool}.

    Uses eps's own personnummer module. A port without one may pass the value
    through and set `synthetic` False; the partial copes.
    """
    if not value or not str(value).strip():
        return {"text": None, "synthetic": False}
    from app.services import personnummer as pnr
    norm = pnr.normalise(str(value))
    if norm is None:
        return {"text": str(value).strip(), "synthetic": False}
    return {"text": norm, "synthetic": pnr.classify(norm) == "synthetic"}


def status_text(status: str | None) -> str | None:
    if not status:
        return None
    return _STATUS.get(str(status).lower(), str(status))


def system_label(system: str | None) -> str | None:
    if not system:
        return None
    return _SYSTEM.get(system, system)


def _value_text(e: dict) -> str | None:
    v = e.get("value")
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        v = "ja" if v else "nej"
    elif isinstance(v, float):
        v = f"{v:g}"
    unit = e.get("unit")
    # UCUM "1" is the dimensionless unit: printing it reads as a second number.
    return f"{v} {unit}" if unit and unit != "1" else str(v)


# ── provenance ──────────────────────────────────────────────────────────


def who_text(audit: dict) -> str | None:
    """Who an audit row says acted, or None when it says nothing useful."""
    label = (audit.get("actor_label") or "").strip()
    kind = (audit.get("actor_type") or "").strip()
    if label:
        return f"{label} ({kind})" if kind and kind not in label else label
    if kind and kind != "system":
        return kind
    if kind == "system":
        return "systemet (ingen inloggad aktör)"
    return None


def provenance_tags(resource_json: dict | None) -> list[str]:
    """The PDHC provenance tag codes on a resource, in order."""
    meta = (resource_json or {}).get("meta") or {}
    return [t.get("code") for t in meta.get("tag") or []
            if isinstance(t, dict) and t.get("system") in _PROV_SYSTEMS and t.get("code")]


def changed_fields(old: dict | None, new: dict | None) -> list[str]:
    """Top-level FHIR elements that differ between two versions, by NAME."""
    old, new = old or {}, new or {}
    keys = sorted((set(old) | set(new)) - {"id", "resourceType"})
    return [_FIELD.get(k, k) for k in keys if old.get(k) != new.get(k)]


def _cap(items: list[dict], n: int = HISTORY_SHOWN) -> tuple[list[dict], int]:
    return items[:n], max(0, len(items) - n)


def version_history(versions: list[dict], audits: list[dict], *,
                    only: Iterable[str] | None = None) -> list[dict]:
    """One history line per stored version, newest first.

    `only` restricts to versions that changed one of these FHIR elements
    (plus the first version), for a single field such as Patient.gender.
    A version's actor comes from the audit row whose `resource_guid` is that
    version's row guid; with none, `who` is None ("uppgift saknas i eps").
    """
    by_guid: dict[str, dict] = {}
    for a in audits or []:
        if a.get("resource_guid"):
            by_guid.setdefault(str(a["resource_guid"]), a)
    vs = sorted(versions or [], key=lambda v: int(v.get("version_id") or 0))
    only = set(only) if only else None
    out = []
    prev = None
    for v in vs:
        rj = v.get("resource_json") if isinstance(v.get("resource_json"), dict) else {}
        n = v.get("version_id")
        a = by_guid.get(str(v.get("guid")))
        if v.get("status") == "retired":
            text = f"Version {n}: tagen ur bruk (finns kvar, visas inte)"
        elif prev is None:
            text = f"Version {n}: skapad"
        else:
            ch = changed_fields(prev, rj)
            if only is not None:
                ch_only = [c for c in ch if c in {_FIELD.get(k, k) for k in only}]
                if not ch_only:
                    prev = rj
                    continue
                ch = ch_only
            text = f"Version {n}: " + (("ändrat " + ", ".join(ch)) if ch
                                       else "ny version utan innehållsändring")
            new_tags = set(provenance_tags(rj)) - set(provenance_tags(prev))
            for t in sorted(new_tags):
                if t in _TAG_TEXT:
                    text += f" — {_TAG_TEXT[t][0].lower()}{_TAG_TEXT[t][1:]}"
        if a:
            ev = _EVENT.get(a.get("event_type"), a.get("event_type")) or ""
            text += f" ({ev[:1].lower()}{ev[1:]})"
        out.append({"at": stamp(v.get("created_at")), "who": who_text(a) if a else None,
                    "text": text})
        prev = rj
    out.reverse()
    return out


def resource_origin(versions: list[dict], audits: list[dict],
                    endorsement: dict | None = None) -> list[dict]:
    """How a FHIR resource came about, from what eps records."""
    vs = sorted(versions or [], key=lambda v: int(v.get("version_id") or 0))
    out: list[dict] = []
    if not vs:
        return out
    first = vs[0]
    first_rj = first.get("resource_json") if isinstance(first.get("resource_json"), dict) else {}
    creating = [a for a in audits or []
                if str(a.get("resource_guid")) == str(first.get("guid"))]
    for a in creating:
        out.append({"text": _EVENT.get(a.get("event_type"), a.get("event_type")),
                    "who": who_text(a), "at": stamp(a.get("at"))})
    for t in provenance_tags(first_rj):
        if t in _TAG_TEXT:
            out.append({"text": _TAG_TEXT[t], "who": None,
                        "at": stamp(first.get("created_at"))})
    if endorsement:
        for e in endorsement.get("endorsed_by") or []:
            out.append({"text": "Vidimerad av vården (patienten är uppgiftslämnare)",
                        "who": e.get("name") or e.get("user_guid"),
                        "at": stamp(e.get("at"))})
    if not out:
        # Nothing names the writer. Say when the row was written, and that eps
        # does not record by whom or how.
        out.append({"text": "Skapad i eps — hur och av vem registreras inte för denna post",
                    "who": None, "at": stamp(first.get("created_at"))})
    return out


def patient_origin(patient: dict, audits: list[dict]) -> list[dict]:
    out = []
    for a in audits or []:
        if a.get("event_type") in ("fhir_create", "clinic_patient_create",
                                   "patient_self_registered",
                                   "patient_registered_at_unit"):
            out.append({"text": _EVENT[a["event_type"]], "who": who_text(a),
                        "at": stamp(a.get("at"))})
    if patient.get("batch_guid"):
        out.append({"text": ("Genererad av eps mock_generator (generate-patients "
                             f"eller admin), batch {patient['batch_guid']}"),
                    "who": None, "at": stamp(patient.get("created_at"))})
    if not out and patient.get("created_at"):
        out.append({"text": "Skapad i eps — hur och av vem registreras inte för denna patient",
                    "who": None, "at": stamp(patient.get("created_at"))})
    return out


class _Ids:
    def __init__(self):
        self.n = 0

    def __call__(self) -> str:
        self.n += 1
        return f"pk-p-{self.n}"


def _p(ids: _Ids, title: str, stored: list[dict], origin: list[dict],
       history: list[dict]) -> dict:
    shown, more = _cap(history)
    return {"id": ids(), "title": title, "stored": stored, "origin": origin,
            "history": shown, "history_more": more}


def _resource_prov(ids: _Ids, title: str, e: dict, records: dict) -> dict:
    rtype = e.get("resource_type") or "Resource"
    rid = e.get("resource_id")
    rec = (records.get("resources") or {}).get(f"{rtype}/{rid}") or {}
    stored = [{"where": f"{records.get('service') or SERVICE} · FHIR {rtype}", "id": rid}]
    cdr = e.get("cdr") if e.get("cdr_backed") else None
    if cdr:
        stored.append({"where": f"{cdr.get('name') or 'CDR (namn ej angivet)'} · {rtype}",
                       "id": cdr.get("guid")})
    versions = rec.get("versions") or []
    audits = rec.get("audits") or []
    return _p(ids, title, stored,
              resource_origin(versions, audits, e.get("provenance")),
              version_history(versions, audits))


# ── views ───────────────────────────────────────────────────────────────


def _entry_view(ids: _Ids, e: dict, section_title: str, records: dict) -> dict:
    d = to_date(e.get("date"))
    meta = [x for x in (_value_text(e), d.isoformat() if d else None,
                        status_text(e.get("status"))) if x]
    display = e.get("display") or e.get("code") or "Namnlös post"
    return {"display": display, "meta": " · ".join(meta),
            "prov": _resource_prov(ids, f"{section_title}: {display}", e, records)}


def _diagnosis_view(ids: _Ids, e: dict, records: dict) -> dict:
    status = (e.get("status") or "").lower() or None
    backed = bool(e.get("cdr_backed"))
    cdr_name = (e.get("cdr") or {}).get("name") if backed else None
    d = to_date(e.get("onset") or e.get("date"))
    return {
        "code": e.get("code"),
        "display": e.get("display") or e.get("code") or "Namnlös diagnos",
        "system_label": system_label(e.get("system")),
        "status_text": status_text(status),
        "active": status in (None, "active", "recurrence", "relapse"),
        "cdr_backed": backed,
        "cdr_name": cdr_name,
        "date": d.isoformat() if d else None,
        "prov": _resource_prov(ids, "Diagnos: " + (e.get("display") or e.get("code") or "namnlös"),
                               e, records),
    }


def _section_view(ids: _Ids, key: str, title: str, s: dict | None,
                  records: dict) -> dict:
    s = s or {}
    status = s.get("status")
    entries = ([_entry_view(ids, e, title, records) for e in (s.get("entries") or [])]
               if status == PRESENT else [])
    absent_text = None
    if status == EXPLICITLY_ABSENT:
        absent_text = ((s.get("absent") or {}).get("narrative_text")
                       or "Uttryckligen inga uppgifter")
    state = ("present" if entries else
             "absent" if status == EXPLICITLY_ABSENT else "missing")
    return {"key": key, "title": title, "count": len(entries), "state": state,
            "priority": key in PRIORITY, "entries": entries,
            "absent_text": absent_text}


def _assignment_audit(audits: list[dict], event_type: str, clinic_guid: Any,
                      at: Any) -> dict | None:
    """The audit row for ONE assignment start or end.

    `patient_assignment` writes the clinic guid and the row's own timestamp
    into `detail` ("assigned_at" / "ended_at"), so the match is on recorded
    values, not on proximity in time.
    """
    key = "assigned_at" if event_type == "patient.assigned" else "ended_at"
    want = stamp(at)
    for x in audits or []:
        d = x.get("detail") or {}
        if (x.get("event_type") == event_type
                and str(d.get("clinic_guid")) == str(clinic_guid)
                and want is not None and stamp(d.get(key)) == want):
            return x
    return None


def _user(guid: Any) -> str | None:
    return f"användare {guid}" if guid else None


def _assignment_history(records: dict) -> list[dict]:
    """Every assignment start and end, newest first, with the audit actor."""
    audits = records.get("assignment_audits") or []
    ev = []
    for a in records.get("assignments") or []:
        name = a.get("clinic_name") or "okänd enhet"
        ev.append((a.get("assigned_at"), f"Kopplad till {name}"
                   + (f" ({_ORIGIN[a['origin']].lower()})" if a.get("origin") in _ORIGIN else ""),
                   "patient.assigned", a))
        if a.get("ended_at"):
            ev.append((a.get("ended_at"), f"Koppling till {name} avslutad",
                       "patient.assignment_ended", a))
    out = []
    for at, text, etype, a in ev:
        match = _assignment_audit(audits, etype, a.get("clinic_guid"), at)
        # A move ends one assignment and opens the next at the same instant;
        # newest first then lists the new start above the old end.
        out.append({"at": stamp(at), "who": who_text(match) if match else None,
                    "text": text, "_k": (_sort_key(at), etype == "patient.assigned")})
    out.sort(key=lambda x: x["_k"], reverse=True)
    for x in out:
        x.pop("_k")
    return out


def _unit_view(ids: _Ids, u: dict, history: list[dict], records: dict) -> dict:
    since = to_date(u.get("since"))
    svc = records.get("service") or SERVICE
    stored = [{"where": f"{svc} · patient_clinic_assignments", "id": u.get("guid")},
              {"where": f"{svc} · clinics (vårdenhet)", "id": u.get("clinic_guid")}]
    if u.get("unit_org_guid"):
        stored.append({"where": "sso.pdhc · organisation (vårdenhet)", "id": u["unit_org_guid"]})
    if u.get("caregiver_org_guid") and u.get("caregiver_org_guid") != u.get("unit_org_guid"):
        stored.append({"where": "sso.pdhc · organisation (vårdgivare)", "id": u["caregiver_org_guid"]})
    origin = []
    if u.get("origin") in _ORIGIN:
        origin.append({"text": _ORIGIN[u["origin"]], "who": None, "at": stamp(u.get("since"))})
    match = _assignment_audit(records.get("assignment_audits") or [],
                              "patient.assigned", u.get("clinic_guid"), u.get("since"))
    if match:
        origin.append({"text": _EVENT["patient.assigned"], "who": who_text(match),
                       "at": stamp(match.get("at"))})
    if not origin:
        origin.append({"text": "Kopplad — hur och av vem registreras inte för denna koppling",
                       "who": None, "at": stamp(u.get("since"))})
    return {
        "name": u.get("name") or "Namnlös vårdenhet",
        "caregiver_name": u.get("caregiver_name"),
        "is_own_caregiver": bool(u.get("is_own_caregiver")),
        "since": since.isoformat() if since else None,
        "prov": _p(ids, "Vårdenhet och vårdgivare", stored, origin, history),
    }


def _block_prov(ids: _Ids, blocks: list[dict], svc: str) -> dict:
    stored, hist = [], []
    for b in blocks:
        stored.append({"where": f"{svc} · patient_blocks", "id": b.get("guid")})
        hist.append({"at": stamp(b.get("created_at")), "who": _user(b.get("created_by")),
                     "text": "Spärr satt" + (f" ({b['scope_type']})" if b.get("scope_type") else ""),
                     "_k": _sort_key(b.get("created_at"))})
        if b.get("lifted_at"):
            kind = {"consent": "hävd med samtycke",
                    "indispensable_care": "nödöppnad (oundgänglig vård)"}.get(
                b.get("lift_kind"), "hävd")
            hist.append({"at": stamp(b.get("lifted_at")), "who": None,
                         "text": f"Spärr {kind}", "_k": _sort_key(b.get("lifted_at"))})
    hist.sort(key=lambda x: x["_k"], reverse=True)
    for x in hist:
        x.pop("_k")
    active = [b for b in blocks if b.get("active")]
    origin = [{"text": "Spärr satt i eps", "who": _user(b.get("created_by")),
               "at": stamp(b.get("created_at"))} for b in active]
    return _p(ids, "Spärr", stored, origin, hist)


def _consent_prov(ids: _Ids, consents: list[dict], svc: str) -> dict:
    stored, hist = [], []
    for c in consents:
        stored.append({"where": f"{svc} · patient_consents", "id": c.get("guid")})
        via = f" via {c['granted_via']}" if c.get("granted_via") else ""
        hist.append({"at": stamp(c.get("granted_at")), "who": _user(c.get("granted_by")),
                     "text": f"Samtycke lämnat{via}", "_k": _sort_key(c.get("granted_at"))})
        if c.get("revoked_at"):
            hist.append({"at": stamp(c.get("revoked_at")), "who": None,
                         "text": "Samtycke återkallat", "_k": _sort_key(c.get("revoked_at"))})
    hist.sort(key=lambda x: x["_k"], reverse=True)
    for x in hist:
        x.pop("_k")
    origin = [{"text": "Samtycke lämnat" + (f" via {c['granted_via']}" if c.get("granted_via") else ""),
               "who": _user(c.get("granted_by")), "at": stamp(c.get("granted_at"))}
              for c in consents if c.get("active")]
    return _p(ids, "Samtycken", stored, origin, hist)


# ── the builder ─────────────────────────────────────────────────────────


def build(patient: dict, *, units: Iterable[dict] = (),
          sections: list[dict] | None = None,
          blocks: list[dict] | None = (), consents: list[dict] | None = (),
          records: dict | None = None, today: date | None = None) -> dict:
    """The `pk` dict for `_patientkort.html`. See the module docstring."""
    today = today or date.today()
    records = records or {}
    svc = records.get("service") or SERVICE
    ids = _Ids()

    # ---- demographics, each with where/how/history ----
    prec = records.get("patient") or {}
    pv, pa = prec.get("versions") or [], prec.get("audits") or []
    p_stored = [{"where": f"{svc} · patient_index", "id": str(patient.get("guid") or "")},
                {"where": f"{svc} · FHIR Patient", "id": patient.get("fhir_id")}]
    p_origin = patient_origin(patient, pa)

    def field_prov(title: str, elements: tuple[str, ...]) -> dict:
        return _p(ids, title, p_stored, p_origin,
                  version_history(pv, pa, only=elements))

    age = age_years(patient.get("birth_date"), today)
    birth = to_date(patient.get("birth_date"))
    gender = (patient.get("gender") or "").lower() or None
    pnr = format_personnummer(patient.get("identifier_value"))

    name_prov = field_prov("Namn", ("name",))
    fields = [
        {"label": "Ålder", "value": (f"{age} år" if age is not None else None),
         "sub": (f"född {birth.isoformat()}" if birth else None), "mono": False,
         "tag": None, "prov": field_prov("Ålder (födelsedatum)", ("birthDate",))},
        {"label": "Kön", "value": (_SEX.get(gender, gender) if gender else None),
         "sub": None, "mono": False, "tag": None,
         "prov": field_prov("Kön", ("gender",))},
        {"label": "Personnummer", "value": pnr["text"], "sub": None, "mono": True,
         "tag": "syntetiskt" if pnr["synthetic"] else None,
         "prov": field_prov("Personnummer", ("identifier",))},
    ]

    # ---- units ----
    unit_hist = _assignment_history(records)
    unit_views = [_unit_view(ids, u, unit_hist, records) for u in units or ()]

    # ---- banners ----
    banners: list[dict] = []
    if patient.get("is_active", True) is False:
        banners.append({"kind": "inactive", "level": "danger", "text": "Inaktiv patient",
                        "prov": field_prov("Aktiv-status", ("active",))})
    if patient.get("archived"):
        banners.append({"kind": "archived", "level": "info", "text": "Arkiverad i listan",
                        "prov": _p(ids, "Arkivering", [{"where": f"{svc} · patient_index.archived_at",
                                                        "id": str(patient.get("guid") or "")}],
                                   [], [])})
    if blocks is None:
        banners.append({"kind": "block", "level": "warning", "text": "Spärrstatus okänd",
                        "prov": None})
    else:
        n = sum(1 for b in blocks if b.get("active"))
        if n:
            banners.append({"kind": "block", "level": "warning",
                            "text": "Spärr aktiv" + (f" ({n})" if n > 1 else ""),
                            "prov": _block_prov(ids, list(blocks), svc)})
    if consents is None:
        banners.append({"kind": "consent", "level": "info", "text": "Samtycken okända",
                        "prov": None})
    else:
        n = sum(1 for c in consents if c.get("active"))
        if n:
            banners.append({"kind": "consent", "level": "info",
                            "text": f"{n} samtycke{'n' if n > 1 else ''} i kraft",
                            "prov": _consent_prov(ids, list(consents), svc)})
    if not unit_views:
        banners.append({"kind": "no_unit", "level": "warning",
                        "text": "Ingen vårdenhet kopplad",
                        "prov": _p(ids, "Vårdenhet", [{"where": f"{svc} · patient_clinic_assignments",
                                                       "id": None}], [], unit_hist)})

    # ---- diagnoses ----
    by_key = {s.get("key"): s for s in (sections or [])}
    diagnoses: list[dict] = []
    for k in DIAGNOSIS_SECTIONS:
        s = by_key.get(k) or {}
        if s.get("status") != PRESENT:
            continue
        for e in s.get("entries") or []:
            if (e.get("resource_type") or "Condition") == "Condition":
                diagnoses.append(_diagnosis_view(ids, e, records))
    diagnoses.sort(key=lambda d: 0 if d["active"] else 1)

    note = None
    unbacked = sum(1 for d in diagnoses if not d["cdr_backed"])
    if unbacked:
        note = (f"{unbacked} av {len(diagnoses)} "
                + ("diagnos finns" if len(diagnoses) == 1 else "diagnoser finns")
                + " bara i patientsammanfattningen och är ännu inte förankrade i någon CDR.")

    # ---- sections ----
    section_views = [_section_view(ids, k, t, by_key.get(k), records) for k, t in CORE_SECTIONS]
    empty_other = []
    for k, t in OTHER_SECTIONS.items():
        v = _section_view(ids, k, t, by_key.get(k), records)
        if v["state"] == "missing":
            empty_other.append(t)
        else:
            section_views.append(v)
    section_views.sort(key=lambda v: 0 if v["priority"] else 1)

    return {
        "name": format_name(patient.get("family_name"), patient.get("given_name")),
        "name_prov": name_prov,
        "age_text": f"{age} år" if age is not None else None,
        "sex_text": _SEX.get(gender, gender) if gender else None,
        "birth_date": birth.isoformat() if birth else None,
        "personnummer": pnr,
        "fields": fields,
        "units": unit_views,
        "banners": banners,
        "diagnoses": diagnoses,
        "diagnoses_state": "unavailable" if sections is None else "ok",
        "diagnosis_note": note,
        "sections": section_views,
        "sections_state": "unavailable" if sections is None else "ok",
        "empty_sections": empty_other,
        "entries_shown": ENTRIES_SHOWN,
        "ids": {"guid": str(patient.get("guid") or ""), "fhir_id": patient.get("fhir_id")},
    }
