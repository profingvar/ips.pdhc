# Spärr zones + nödöppning (D3 #406)

The composed care-phase access rule lives in ONE place —
`gateway/app/services/care_access_policy.py` — the same
single-source-of-truth principle as the analysis consent policy
(`consent_policy.py`, #422). Consumers evaluate a read via
`POST /api/v1/patients/<guid>/care-access-check`; nothing is
re-implemented consumer-side.

## The zone model (v3 spec §4, locked 2026-07-03)

| Zone | Relation | Rule | access_basis |
|---|---|---|---|
| 1 | Reader's care unit == authoring unit | Always allowed — spärr never hides a unit's data from itself | `same_unit` |
| 2 | Same care organisation, different unit (*inre sekretess*) | Blocked by an active **inre spärr** (clinic-scoped `PatientBlock` on the authoring unit); otherwise allowed | `same_org` |
| 3 | Different care organisation (*sammanhållen vård*, Lag 2022:913 §5) | Requires an active `PatientConsent` for the **reading** caregiver (*allow_sharing_in_care*) **AND** no **yttre spärr** (caregiver-scoped block on the authoring caregiver) **AND** no inre spärr on the authoring unit (a clinic block hides that unit's data outside the unit, org boundary or not) | `cross_org_consent` |

Denial reasons (stable codes): `inre_sparr`, `yttre_sparr`,
`no_sharing_consent`.

Spärr mapping: `PatientBlock.source_scope_type='clinic'` **is** the
inre spärr; `'caregiver'` **is** the yttre spärr. Lift mechanics
(consent lift, auto-re-imposing indispensable-care lift, concept-level
mechanical filter) are unchanged — the policy consults
`PatientBlock.is_active()` only.

## Nödöppning (PDL 6 kap 5 §)

`POST /api/v1/patients/<guid>/emergency-access` creates an attested,
time-bound `EmergencyAccess` grant for the **reading unit**:

- Role-gated: SU admin or a role in `IPS_EMERGENCY_ACCESS_ROLES`
  (falls back to `IPS_INDISPENSABLE_LIFT_ROLES`, default
  `physician,admin`).
- Requires `reason` (written justification, verbatim in the audit) and
  `attest: true` (explicit confirmation of an acute risk to the
  patient's life or health).
- Default 24 h, max 7 days (`expires_in` seconds). INSERT-only; never
  edited, simply expires.
- While active, `care-access-check` allows zones 2–3 past spärr AND
  absent consent with `access_basis=emergency`.
- Audited as `emergency_access.granted` with
  `detail.access_basis=emergency` + the operator session id (#191/#203
  chain of custody); every later check that rides the grant audits
  `care_access.check` with `access_basis=emergency`.
- Patient notification: the grant row (with `notified_at`) is the
  notification source; the patient-portal banner for emergency access
  ships with the full portal reconcile (#437) once the patient-facing
  copy has legal sign-off (#242 family). The audit trail is visible to
  the patient via the portal audit link today.

Distinct from the **indispensable-care lift** (#244, PDL 4 kap 5 §):
a lift alters one block row and requires a concept-level mechanical
filter; nödöppning overrides the whole composition for one reading
unit, blocks untouched.

## API

```
POST /api/v1/patients/<guid>/care-access-check
  { reader_care_unit_guid, reader_care_organisation_guid?,
    author_clinic_guid, author_caregiver_guid? }
→ { allowed, zone, access_basis, reason, emergency_access_guid? }

POST /api/v1/patients/<guid>/emergency-access
  { reader_care_unit_guid, reader_care_organisation_guid?,
    reason, attest: true, expires_in? }
→ 201 EmergencyAccess.to_dict()
```

Every check — including denials — writes an X1-shaped audit row
(`purpose=care`, `access_basis`, zone, reason, both contexts).

## Tests

`tests/test_care_access_policy.py` (pure rule, all zones × block ×
consent × emergency) + `tests/test_care_access_routes.py` (endpoints,
role gate, attestation, audit shape, unit-scoping, expiry).
