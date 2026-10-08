
## #792 — euIPS document header (2026-10-08)

Phase B2. `app/services/euips_header.py` + `euips_header_backfill.py`,
`GET /api/v1/patients/<guid>/euips-header`, wired into `ips_generator` and the
mock generator. DEPLOYED.

### The watch item drove the design

#792 flags that the Composition custodian, the Patient's
`managingOrganization` and the `PatientClinicAssignment` row are three places
holding ONE organisation — the #768 shape, where three organisation
identifiers on one datapoint failed to collapse and a Rule 24 gate scoped on
the wrong org.

**THE ASSIGNMENT IS AUTHORITATIVE.** `_custodian_clinic` reads it from
`PatientClinicAssignment` — what cross-service consumers actually query, since
`/api/v1/clinics/<guid>/patients` joins on that table and not on
`managingOrganization` — and custodian, author and attester are projections of
it. A stale `managingOrganization` does not win, and is not swallowed either:
`custodian_disagreement` surfaces it as a bundle `meta.tag` and as
`custodian_mismatch` in the endpoint. #768 happened because a mismatch was
invisible; preferring the right source silently is only half a fix.

No assignment ⇒ no custodian, author or attester. An unattributed document is
correct; an invented attribution is not.

### Decisions a reviewer should push back on if they disagree

- **All three parties are the Organization, not a Practitioner.** A generated
  summary has no human author; naming one would put a clinician who does not
  exist into clinical data, where no later reader could tell the fabrication
  from a real attribution. FHIR permits Organization for `author` and
  `attester.party`.
- **A guardian only for a minor.** An adult may have a *god man*, but that is
  a court appointment, not an inference from age. Unknown age ⇒ no guardian,
  because unknown is not minor. Measured over 3000 draws of the generator's
  1940–2010 birth range: **101 minors, 101 guardians** — the path fires, and
  only there.
- **`Coverage.insurer` is a display-only Reference.** ips holds no region
  registry, so `Organization/<guid>` would point at nothing — the dangling
  reference #771 and #768 are both about. PUBLICPOL regional cover, insurer
  derived from the patient's city so a Stockholm resident is not on Region
  Skåne's books.
- **Country of origin has no FHIR Composition element.** Rather than mint an
  extension URL no validator would recognise, it rides on the custodian
  Organization's and the Patient's `address.country`, and the module says so
  instead of implying a standard exists.

### Unverified and labelled

`CODES_VERIFIED = False`, like `euips_sections`, and the endpoint returns it.
Two R5-vs-R4 shapes are asserted and want a reviewer's eye, because the R4 form
would validate nowhere: `Coverage` uses `kind` + `insurer` (R4: `payor`, no
`kind`), and `Composition.attester.mode` is a CodeableConcept (R4: plain code).
Both have explicit tests.

Header resources are fetched separately from the clinical types so they never
reach `_build_sections` — a "Coverage section" is a section the guideline does
not define.

### Live verification (ips-app-1, real patient 8f83e561…)

```
route registered : ['/api/v1/patients/<guid>/euips-header']
unauthenticated  : 401 Missing Authorization header
assigned clinic  : Test Clinic  org 7f003d04-…
custodian        : urn:uuid:7f003d04-…  display 'Test Clinic'
attester mode    : CodeableConcept, code 'legal'
language         : sv-SE      mismatch: None
guardian         : not_applicable — "patient is an adult, so a guardian
                   would be invented"   (age 68)
RelatedPerson: 0   Coverage: 0
header complete  : False   missing: ['contact_person', 'health_insurance']
```

### The header is half derived, half stored — so the deploy only half fixed it

That last line is the finding. Deriving on read gave **every existing patient**
a correct custodian, author, attester and language the moment the image
restarted. The two STORED resources were absent for all of them, because
nothing had written them.

`flask euips-header-backfill` closes the gap. **DRY RUN BY DEFAULT**, and
deliberately not a migration: it writes statements about real people (a next of
kin, an insurance policy) and these rows feed cdr_6, analyse and every spärr
decision downstream, so manufactured ones would be indistinguishable later from
data a clinician entered. Idempotent; `--seed` makes the dry run and the real
run produce identical values.

Production dry run, 2026-10-08 — **nothing written, awaiting operator go/no-go**:

```
patients examined       : 150
need contact persons    : 150
need health insurance   : 150
need a document language: 150
of which legal guardians: 5   (minors only)
```

618 passed; `tests/test_patient_portal_html.py`'s draft-banner test fails
identically with these changes stashed (pre-existing, unrelated).

### #792 backfill APPLIED — 2026-10-08, operator-authorised

Pre-write snapshot: `miserver:~/backups/predeploy/ips.pdhc/792/ips_20261008T091737Z.pgdump`
(188K, `pg_dump -Fc` of `ips_db`). Taken because the backfill patches 150
existing `Patient.resource_json` rows in place, not only inserts.

Run with `--seed 20261008`, so the dry run and the applied run produced
identical values and the operation is reproducible:

```
patients examined       : 150
created RelatedPerson   : 155     (150 contacts + 5 guardians)
created Coverage        : 150
patched language        : 150
patched Patient.contact : 150
```

Verified afterwards:

| check | result |
|---|---|
| `fhir_resources` Coverage / RelatedPerson | 150 / 155 |
| patients with no contact person | **0** |
| patients with no insurance | **0** |
| guardians created, and their ages | 5 — **[3, 3, 9, 16, 17]** |
| any guardian on an adult or unknown age | **none** |
| language spread | sv-SE 133, en-GB 8, so-SO 4, fi-FI 2, ar 2, fa 1 |
| headers still incomplete | **0** |
| second `--no-dry-run` run | created 0, patched 0 — idempotent |

**The guardian ages are worth noting.** The mock generator only produces
1940–2010 births, so its youngest patient is 16. Ages **3 and 9** are
Synthea-imported patients — the guardian rule is therefore doing real work on
imported data, not just on generated cohorts, and the age gate is what keeps it
from attaching a guardian to the 145 adults.

Endpoint re-check on the same real patient that reported
`missing: ['contact_person','health_insurance']` before the backfill:

```
RelatedPerson    : 1   Coverage: 1
header complete  : True   missing: []
guardian         : not_applicable — "patient is an adult, so a guardian
                   would be invented"   (age 68)
custodian        : urn:uuid:7f003d04-…  'Test Clinic'     mismatch: None
```

So #792 is now complete for the existing population as well as for newly
generated patients.
