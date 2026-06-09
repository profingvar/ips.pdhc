# ips.pdhc — technical notes

A growing collection of focused technical notes for `ips.pdhc`. The
fuller end-to-end description lives in `description_of_IPS.md`; this
file is for sections that need a stable URL inside the codebase (e.g.
audit findings, legal-confirmation paragraphs, deploy-shaped runbooks).

## Spärr — historical data migration confirmation (ticket #208)

**Scope.** PDL Ch 4 § 4 spärr landed via IPS Renov 1 (`PatientBlock`,
ticket #197). Before that ticket, no `PatientBlock` table existed.
Ticket #208 asked whether any *pre-existing* "no-share" markers
elsewhere on the platform should have been converted into
`PatientBlock` rows when #197 shipped — so the new structured blocks
inherit any legacy patient opt-outs.

**Verdict: no markers found. Negative confirmation.**

### What was swept (2026-06-09)

Both code and data, across every database that could plausibly carry
a patient opt-out marker:

| DB | Schema column sweep | Data sweep |
|---|---|---|
| `ips_db` | `information_schema.columns` filtered on `share`, `hidden`, `opt`, `nopat`, `exclud`, `spar`, `no_disclose` | `fhir_resources.resource_json` for Patient rows containing `NOPAT`, `confidentiality`, `restricted`, or any `meta.tag[]` |
| `dashboard_pdhc_db` | same column-name filter | `observation_cache.raw` for the same security-label strings |
| `gateway_pdhc_db` | same column-name filter | n/a (no patient-shaped JSON columns) |
| `request_pdhc_db` | same column-name filter | n/a |

All four schemas: **0 columns match**.
IPS Patient JSON: **0 patients with `meta.tag[]` populated**, **0
patients with NOPAT / confidentiality / restricted strings**.
Dashboard cache JSON: **0 rows with security-label strings**.

This is the expected result on this platform — PDHC was built
post-PDL Ch 4 § 4 with `PatientBlock` as the only spärr surface, and
no consumer ever wrote a legacy opt-out flag the way an older EMR
might (a `do_not_share` boolean on the patient row, or a
`hidden_patient_list` table).

### What this means going forward

- **No one-off migration was needed.** No `PatientBlock` rows are
  owed from legacy data.
- **The negative confirmation is documented here** so a future audit
  doesn't re-ask the question. The expected scope of such an audit
  is "patient-shaped opt-out signals before #197 landed" — they
  didn't exist; this section is the canonical evidence.
- **If a marker does appear in the future** (e.g. via Synthea import
  with synthetic security labels, or via a future EMR migration), it
  should be converted into `PatientBlock` rows in the same migration
  that introduces it. The `PatientBlock` model has supported
  `source_scope_type='caregiver'` since #197 and now serves cross-
  caregiver semantics (#204), so it can carry any granularity a
  legacy marker would have expressed.

### Reproducing the sweep

```sql
-- Schema sweep (one per database)
SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND (column_name ILIKE '%share%'
       OR column_name ILIKE '%hidden%'
       OR column_name ILIKE '%opt_out%'
       OR column_name ILIKE '%nopat%'
       OR column_name ILIKE '%exclud%'
       OR column_name ILIKE '%spar%'
       OR column_name ILIKE '%no_disclose%')
ORDER BY table_name, column_name;

-- IPS Patient JSON sweep
SELECT count(*) FROM fhir_resources
WHERE resource_type = 'Patient'
  AND (resource_json::text ILIKE '%NOPAT%'
       OR resource_json::text ILIKE '%confidentiality%'
       OR resource_json::text ILIKE '%restricted%');

-- Dashboard cache JSON sweep
SELECT count(*) FROM observation_cache
WHERE raw::text ILIKE '%hidden%'
   OR raw::text ILIKE '%no_share%'
   OR raw::text ILIKE '%opt_out%'
   OR raw::text ILIKE '%confidentiality%'
   OR raw::text ILIKE '%NOPAT%';
```
