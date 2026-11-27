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
- **sso.pdhc's invite acceptance** needs the same key ALSO scoped
  `patients:identifier-match` (#1050, section 6d), added by
  `plans/patientapp_deploy/ops/pa7_invite_scope.sh` in the workspace repo.

## 1) What eps.pdhc is

**eps.pdhc is the platform's patient registry.** Every other service refers to
a patient by a GUID that originates here, and three decisions that no other
service may make are made here:

| decision | who asks | how |
|---|---|---|
| does this patient exist, and where are they assigned | contract, request, gateway | `GET /api/v1/patients/<guid>/clinics` |
| is this patient's data from source X blocked (**spärr**, PDL Ch 4 §4) | cdr1–3, cdr_6, gateway, analyse | `GET /api/v1/patients/<guid>/blocks/check` |
| may this patient's data be used for this analysis purpose | analyse, rosetta, cdr2–6 | `POST /api/v1/patients/analysis-filter` |
| everything eps holds about one patient, for the journal extract (#1059) | record.pdhc, with the professional's own bearer | `GET /api/v1/patient-extract/<guid>` |

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
| `patient_clinic_assignments` | the M2M that answers "where does this patient belong". `ended_at` (#891); `origin` (#1049): NULL = not stated, `self-registered` = the patient registered in the patient app and chose this unit, `invited` (#1050) = a professional registered the patient here for an invitation |
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

**`?include=resource` (#1061).** With `include=resource`, every entry of
`/euips-summary` also carries `resource`: the stored FHIR resource of that
entry (current version). record.pdhc builds its HL7 Europe Patient Summary
(`hl7.fhir.eu.eps#1.0.0-ballot`) from it, so eps stays the one place that
decides what is in an IPS section. Any other `include` value is
`400 bad_include` (checked before the gate); the read is audited with
`detail.resources=True`. Without the parameter the response is unchanged.
eps keeps IPS 1.1's `absent-unknown-uv-ips` codes; EPS is IPS 2.0, and
record translates them to IPS 2.0's SNOMED codes at its export boundary.
The synthetic generators' codes and displays were corrected against
tx.fhir.org in the same pass (some meant something other than their text).

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

## 6d) Registration by the care unit, for an invitation (#1050)

Patients join the patient app only by invitation (operator decision
2026-11-22). Self-registration (6c) stays in the code but sso closes it by
default. dashboard.pdhc's **Bjud in patient** calls two routes here.

### `POST /api/v1/patients/register-at-unit`

`@require_care_professional` (`services/auth_service.py`): the caller's own
SSO **bearer**, validated with sso's `/api/auth/me/service` like the HTML
login. Unlike `require_auth`, no local eps `User` row is needed: the access
blob decides. An `ApiKey` is refused (403) whatever its scopes — this route
acts on a person's affiliation, which a key does not have. Allowed: an SU, or
`user_type == "professional"` with `care_unit_guid` among
`affiliations[].care_unit_guid` (`may_act_for_unit`). `organization_ids` is
never read (Rule 24). A patient, a must-change-password account or a token sso
rejects: 403/401. The audit actor is the professional (a transient, never
stored `User` with the SSO guid and email).

Body `{"given_name", "family_name", "personnummer", "care_unit_guid",
"mobile"?}`. Checks, in this order:

| outcome | answer |
|---|---|
| a required field missing or too long | 422 `validation` |
| caller not affiliated to `care_unit_guid` (checked BEFORE any lookup, so nothing is learned about the number) | 403 `not_affiliated` |
| not a personnummer / a VALID check digit while `SELF_REGISTER_SYNTHETIC_ONLY` | 422 `invalid_personnummer` / `real_personnummer` |
| no ACTIVE clinic with that `organisation_guid` | 422 `unknown_unit` |
| two patients carry the number | 409 `ambiguous` |
| the patient is archived | 409 `archived` |
| the patient exists under another name (case and spacing ignored) | 409 `name_mismatch` — nothing written, so a mistyped number cannot attach a stranger |
| the patient exists | 200 `{"patient_guid", "created": false, "assignment": "existing"\|"added"}`; an ACTIVE assignment at the unit is ensured (a new one has `origin = 'invited'`; an existing one is left as it is) |
| otherwise | 201 `{"patient_guid", "created": true, "assignment": "added"}`: a FHIR Patient as in 6c (mobile only as telecom) and an ACTIVE assignment `origin = 'invited'` |

`X-PDHC-Patient-Guid` on 200/201. Audited `patient_registered_at_unit` /
`patient_register_at_unit_refused`; the personnummer is never logged or
audited. The mobile number is stored only on a NEW patient. `origin` already
exists (6c's `add_assignment_origin.sql`); `invited` needs no migration.

### `POST /api/v1/patients/<guid>/identifier-match`

`require_auth` + scope `patients:identifier-match`; the caller is sso.pdhc,
when an invited patient types their personnummer. `<guid>` is the platform
guid only. Body `{"personnummer"}` → 200 `{"match": true|false}`; 422
`invalid_personnummer`; 404 `{"error": "Patient not found"}`. The number is
never returned; sso learns only yes or no. Audited `patient_identifier_match`
with `{match}` only.

### `GET /api/v1/clinics/<guid>/patients` — the roster, for a person too (#1050 picker)

dashboard.pdhc's patient picker lists each of the caller's care units' rosters
(names and personnummer) with the professional's own SSO **bearer**.

- `@require_auth_or_care_bearer` (`services/auth_service.py`). The `ApiKey`
  path is exactly `require_auth` (sim.pdhc, request.pdhc, icd11.pdhc read
  rosters with a key; unchanged, any clinic). On the `Bearer` path the blob is
  re-validated with sso on every request; a local eps `users` row is used when
  one exists (inactive → 401), and otherwise an SU or a professional is
  admitted as a transient actor (anyone else 401 as before). Before this,
  `require_auth` answered 401 "User not found in local system" to every
  professional without an eps user row, i.e. to practically every real
  professional.
- **Gate, Bearer path only:** SU, or a professional affiliated to the
  clinic's care unit (`may_act_for_unit` over `affiliations[].care_unit_guid`;
  `organization_ids` never read). Otherwise 403 `not_affiliated`. A clinic with
  no `organisation_guid` is SU-only. Before #1050 any bearer with an eps user
  row could read any clinic's roster.
- `<guid>` is the eps `Clinic.guid` or, failing that, the sso care-unit guid
  (`Clinic.organisation_guid`, case-insensitive, active clinics only).
- A bearer read writes one `clinic_roster_read` audit row (`resource_guid` =
  clinic, `detail = {"patients": n}`); never names or numbers. Key reads are
  not audited here (unchanged).
- Tests: `gateway/tests/test_clinic_roster_gate_1050.py`.

### `GET /patients/<guid>/state` and `/patients/<guid>/clinics` with a professional's bearer (#1050 invite)

dashboard's invite reads both with the professional's own bearer. Under
`require_auth` they answered 401 "User not found in local system" to anyone
without an eps `users` row, and production holds ONE such row (measured
2026-11-22), so the invite could not work for real professionals. Both now take
`@require_auth_or_care_bearer`:

| caller | reader scope (`patient_export.exportable`) | `/clinics` |
|---|---|---|
| Bearer, NO eps users row, SU | every patient (`is_admin()`: the transient actor's `is_superuser`) | any patient |
| Bearer, NO eps users row, professional | patients ACTIVELY assigned to an ACTIVE clinic whose `organisation_guid` (care unit) is in `affiliations[].care_unit_guid`; `organization_ids` never read | same scope check; out of scope = the same 404 `{"error": "Patient not found"}` as no such patient, no `X-PDHC-Patient-Guid` |
| Bearer WITH an eps users row | eps-local `UserClinicAssignment`, unchanged | unscoped, unchanged |
| ApiKey | unchanged (an identity-less key has no assignments: `/state` 404) | unscoped, unchanged (request, contract, gateway, icd11, sso, cdr smoke) |

The transient actor is marked `g.care_bearer_transient` by the decorator;
`patient_export._reader_clinic_guids` takes the affiliation branch only then,
so `/export` and `/euips-summary` (still `require_auth`) cannot reach it.
A patient or other non-professional bearer without a row: 401 as before;
must_change_password as everywhere.

Tests: `gateway/tests/test_invite_reads_bearer_1050.py` (13). Run against the
pre-change code, the 9 transient-path tests fail (401) and the 4
unchanged-path tests pass, which is the evidence the key and eps-row paths
did not move.

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

## Access log of one patient (#1045)

`GET /api/v1/audit/patients/<guid>?from=<ISO>&to=<ISO, exclusive>&limit=<n ≤ 5000>`
(gateway/app/api/audit_routes.py), for dashboard.pdhc's loggkontroll.

- `require_auth_or_care_bearer`, and a **Bearer is required**: an `ApiKey`
  caller gets 403 `bearer_required` (a key names no person, and is
  organisation-blind).
- Scope: `patient_export.exportable` — SU all; a professional the patients
  actively listed at a clinic of their affiliated care units. Out of scope =
  the same 404 as no such patient.
- Rows: `audit_log` where `patient_guid`, oldest first, in the platform
  access-log shape (`at, user_guid, user_label, actor_type, action, outcome,
  route, resource_type, session_id, actor_units, basis, detail`); `detail` is
  limited to `reason, outcome, format, mode, access_basis, refusal_code, scope`.
- Logged: `patient.access_log.read`; refusal for an existing patient
  `patient.access_log.refused`.
- `GET /api/v1/audit` (the whole log) is **SU only** since #1045; it was
  `require_auth`, i.e. organisation-blind for any users row or key.

## Patient extract (#1059, record.pdhc stage 6b)

`GET /api/v1/patient-extract/<patient_guid>` (gateway/app/api/patient_extract_routes.py,
gateway/app/services/patient_extract.py): everything eps holds about ONE
patient, in the platform shape `pdhc.patient-extract/1`
(`plans/record_pdhc_extract_contract.md`). record.pdhc merges it with the
other services' parts into the PDF (plan s4.4).

**Door and gate** (the #1045 door):

- `require_auth_or_care_bearer`, then a **Bearer is required**: `ApiKey` ->
  403 `bearer_required`. A patient's bearer is 401 (842540c).
- `patient_export.exportable` (Rule 24 scope, as `/state`) **and** D9
  (`patient_extract.d9_allows`): SU, or an sso affiliation with role
  `doctor` or `nurse` at an ACTIVE clinic where the patient is ACTIVELY
  listed. A professional affiliated as `other_care`, `researcher` etc. is out
  of scope. An eps users row still needs the D9 affiliation in its blob.
- Out of scope = the same 404 `patient not found` as no such patient;
  malformed guid 400.
- Audit: every call writes `patient_extract` with `detail.outcome` =
  `served` (with `n_sections`, `n_items`) / `denied` (`reason`
  `bearer_required`, `out_of_scope`, `malformed_guid`) / `not_found`. The
  loggkontroll view shows a refusal as `denied`.

**Sections** (fixed order; every section always present, `count` = items):

| key | source | versions | event_time / recorded_at |
|---|---|---|---|
| `identity` | `fhir_resources` Patient (all versions) + `patient_index` row | Patient: all; index: 1 (updated in place) | null / row `created_at` |
| `care_units` | `patient_clinic_assignments` (incl. ended) + clinic name and care unit | 1 per row; `events` assigned/ended | `assigned_at` / null (no record column) |
| `contacts` | `Patient.contact` of each Patient version | one item, a version per Patient version | null / Patient row `created_at` |
| `related_persons` | `fhir_resources` RelatedPerson (not patient-reported) | all | resource date / `created_at` |
| `proxy_grants` | `patient_proxy_grants` (ombud, #889) | 1; `events` granted/revoked | `valid_from` / `granted_at` |
| `blocks` | `patient_blocks` incl. lifted/expired | 1; `events` created/lifted | `created_at` / `created_at` |
| `consents` | `patient_consents` incl. revoked and contract-emitted (#558) | 1; `events` granted/revoked | `granted_at` / null |
| `emergency_access` | `emergency_access` (insert-only) | 1 | `attested_at` / `created_at` |
| `patient_card` | `fhir_resources` carrying the #1044 endorsed tag, incl. `retired` (#1049) | all | resource date / `created_at` |
| `conditions` | other `fhir_resources` Condition | all | onset/recorded / `created_at` |
| `summary` | every other `fhir_resources` type of the patient | all | resource date / `created_at` |
| `eps_documents` | `ips_cards` with every `ips_snapshots` bundle | a version per snapshot | `composition_date` / snapshot `created_at` |
| `eps_deliveries` | `push_jobs` of those snapshots + destination name/type | 1 | completed/last attempt / `created_at` |

Each `fhir_resources` resource lands in exactly ONE section
(`patient_extract.fhir_category`). Clinical items carry `cdr_backed`, `cdr`
(#984/#985) and `eps_sections`; card items carry `card_version`,
`endorsed_by`, `informant` per version. `patient_card` says
`source_of_rest: cdr1.pdhc`: every SUBMITTED card version, pending and
rejected ones, and care's review decisions are in cdr1 (endorsements), not
here; eps holds only what was derived from endorsed versions.

**Not in the extract, by name** (`TABLE_EXCLUSIONS`): `patient_state_facts`
(derived projection of tables that are in it) and `audit_log` (D10: the
optional "who read" part comes from `/api/v1/audit/patients/<guid>`).
`test_every_patient_linked_table_is_exported_or_excluded_by_name` fails when a
new table linked to a patient (column name containing `patient`, FK to
`patient_index`, or FK to such a table) is in neither map.

**Personnummer** appears only in `identity`. Elsewhere (snapshot bundles, a
RelatedPerson's own identifier, a `subject.identifier`) the value of a
`urn:oid:1.2.752.129.2.1.3.1` identifier is replaced by
`[personnummer: se avsnittet Identitet]`.

**Never included:** API keys or their hashes, `emergency_access.session_id`,
push destinations' `endpoint_url`, `auth_config`, `headers`, push jobs'
`error_message` (a transport error can quote a URL with a token).

No limit and no truncation: `complete` is always true.

## Port Allocation

| Port | Service |
|------|---------|
| 9040 | Flask application (Gunicorn, bound to 127.0.0.1) |
| 9041 | PostgreSQL database |
