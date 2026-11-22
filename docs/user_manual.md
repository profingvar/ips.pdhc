# EPS (eps.pdhc) — User Manual

> **Renamed 2026-11-22 (#1015).** ips.pdhc is now **eps.pdhc**, at
> <https://eps.pdhc.se>; `ips.pdhc.se` no longer resolves. Only the name and
> address changed: the containers (`ips-app-1`, `ips-db-1`), the database
> (`ips_db`), the server directory (`/usr/local/www/pdhcips/`) and stored
> identifiers keep `ips` on purpose. "IPS card" below is the document type
> (International Patient Summary), not the service.

This is the manual for people who **use** eps.pdhc through its web interface.
For how the service works internally, and for integrating another service with
it, see the technical manual.

> **New file, 2026-10-08.** ips.pdhc had no user manual, and pdhc.se was
> publishing its *spärr operator runbook* in the "layman's manual" slot — a
> narrow operational procedure standing in for a guide to the service. The
> runbook is still the right document for a spärr question and is referenced
> below.

---

## 1) What this service is for

eps.pdhc holds **the platform's patient registry**. Every other PDHC service
refers to a patient by a GUID that originates here.

Three questions can only be answered here, and other services ask them
constantly:

- **Does this patient exist, and which clinic are they assigned to?**
- **Is this patient's data from a given clinic blocked?** (*spärr* — a patient's
  legal right under Patientdatalagen to hide records from other care units.)
- **May this patient's data be used for a given analysis purpose?**

It also assembles **International Patient Summary** documents — the portable
summary of a patient's allergies, conditions, medications and so on.

In PDHC a **clinic** is an organisation. The words are used interchangeably in
the interface; a patient is assigned to a clinic, and that assignment is what
decides who may see their data.

---

## 2) Signing in

eps.pdhc uses PDHC SSO. Opening the service redirects you to sso.pdhc and
returns you signed in.

Every page carries the platform ribbon in the top left:

    PDHC / eps.pdhc

`PDHC` returns you to the service index at <https://www.pdhc.se/services.html>.

The four sections in the navigation bar are **Dashboard**, **Patients**,
**Push Monitor** and **Docs**.

---

## 3) Patients

### Finding a patient

**Patients** lists every patient in the registry with their identifier, name,
birth date and assigned clinic. A patient's own page shows their clinical
resources grouped by euIPS section, their blocks and their consents.

### Adding one patient

The admin form creates the patient **and the clinic assignment together**.
Both are required: a patient with no assignment is invisible to every
organisation-scoped reader, which in practice means the data has been collected
and then cannot be read by whoever collected it.

### Generating a cohort

For testing and demonstration, the generator creates up to 150 synthetic
patients for a chosen clinic.

**What you get per patient:**

| always | in full mode only |
|---|---|
| a valid Swedish personnummer | the three euIPS **required** sections |
| a clinic assignment | the four **recommended** sections |
| contact person (and a guardian, if a minor) | the seven **optional** sections |
| health insurance (regional public cover) | the three **EU addition** sections |
| document language | an IPS card and a rendered snapshot |

**`Skip clinical data`** creates the patient, the assignment and the document
header only. Use it when sim.pdhc will supply the clinical data, so that the
observations have one source rather than two. The euIPS *required* sections are
still written, as explicit "none known" statements — the guideline forbids a
required section from being empty, and a patient waiting for data is not a
reason to create a non-conformant summary in the meantime.

**The confirmation message reports conformance, not row counts.** It says how
many of the patients carry all three required sections either as content or as
an explicit "none known" statement, because *"are these valid patient
summaries"* is the question worth answering.

### Batches, and undoing a generation

Every generate run stamps **one batch GUID** on the patients it creates, shown
in the confirmation message and listed on the dashboard. A batch can be purged
as a unit.

That is the only clean way to undo a generation. Without it the alternative is
recording GUIDs by hand, so **note the batch GUID if you may want the cohort
gone again** — particularly before generating a large one.

### euIPS status

A patient's page reports each of the 17 euIPS sections as:

| status | meaning |
|---|---|
| **Present** | the section has content |
| **Explicitly absent** | the section states "none known" — which the guideline requires, and is *not* a gap |
| **Missing** | the section says nothing at all |

The distinction between the middle and last rows is the point. "No allergies
recorded" and "the clinician confirmed there are no known allergies" are
different clinical statements, and before this work they were indistinguishable.

**`conformant` is not a claim of EU conformance**, and the service says so on
every response. The EHDS implementing acts were not confirmed adopted as of
October 2026 and the section codes are not verified against a published
implementation guide. It means "every required section is present or explicitly
absent" — useful, and narrower than it sounds.

---

### What the patient reported (#1044)

A patient can report allergies, medication, previous illnesses, vaccinations
and contact persons in the patient app. None of it appears in the summary
until a physician or nurse at the patient's care unit has approved it in the
dashboard queue "EPS att granska". A rejected or not yet reviewed answer never
appears here.

An approved answer is shown as an ordinary entry with three differences:

- the text is the patient's own words (or the reviewer's amended wording),
  with no code;
- the entry says it came from the patient and names who approved it and when;
- the reviewer is listed as an attester of the summary document.

A previous illness reported by the patient is listed under past illnesses,
not in the problem list. Diagnoses come from care only.

Approved answers reach eps.pdhc when an administrator runs the derivation
(`flask derive-patient-reported-from-cdr`, technical manual section 6b); it is
not automatic. The run reports answers it could not place (`unattached`) and
entries whose approval is no longer in the CDR export (`orphaned`). Neither is
removed or guessed; someone has to look at them.

## 4) Spärr (patient blocks)

A spärr is a patient's decision to hide their records at one care unit from
others. It is a legal instrument, not a preference setting.

**Day-to-day spärr procedures — registering, lifting, extending, emergency
access — are in `docs/sparr_operator_runbook.md`.** That document carries the
clinical-lead and legal sign-offs and is the authority; this manual does not
duplicate it.

Two things are worth knowing here:

- A **vårdenhet** (care unit) is the *spärrgräns* — the boundary a block applies
  across. Which unit a clinic sits under is therefore a legal fact, not a
  label, and moving one changes which records a block hides.
- `Indispensable care` lifts are applied **mechanically** by consuming services,
  from the concepts and dates on the lift. A `consent` lift is a human decision
  and is not applied automatically.

---

## 5) Push Monitor

ips can push a patient summary to an external destination. **Push Monitor**
lists the configured destinations and the job history, with each job's status
and outcome. Use it to answer "did that summary actually leave".

---

## 6) Docs

**Docs** serves this manual and the other documents in the repository. The
files are also downloadable directly from `/docs/download/<name>`.

---

## 7) Things worth knowing before you change data

- **28 of 150 patients currently have no clinic assignment.** They are invisible
  to organisation-scoped readers. This is a known gap, not a display problem.
- **All assigned patients are currently in one clinic.** Any view or filter that
  scopes by organisation cannot be meaningfully tested against this population —
  it will look correct whether or not it is.
- **Generated data is synthetic but it is real data to every other service.** It
  flows to cdr_6 and analyse and is subject to the same spärr and consent
  decisions as anything else. Purge a batch you did not mean to create.
- **A contact person and an insurance policy are statements about a person.**
  The header backfill writes them, which is why it is a deliberate, dry-run-by-
  default command and not something that happens on deploy.
