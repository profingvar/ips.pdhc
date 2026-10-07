"""#799 — euIPS completeness reporting, and what it refuses to claim.

Answers, per patient and per batch: **is this a valid EU Patient Summary, and
if not, which header is missing?**

## What it refuses to say

It does not claim regulatory conformance, and the refusal is deliberate rather
than cautious boilerplate. `docs/EU_Patient_Summary_ICD11.docx` states that the
EHDS implementing acts carrying the technical specifications for the exchange
format were **not confirmed adopted** as of October 2026, with the
patient-summary format act expected around September 2026 and a member-state
vote on classifications in June 2026. On top of that,
`euips_sections.CODES_VERIFIED` is False: the LOINC section codes and the IPS
absent/unknown codes are written from knowledge of the IG, not from a fetch of
the published CodeSystem.

So the verdict is phrased as **"all required sections present"**, never
"EU-conformant". A tool that prints the second against a specification that is
not finally adopted is worse than one that prints the first, because the second
is a claim somebody may repeat in a technical file — and #783 exists because
this platform has already been bitten by a status being reported more
confidently than it was known.

## What counts as a failure

**Only a MISSING required section.** That is what "required" means, and it is
the single thing that makes a summary invalid.

A MISSING *recommended* or *optional* section is **not** a failure, and #794
established why: those sections may legitimately be absent, and the generator
produces that outcome on purpose. Reporting them as failures would make a
correct cohort look broken and would train the reader to ignore the output.

They are reported as information, because "no immunisations recorded anywhere"
is worth seeing even though it is not an error.
"""
from __future__ import annotations

from app.models.base import db
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex
from app.services import euips_sections as euips

#: Said in every output, not left to a docstring. See the module header.
DISCLAIMER = (
    "Checks the section obligations described in "
    "docs/EU_Patient_Summary_ICD11.docx. NOT a claim of EU or EHDS "
    "conformance: the implementing acts were not confirmed adopted as of "
    "October 2026, and the section codes are not yet verified against the "
    "published IPS implementation guide."
)


def status_for_patient(patient: PatientIndex) -> dict[str, str]:
    rows = (db.session.query(FhirResource)
            .filter(FhirResource.patient_guid == patient.guid).all())
    return euips.status_for_resources(rows)


def report(batch_guid=None, *, failure_limit: int = 10) -> dict:
    """Section coverage across the database, or across one batch.

    `failures` lists only patients with a MISSING REQUIRED section, capped --
    a report that prints 110 identical lines is not more informative than one
    that prints ten and says how many more there are.
    """
    q = db.session.query(PatientIndex)
    if batch_guid:
        q = q.filter(PatientIndex.generation_batch_guid == batch_guid)
    patients = q.all()

    # section -> status -> count
    matrix: dict[str, dict[str, int]] = {
        s.key: {euips.PRESENT: 0, euips.EXPLICITLY_ABSENT: 0, euips.MISSING: 0}
        for s in euips.SECTIONS
    }
    conformant = 0
    failures: list[dict] = []
    empty = 0

    for p in patients:
        st = status_for_patient(p)
        for key, state in st.items():
            matrix[key][state] += 1
        if euips.is_conformant(st):
            conformant += 1
        else:
            missing = [k for k in euips.REQUIRED_KEYS
                       if st[k] == euips.MISSING]
            if len(failures) < failure_limit:
                failures.append({
                    "patient_guid": str(p.guid),
                    "name": " ".join(filter(None, [p.given_name, p.family_name])),
                    "missing_required": missing,
                })
        if all(v == euips.MISSING for v in st.values()):
            empty += 1

    total = len(patients)
    return {
        "scope": f"batch {batch_guid}" if batch_guid else "all patients",
        "patients": total,
        "conformant": conformant,
        "not_conformant": total - conformant,
        "no_content_in_any_section": empty,
        "by_obligation": {
            lvl: {
                s.key: matrix[s.key]
                for s in euips.SECTIONS if s.obligation == lvl
            }
            for lvl in euips.OBLIGATION_ORDER
        },
        "failures": failures,
        "failures_truncated": max(0, (total - conformant) - len(failures)),
        "codes_verified": euips.CODES_VERIFIED,
        "disclaimer": DISCLAIMER,
    }


def format_report(r: dict) -> str:
    """Human-readable. Obligation level is the organising axis, because that
    is what decides whether a MISSING section matters."""
    out: list[str] = []
    out.append(f"euIPS section coverage — {r['scope']}")
    out.append("")
    out.append(f"  patients                      : {r['patients']}")
    out.append(f"  all required sections present  : {r['conformant']}"
               f"{'' if not r['patients'] else '  (%.0f%%)' % (100 * r['conformant'] / r['patients'])}")
    out.append(f"  missing a required section     : {r['not_conformant']}")
    out.append(f"  no content in ANY section      : {r['no_content_in_any_section']}")
    out.append("")

    titles = {
        euips.REQUIRED: "REQUIRED — a MISSING section here is a FAILURE",
        euips.RECOMMENDED: "RECOMMENDED — MISSING is permitted, not a failure",
        euips.OPTIONAL: "OPTIONAL — MISSING is permitted, not a failure",
        euips.EU_ADDITION: "EU ADDITIONS — MISSING is permitted, not a failure",
    }
    for lvl in euips.OBLIGATION_ORDER:
        sections = r["by_obligation"].get(lvl) or {}
        if not sections:
            continue
        out.append(f"  {titles[lvl]}")
        out.append(f"    {'section':<22} {'present':>8} {'absent':>8} {'missing':>8}")
        for key, counts in sections.items():
            out.append(f"    {key:<22} {counts[euips.PRESENT]:>8} "
                       f"{counts[euips.EXPLICITLY_ABSENT]:>8} "
                       f"{counts[euips.MISSING]:>8}")
        out.append("")

    if r["failures"]:
        out.append("  patients missing a REQUIRED section:")
        for f in r["failures"]:
            out.append(f"    {f['patient_guid']}  {f['name'] or '(no name)':<28} "
                       f"missing: {', '.join(f['missing_required'])}")
        if r["failures_truncated"]:
            out.append(f"    … and {r['failures_truncated']} more")
        out.append("")

    out.append(f"  codes verified against the published IG: {r['codes_verified']}")
    out.append("")
    # Wrapped by hand so the caveat reads as prose rather than one long line.
    out.append("  " + DISCLAIMER.replace(". ", ".\n  "))
    return "\n".join(out)
