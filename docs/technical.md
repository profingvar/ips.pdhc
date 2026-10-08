# ips.pdhc — Technical Manual

> **What this file used to be.** Until 2026-10-08 it was 99 lines about a
> single 2026-06-09 data sweep plus a port table, and it was published as the
> service's technical manual on pdhc.se. It described an incident, not a
> service. The sweep note is retained verbatim in §8 because it is still the
> record of what happened; everything above it is new.

---

## 1) What ips.pdhc is

**ips.pdhc is the platform's patient registry.** Every other service refers to
a patient by a GUID that originates here, and three decisions that no other
service may make are made here:

| decision | who asks | how |
|---|---|---|
| does this patient exist, and where are they assigned | contract, request, gateway | `GET /api/v1/patients/<guid>/clinics` |
| is this patient's data from source X blocked (**spärr**, PDL Ch 4 §4) | cdr1–3, cdr_6, gateway, analyse | `GET /api/v1/patients/<guid>/blocks/check` |
| may this patient's data be used for this analysis purpose | analyse, rosetta, cdr2–6 | `POST /api/v1/patients/analysis-filter` |

It also renders **International Patient Summary** documents (FHIR R5 Bundles)
and, since the euIPS epic (#788–#799), measures them against the EU patient
summary guideline.

In PDHC a **clinic** is an organisation. `Clinic.organisation_guid` is the
GUID sso.pdhc issued, and that is the value every cross-service comparison must
use — see §5.

---

## 2) Authentication — one header, and only one

`app/services/auth_service.py::require_auth` inspects **only** the
`Authorization` header, and accepts two schemes:

```
Authorization: Bearer <sso-token>     a human's SSO session
Authorization: ApiKey <raw-key>       a service account (api_keys table)
```

**It never looks at `X-API-Key`, `X-Service-Key`, or a session cookie.** A
caller using any of those receives `401 {"diagnostics": "Missing Authorization
header"}` — a 401 that names an *absent* credential while the request carried a
perfectly valid one.

This is the single most expensive fact about integrating with ips. Five
services have now got it wrong, and each failure was silent because the caller
treated the 4xx as an empty result:

| service | what it sent | consequence |
|---|---|---|
| request.pdhc (`ips_client`) | `X-API-Key` | spärr filter failed **OPEN** — no record was ever hidden |
| request.pdhc (`ips_consent_client`) | `X-API-Key` | dispatch failed **closed** — over-refused |
| gateway.pdhc | `X-Service-Key` | observation-read spärr failed open |
| cdr_6.pdhc | `X-API-Key` | cached the 401's empty list as "no blocks" |
| contract.pdhc | `X-API-Key` | every `Patient/<guid>` signer rejected as "not found in IPS" |

If you are debugging a 401 from ips, check the header **name** before checking
the key.

---

## 3) Which endpoint a service account may use

A service account has `is_superuser = False` and **no clinic relationship to
any patient**, by design. That rules out the staff-facing routes, and the
choice of endpoint is therefore not a matter of taste.

| route | gate | a service account gets |
|---|---|---|
| `GET /patients/<g>/blocks` | `require_auth` **+ `_can_act_on_patient`** | **403**, and `source_scope_id` redacted even when it answers |
| `GET /patients/<g>/blocks/check?source_clinic_id=<org>` | `require_auth` only | **200** — `is_blocked` + un-redacted `blocking_scopes` |
| `GET /patients/<g>/blocks/metadata` | `require_auth` only | counts only, deliberately |
| `GET /patients/<g>/consents/check` | `require_auth` only | the consent twin of `blocks/check` (#558) |
| `GET /patients/<g>/clinics` | `require_auth` only | the assignment list — also the cheapest existence probe |

**"Which clinics blocked this patient" is a question ips declines to answer a
service caller**, on a recorded legal decision carried in the source of
`/blocks/metadata`: *"this metadata view may be exposed to any authenticated
caller — no clinic relationship required. It returns only counts; PDL §4 ¶3
satisfied without leaking sources."*

So a 403 on `/blocks` is not a credential problem to solve — it is the design
telling a caller to ask a different question. Use `/blocks/check` once per
distinct source, which is what analyse, request.pdhc and cdr_6 all do.

`/blocks/check` returns **every** matching scope, active or lifted, so a
consumer can apply the mechanical `indispensable_care` lift filter itself.
Omitting `source_caregiver_id` considers clinic-level blocks only — passing a
guessed one silently *widens* the filter.

---

## 4) Data model

| table | holds |
|---|---|
| `patient_index` | one row per patient: `guid` (the platform identifier), `resource_id` (the FHIR Patient id), the D1 consent flags, `generation_batch_guid` (#797) |
| `fhir_resources` | every FHIR resource, keyed by `resource_type` + `resource_id`, scoped to a patient by `patient_guid`, versioned by `version_id` |
| `clinics` | organisations. `organisation_guid` is **sso's** GUID |
| `patient_clinic_assignments` | the M2M that answers "where does this patient belong" |
| `patient_blocks` | spärr. `source_scope_type` (clinic / caregiver) + `source_scope_id`, with lift fields |
| `patient_consents` | per-purpose consent |
| `emergency_access` | nödöppning |
| `ips_cards` / `ips_snapshots` | a rendered summary and its point-in-time bundle |
| `api_keys` | service accounts (`user_guid` NULL) |
| `audit_logs` | the Rule 24 operation log |

**`patient_index.guid` is a UUID column.** A malformed guid therefore raises at
the driver rather than returning no rows — which is how `/analysis-filter`
once answered **500** for a cohort containing one bad guid, and cdr turned that
into `IpsUnreachable` and fail-closed the whole read, blaming a sibling outage.
Malformed guids are now treated as *unknown* and named in `excluded` with their
own reason. A consent gate must return a verdict, never an exception.

---

## 5) Identifier spaces do not collapse

Two GUID spaces meet here and they are **not** interchangeable:

- `clinics.guid` — ips's own primary key
- `clinics.organisation_guid` — the GUID **sso** issued for that organisation

Every cross-service comparison uses the **organisation** GUID, because that is
what appears in an SSO access blob. Comparing the two spaces as if they were
one is #779: an authorisation gate compared sso organisation GUIDs against ips
clinic GUIDs and consequently denied **every** non-SU caller, while twelve unit
tests passed because the fixture fed both sides the same value.

`tools/check_clinic_org_resolution.py` (#780) checks that every active clinic's
`organisation_guid` resolves to an organisation sso actually issued. One did
not, and was deactivated.

---

## 6) The euIPS layer (#788–#799)

The EU patient summary guideline describes 17 sections at four obligation
levels. `app/services/euips_sections.py` is the catalogue; four modules emit
content (`euips_required`, `euips_recommended`, `euips_optional`,
`euips_eu_additions`) and `euips_header` supplies the document header (#792).

Three design decisions are worth knowing before changing anything here.

**Status is COMPUTED, never stored.** `GET /patients/<g>/euips-sections` and
`/euips-header` derive their answer from the patient's `fhir_resources` on every
call. A stored copy of a derivable fact is the shape that produced both #779
and #771, so there is deliberately no table.

**A required section may never be empty.** The guideline requires a summary to
state *"no known allergies"* rather than leave the section blank, so each
section has three states — `PRESENT`, `EXPLICITLY_ABSENT`, `MISSING` — and the
absent assertions carry `absent-unknown-uv-ips` codes. Measured 2026-10-07,
110 of 150 patients had no statement of any kind in any section, which is
what #793 fixed.

**`conformant` is not a conformance claim, and the API says so.** Every
response carries `codes_verified: false` and a disclaimer, because the EHDS
implementing acts were not confirmed adopted as of October 2026 and the section
codes are not verified against a published IG. Do not remove that field to make
a dashboard greener.

### The document header (#792)

`RelatedPerson` (contact, plus a guardian **only for a minor**), `Coverage`
(PUBLICPOL regional public cover), and `Composition.author` / `attester[legal]`
/ `custodian` / `language`.

**The custodian is derived from `patient_clinic_assignments`, which is
authoritative.** The Patient's `managingOrganization` and the Composition
custodian are projections of it. A disagreement is *reported* — as a bundle
`meta.tag` and as `custodian_mismatch` on the endpoint — not silently resolved,
because #768 happened precisely because a mismatch was invisible.

Two R5 shapes are asserted and are worth a reviewer's eye, since the R4 form
validates nowhere: `Coverage` uses `kind` + `insurer` (R4: `payor`, no `kind`),
and `Composition.attester.mode` is a CodeableConcept (R4: a plain code).

### Identifiers

`app/services/personnummer.py` builds valid Swedish personal identity numbers
with a Luhn check digit (#789). The previous generator prefixed `"19"` onto a
date that already carried its century, producing 15-character values whose
check digit was correct about 10% of the time — by chance.

---

## 7) Operational notes

- **Generation is batched.** Each admin generate run stamps one
  `generation_batch_guid` on every patient it creates, so a cohort can be
  identified and purged as a unit (#797). Purge deletes assignments explicitly
  rather than trusting `ON DELETE CASCADE`, because SQLite does not enforce
  foreign keys without `PRAGMA foreign_keys=ON` and the tests run on SQLite.
- **Backfill is opt-in and dry-run by default.** `flask euips-header-backfill`
  writes statements about real people (a next of kin, an insurance policy) into
  rows that feed cdr_6, analyse and every spärr decision, so it is not a
  migration. `--seed` makes a dry run and the real run produce identical
  values.
- **`flask euips-report`** reports section coverage across all patients;
  `euips-report-batch <guid>` does one cohort.
- **`gateway/scripts/contract_check.py`** verifies the routes consumers depend
  on, from inside the image (#798). Its first run found a live defect in
  contract.pdhc.

---

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

---

## Port Allocation

| Port | Service |
|------|---------|
| 9040 | Flask application (Gunicorn, bound to 127.0.0.1) |
| 9041 | PostgreSQL database |
