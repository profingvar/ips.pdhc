# eps.pdhc (formerly ips.pdhc) — Technical Manual

> **Renamed 2026-11-22 (#1015).** ips.pdhc is now **eps.pdhc**, at
> <https://eps.pdhc.se>; `ips.pdhc.se` no longer resolves. Only the name and
> address changed: the containers (`ips-app-1`, `ips-db-1`), the database
> (`ips_db`), the server directory (`/usr/local/www/pdhcips/`) and stored
> identifiers keep `ips` on purpose. "IPS card" below is the document type
> (International Patient Summary), not the service.

> **What this file used to be.** Until 2026-10-08 it was 99 lines about a
> single 2026-06-09 data sweep plus a port table, and it was published as the
> service's technical manual on pdhc.se. It described an incident, not a
> service. The sweep note is retained verbatim in §8 because it is still the
> record of what happened; everything above it is new.

---

## 0) Names, addresses and the rename (#1015)

- **Callers** set `EPS_BASE_URL=https://eps.pdhc.se` and `EPS_API_KEY`. The old
  `IPS_BASE_URL` / `IPS_API_KEY` are still read, each only when its `EPS_*`
  twin is blank, until phase 4 (#1028) removes them. Both unset behaves as
  before in the services: no invented default. The one exception is sim.pdhc
  (a Mac-side tool), which defaults to `https://eps.pdhc.se` (#1027).
- **SSO**: requests arriving on host `eps.pdhc.se` use the client pair
  `SSO_CLIENT_ID_EPS` / `SSO_CLIENT_SECRET_EPS`, falling back to
  `SSO_CLIENT_ID` / `SSO_CLIENT_SECRET` when that pair is incomplete.
- **Health** reports `"service": "eps.pdhc"` with
  `"service_aliases": ["ips-server", "ips.pdhc"]`, so a reader of the old
  name keeps working.
- **Who still calls which address**: every `/api/`, `/fhir/` and `/external/`
  request increments one row of `host_usage` per (Host, caller). Read it with
  `docker exec -w /app ips-app-1 flask host-usage [--host eps.pdhc.se]`.
  Callers are named by key label, never by secret.
- **contract.pdhc's consent emitter** holds a key scoped `consents:emit`, which
  admits list / grant / revoke of PatientConsent for any patient and nothing
  else (#1030).
- **sso.pdhc's registration** needs its eps key scoped
  `patients:self-register`, which admits `POST /patients/self-register` and
  nothing else (#1049, section 6c).

## 1) What eps.pdhc is

**eps.pdhc is the platform's patient registry.** Every other service refers to
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
| `patient_clinic_assignments` | the M2M that answers "where does this patient belong". `ended_at` (#891); `origin` (#1049): NULL = not stated, `self-registered` = the patient registered in the patient app and chose this unit |
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

## 6b) Patient-reported EPS content and endorsement (#1044)

The patient may report five things through the patient app's EPS form:
allergies, medication, previous illnesses, vaccinations and contact persons.
Diagnoses are not in the form; they come from care. eps.pdhc takes none of it
directly. Each answer is stored in the CDR as a patient-generated original, a
professional approves, amends or rejects it there, and an approval writes a
new CDR row, the **endorsement row**.

**The rule.** Of patient-reported material, only an endorsement row is a
source: `endorses_guid` set and `data_origin` null. An original is never a
source, whatever its `review_status`. The rule is one function,
`cdr_patient_reported_derivation.is_source`.

**The form.** `gateway/app/resources/eps_patient_v1.json`, a byte-identical
copy of `plans/PROMs/eps_patient_v1.json` in the workspace repo (a test
compares them). Canonical `https://plan.pdhc.se/fhir/Questionnaire/eps-patient`,
version 1. Per section: `<section>.status` (has / none / unknown) and a
repeating group `<section>.entry`.

**The command.** File-fed, like `derive-conditions-from-cdr`:

```
flask derive-patient-reported-from-cdr FILE            # dry run
flask derive-patient-reported-from-cdr FILE --apply --expect N
```

FILE is a JSON list of CDR answer rows: `{cdr, guid, patient_guid, link_id,
value, data_origin, endorses_guid, reviewed_by_user_guid, reviewed_by_name,
reviewed_at, [author_org_guid], [group], [review_status]}`.

| situation | what happens |
|---|---|
| original only, pending or rejected | nothing derived; counted as ignored |
| endorsement row | one entry per anchor field, value = the endorsement row's (the amended one if care amended) |
| same file again | nothing planned |
| export differs from the stored entry | a new version (#934), not a second entry |
| derived entry whose endorsement is not in FILE | kept, and listed as `orphaned` on every run; nothing is deleted |
| `endorses_guid` set but `data_origin` not null | the run is refused, nothing written |
| row without the `data_origin` key, endorsement without author, endorsement of a non-endorsed original, two endorsements of one original, patient unknown to eps | the run is refused, nothing written |
| `--expect` differs from the planned count | refused, nothing written |

**Mapping.** The anchor field names the thing and becomes one resource; the
other fields are details of it. Free text stays text: no code is derived from
a string.

| section | anchor | resource | details |
|---|---|---|---|
| allergy | `allergy.substance` | AllergyIntolerance, `code.text`, clinicalStatus active | `reaction` -> `reaction.manifestation.concept.text`; `severity` -> `reaction.severity` (the patient's own choice) |
| medication | `medication.name` | MedicationStatement, `medication.concept.text`, status recorded | `dose` + `frequency` -> `dosage.text`; `indication` -> `reason.concept.text`; `prescribed` -> a note |
| history | `history.condition` | Condition, `code.text`, clinicalStatus **inactive**, no verificationStatus | `year` -> `onsetDateTime` |
| vaccination | `vaccination.vaccine` | Immunization, `vaccineCode.text`, primarySource false | `date` -> `occurrenceDateTime`, else `occurrenceString` |
| contact | `contact.name` | RelatedPerson, `name.text` | `relation` -> `relationship.text`; `phone` -> `telecom` |

A history entry is a past illness: `inactive` keeps it out of the problem
list, which holds care's diagnoses. A contact is a RelatedPerson because that
is the resource the document header already carries and it can hold its own
id, CDR link and endorsement; it is not mirrored into `Patient.contact`, so
`/euips-header` does not count a text-only derived contact as `contact_person`.

"None known" (`<section>.status` = none), endorsed, becomes the section's own
absent assertion for allergies, medication and vaccinations. Past illnesses
and contacts have no such code and nothing is written. "Unknown" writes
nothing.

A detail is attached to the anchor of the same patient, section and `group`.
Without `group` it is attached only when the section has exactly one endorsed
anchor for that patient; otherwise it is listed as `unattached`.

**What each derived entry carries.**

- id: uuid5 of the endorsement row's guid, so a re-run finds it.
- `identifier`: `https://cdr.pdhc.se/fhir/Observation|<endorsement row guid>`,
  assigner = the CDR's name; the anchor first, then each attached detail.
- `meta.tag`: `endorsed-patient-reported`.
- extension `https://ips.pdhc.se/fhir/StructureDefinition/endorsement` (a PDHC
  extension): the patient as informant, and each endorser with name, SSO user
  guid, organisation and time. AllergyIntolerance and Condition also carry
  `participant` (informant, verifier); MedicationStatement and Immunization
  carry `informationSource`.

**Where it shows.** In the document, each endorser is a
`Composition.attester` with mode `professional`, once, at their latest
endorsement, beside the custodian's legal attester. In `/euips-summary`, each
entry has `provenance`: null for care's entries, else `{origin:
"patient_reported", informant: "patient", endorsed_by: [...]}`; `cdr_backed`
and `cdr` name the endorsement row.

`derive-conditions-from-cdr` now refuses a row whose `data_origin` is not
null. Its export has not carried that field; the check works when it does.

`/euips-summary` and `/euips-sections` read current versions only. Before,
a superseded version was returned as an entry of its own.

### Card versions: the latest endorsed version wins (#1049)

In patient app v2 the patient sends one SECTION of "Mitt patientkort" at a
time, and every row of one sending carries the same `card_version` (the CDR
export also gives `card_section` and `reviewed_at`). Care endorses a version as
a whole.

| situation | what happens |
|---|---|
| a section has endorsed rows of several card versions | only the rows of the LATEST (by `reviewed_at`, ties by the version string) are sources; the others are listed as `replaced_by_newer_card` |
| an entry derived earlier from an older version of that patient and section | **retired**: the current version becomes `superseded` and a new version row with the same content and status `retired` is written (`fhir_service.retire_resource`). Every read selects `status = 'active'`, so it is gone from the summary, the sections and FHIR reads; history is kept. So a removal by the patient, once endorsed, removes the entry |
| row without `card_version` (v1, one row per answer) | the #1044 rule unchanged; never replaced or retired by a card version |
| an entry with a card version, but no newer version of its section in FILE | `orphaned`, as before; never retired on inference |
| FILE would bring back a retired entry (it lacks the newer version that retired it) | refused, nothing written: the export is older than the EPS |
| `card_section` contradicts the linkId; one `card_version` spanning two patients or sections; `reviewed_at` not an ISO time with a timezone | refused, nothing written |

A derived entry records its version in the endorsement extension
(`{"url": "cardVersion", "valueString": ...}`); a v1 entry has none, so its
JSON is unchanged and a re-run of a v1 export still plans nothing. The dry run
prints `planned {'create': .., 'update': .., 'retire': ..}`; `--expect` counts
all three.

## 6c) Self-registration (#1049)

`POST /api/v1/patients/self-register`, `require_auth` + scope
`patients:self-register` (`SCOPE_PATIENTS_SELF_REGISTER`). Caller: sso.pdhc's
`/register-patient`, with its `EPS_API_KEY`. That key must carry the scope; an
SSO bearer is refused even for an SU (`require_scope`).

Body `{"personnummer", "given_name", "family_name", "care_unit_guid",
"email"?, "mobile"?}`.

| outcome | answer |
|---|---|
| a required field missing or a value over 255 characters | 422 `{"error": "validation", "fields": [...]}` |
| not a personnummer with a real date | 422 `{"error": "invalid_personnummer"}` |
| a VALID check digit while `SELF_REGISTER_SYNTHETIC_ONLY` is true (default; only `false` turns it off) | 422 `{"error": "real_personnummer"}` |
| `care_unit_guid` is not the `organisation_guid` (= `care_unit_guid` in `Clinic.to_dict`) of an ACTIVE clinic, compared case-insensitively as sso does. An eps clinic `guid` is not a unit guid | 422 `{"error": "unknown_unit"}` |
| any patient already carries the number (`YYYYMMDD-NNNN` or the 12 digits without the dash; any system, archived included) | 409 `{"error": "exists"}`, no guid, no detail |
| otherwise | 201 `{"patient_guid"}` + `X-PDHC-Patient-Guid` |

The patient is created as the admin form and the clinic import create one: a
FHIR Patient through `create_resource` (identifier under the personnummer OID,
`name`, `birthDate` = the date the number encodes, `gender` unknown,
`managingOrganization` = the unit, `telecom` email / phone `use: mobile`),
which writes the PatientIndex row with `guid == resource_id`. Then an ACTIVE
`PatientClinicAssignment` with `origin = 'self-registered'`, and the state
projection is rebuilt. Audited `patient_self_registered` (clinic, unit, which
telecom kinds); refusals for unit and exists as `patient_self_register_refused`.
The personnummer is never logged or audited.

**Deploy order.** `migrations/add_assignment_origin.sql` must run BEFORE the
image with this code: the model selects the `origin` column on every
assignment read, so without it every such read fails.

Not guarded: two simultaneous registrations of the same number can both pass
the exists check (no unique index on `patient_index.identifier_value`).

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
