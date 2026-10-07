# euIPS reform of ips.pdhc — the plan

**Epic #788.** Tickets #789–#799. Source: `docs/EU_Patient_Summary_ICD11.docx`.
Measured against the live `ips_db` and every sibling repo on 2026-10-07.

Kept here as well as on the board because the board has no edit: refining a
ticket means deleting and recreating it, which renumbers it and dangles every
reference (CLAUDE.md §2). The plan survives that; the numbers may not.

## The headline: the schema barely needs reforming

`fhir_resources` is already generic — `resource_type` + `resource_json` (JSONB)
+ `patient_guid`, indexed on type, patient and type+patient. **Every euIPS body
section is a FHIR resource.** So the body needs no new tables. That is also the
best possible answer to "do not break the other services": the reform is
generator and semantics work, not a schema rewrite.

The one addition that IS justified is a batch marker on `patient_index`, because
"generate 100 patients" currently cannot be undone without recording the GUIDs
by hand. Additive, nullable, no default.

## What is actually wrong today, with numbers

| finding | measurement |
|---|---|
| Patients with NO clinical resources in any section | **110 of 150** |
| …including all three euIPS-REQUIRED sections | so 110 invalid summaries |
| Personnummer of the wrong length | **60 of 60** sampled (15 chars, not 13) |
| Personnummer with a valid Luhn check digit | **6 of 60 — exactly chance** |
| Patients whose identifier century contradicts their birth date | 4 of 60 (`1920…` for a 2000s birth) |
| Patients carrying US SSNs in a Swedish registry | 10 (Synthea import) |
| euIPS sections with no resource type at all | Device, CarePlan, Consent, Flag, RelatedPerson, Coverage, travel, social history, functional status, pregnancy |

The personnummer cause is one line, `gateway/app/admin.py:743`:

```python
personnummer = f"19{mp['birth'].replace('-', '')}-{random.randint(1000, 9999)}"
```

`mp['birth']` is already `YYYY-MM-DD`, so the century is doubled, and the final
digit is random where it must be a Luhn checksum.

## The compatibility contract — nine consuming services

Found by searching every sibling repo, not from memory.

| endpoint | consumers |
|---|---|
| `POST /api/v1/patients/analysis-filter` | cdr, cdr_6, analyse, dashboard, rosetta |
| `/patients/<guid>/blocks`, `/blocks/check`, `/blocks/metadata`, `/blocks/check-bulk` | request, cdr_6, analyse, dashboard, gateway |
| `GET /patients/<guid>/clinics` | request — the #779 authorisation gate |
| `/patients/<guid>/consents`, `/consents/check`, `/consents/<id>/revoke` | request, contract |
| `GET /clinics`, `/clinics/<guid>/patients` | sim |
| `/fhir/Patient`, `/fhir/Observation`, `/fhir/Condition` | gateway, analyse, dashboard, cdr, sim |

Binding on every ticket:

1. **`patient_index` changes are additive only.** `guid` is the cross-service
   key; `ehds_opt_out`, `quality_registry_opt_out` and
   `consented_research_projects` are read by `analysis-filter`, which five
   services depend on.
2. **`Clinic.guid` and `Clinic.organisation_guid` stay distinct.** Conflating
   them was #779 — the gate denied every non-SU caller for months.
3. **The patient GUID stays the internal key.** The personnummer is an
   identifier, never a join key (Rule 18).

## The euIPS rule that drives the design

> Where the coding is incomplete, the "absent / unknown" codes still have to be
> given explicitly. This applies, for example, to the required sections: you
> must state "no known allergies" rather than leave the section empty.

So "no row" is ambiguous between three states euIPS treats differently:
**asserted empty**, **unknown**, and **not generated**. Recommendation: an
asserted-empty section is a real resource carrying the IPS
`absent-unknown-uv-ips` code, which needs no new storage — and then genuine
absence of a row means "not generated", which is what it should mean.

## Sequencing

| phase | tickets | why here |
|---|---|---|
| **A** standalone | #789 personnummer, #790 move the generator UI | No schema change, no design dependency. Ships first, shrinks the surface. |
| **B** decide | #791 where content lives + the absent-code model (**blocks C**), #792 document header | Every Phase C ticket depends on #791's answer. |
| **C** generate | #793 required, #794 recommended, #795 optional, #796 EU additions, #797 100-per-provider batch | euIPS obligation order: the sections that make a summary valid come first. |
| **D** verify | #798 pin the nine consumers, #799 completeness validator | "Lose no functionality" is checked, not hoped for. #798 is written first and run throughout. |

## Two things the plan deliberately refuses

* **No conformance claim.** The document states the EHDS implementing acts for
  the exchange format were not confirmed adopted as of October 2026. #799's
  validator therefore reports "all required sections present", never
  "EU-conformant" — the second is a claim someone may repeat in a technical
  file.
* **No invented terminology.** plan.pdhc and termbank.pdhc own codes. Where a
  real code set is unavailable, a simulator value is marked as such rather than
  passed off as SNOMED.

---

# #791 DECISION TAKEN — 2026-10-07

Operator: "go with your recommendation for 791". Implemented in commit below.
This unblocks Phase C.

## 1. Section content lives in `fhir_resources`. No new tables.

That table is already `resource_type` + `resource_json` (JSONB) +
`patient_guid`, indexed on type, patient and type+patient. Every euIPS section
IS a FHIR resource. Nine sibling services read ips; a per-section table would
mean new endpoints, new serialisers, and a second source of truth for the same
clinical facts.

It also preserves the hybrid format. The guideline requires narrative *and*
coded entries and calls the narrative the safety net — "what a clinician abroad
sees". A FHIR resource carries both; typed columns would lose one.

## 2. An explicitly-absent section is a real resource with the IPS absent code

`absent-unknown-uv-ips`. The guideline is explicit: *"you must state 'no known
allergies' rather than leave the section empty."* Written as an ordinary row it
needs no new storage, and it makes three states distinguishable:

| state | meaning |
|---|---|
| `PRESENT` | a clinical resource of that type exists |
| `EXPLICITLY_ABSENT` | a resource exists carrying an absent/unknown code |
| `MISSING` | no row — now unambiguously "not generated" |

Before this, 110 of 150 patients had no rows in any section, and "no row" could
not be told apart from "nothing to report".

**Real content beats a stale absent assertion.** A patient may carry both; the
data wins, or the summary hides a genuine allergy behind old bookkeeping. That
is a safety question, and it has its own test.

## 3. Section status is COMPUTED, never stored

No `ips_section_status` table. `GET /api/v1/patients/<guid>/euips-sections`
derives it per call. A stored copy of a derivable fact is the shape that
produced #779 (two identifier spaces compared as one) and #771 (two GUIDs for
one object).

## 4. One schema addition: `patient_index.generation_batch_guid`

Nullable, no default, no index. Generating "100 patients for an assigned care
provider" has to be undoable, and there was no batch marker at all — removing a
batch meant recording its GUIDs by hand. Nothing else about a batch needs
storing: the timestamp is `created_at`, the organisation comes from the clinic
assignment. A batch *table* would duplicate derivable facts.

`UUID`, not `VARCHAR(36)`: `models/base.py::GUID` resolves to
`PG_UUID(as_uuid=True)` on postgresql, and `patient_index.guid` is a real
`uuid` column — confirmed against `information_schema`. My first draft of the
migration said varchar; psycopg2 would have adapted bound UUIDs to strings so
it would have *appeared* to work while disagreeing with the model. That is the
UUID-versus-string mismatch that hid #730's 500.

Applied by `gateway/migrations/add_generation_batch_guid.sql` — idempotent
`ADD COLUMN IF NOT EXISTS`, the same pattern as `add_reform_patient_flags.sql`
(#404), because ips builds schema with `db.create_all()`, which adds missing
tables and never alters an existing one.

## 5. Header items: JSON by default

Contact persons → `RelatedPerson`, insurance → `Coverage`, author / legal
authenticator / custodian → the `Composition` inside the bundle, which
`ips_snapshots.bundle_json` already stores. A patient-level column only where
something filters on it, and nullable when added.

## 6. Codes are flagged UNVERIFIED, deliberately

`euips_sections.CODES_VERIFIED = False`, and the endpoint says so in its own
response rather than leaving a caller to assume. The LOINC section codes and
absent/unknown codes are written from knowledge of the IPS IG, not from a fetch
of the published CodeSystem, and the plan's rule is that terminology belongs to
plan.pdhc and termbank.pdhc.

The EU-addition sections (alerts, travel history, patient-provided) carry
`loinc=None` and `absent_code=None` rather than a plausible guess, with a test
pinning that nothing was invented there.

`is_conformant()` is named for what it checks — every required section PRESENT
or EXPLICITLY_ABSENT — and is not called `is_eu_conformant`. The source
document states the EHDS implementing acts were not confirmed adopted as of
October 2026.
