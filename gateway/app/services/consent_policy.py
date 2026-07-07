"""Canonical analysis-phase consent policy (access-model reform #422).

The three D1 patient consent flags (#404) live in ips PatientDB, so ips is the
consent OWNER — and therefore owns the *enforcement* policy too. Analysis
services (analyse.pdhc, rosetta, cdr2-6) call the ``/api/v1/patients/
analysis-filter`` endpoint that applies this module, rather than each
re-implementing the rules. Keeping the legal logic in exactly one place is a
legal-correctness safeguard: there is no way for two consumers to enforce
different rules.

Rules are keyed on the read ``purpose`` (closed enum, see
plans/pdhc_data_shapes.md §5):

1. **EHDS opt-out** — ``ehds_opt_out`` blocks any analysis SECONDARY-USE read
   (research · statistics · quality_assurance · quality_registry). Primary-use
   purposes (care · care_coordination · patient_access · administration) are
   not secondary use and are unaffected by this flag.
2. **Research consent** — for ``purpose == 'research'`` the patient must have
   consented to at least one of the reader's research projects (intersection
   of ``consented_research_projects`` with the reader's affiliation
   ``research_project_guids``). No overlap → excluded. A patient with no
   recorded consent (incl. one absent from ips) is therefore excluded from
   research — consent is a positive act.
3. **Quality-registry opt-out** — ``quality_registry_opt_out`` blocks
   ``purpose == 'quality_registry'`` reads (checked before any external report).
"""

# Analysis secondary-use purposes that an EHDS opt-out withdraws the patient
# from. Primary-use purposes are deliberately excluded from this set.
EHDS_SECONDARY_PURPOSES = frozenset({
    "research", "statistics", "quality_assurance", "quality_registry",
})


def evaluate_patient(flags, purpose, reader_research_project_guids=None):
    """Decide whether one patient's data may be read for ``purpose``.

    Args:
        flags: dict of the patient's D1 consent flags — ``ehds_opt_out``,
            ``quality_registry_opt_out``, ``consented_research_projects``.
            Missing keys default to the safe value (opt-outs False, consent
            empty), so an absent/unknown patient is treated as "no opt-out,
            no research consent".
        purpose: the read purpose (closed enum).
        reader_research_project_guids: the reader's affiliation research
            projects (only consulted for research purpose).

    Returns:
        (allowed: bool, reason: str | None) — reason is the exclusion code
        when allowed is False, else None.
    """
    ehds_opt_out = bool(flags.get("ehds_opt_out"))
    qreg_opt_out = bool(flags.get("quality_registry_opt_out"))
    consented = set(flags.get("consented_research_projects") or [])

    if ehds_opt_out and purpose in EHDS_SECONDARY_PURPOSES:
        return False, "ehds_opt_out"
    if purpose == "quality_registry" and qreg_opt_out:
        return False, "quality_registry_opt_out"
    if purpose == "research":
        reader_projects = set(reader_research_project_guids or [])
        if not (consented & reader_projects):
            return False, "no_research_consent"
    return True, None
