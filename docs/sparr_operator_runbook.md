# Spärr — operator runbook

For a clinician operator who is about to perform an **indispensable-care
block lift** under PDL Ch 4 § 5. Cross-linked from the admin lift UI;
keep both pointed at the latest commit so the wording stays in sync.

This page is opinionated about *when* you may lift; it does **not**
replace clinical judgement on *whether* a given case meets the
indispensable-care bar. If in doubt, treat as out-of-scope and seek
your medical director's sign-off before lifting.

---

## 1. When the law allows you to lift

The right to override a patient's spärr lives in **PDL Ch 4 § 5**
(patientdatalagen, 2008:355). The lift is lawful only when the
patient's data is **indispensable** (Swedish: *oundgänglig*) to the
care the patient needs *now*. "Useful", "convenient", or "likely to be
informative" do not meet the bar.

### What "indispensable" actually means

| Situation | Indispensable? |
|---|---|
| Unconscious trauma patient; no medication history available locally | **Yes** — drug interactions / allergies are life-safety |
| Active acute psychiatric episode; clinician needs prior crisis plan | **Yes** — the prior plan materially changes immediate management |
| Outpatient visit; clinician is curious about earlier diagnoses | **No** — convenience, not indispensable |
| Patient declined to share specifically; you disagree with the choice | **No** — the patient has the right to block, full stop |
| Research / quality-improvement work | **No** — never indispensable; out of scope of § 5 |

The test is not "would this help?" — it is "without this, can I
deliver the care the patient needs?". If the answer is "I could but
it would be worse," **don't lift**.

### What the lift will NOT do

- The lift does **not** un-block the patient permanently — it
  auto-re-imposes after `lift_expires_at` (default 24 hours, see § 4).
- The lift does **not** widen beyond the concept set you name in
  `concept_guids` — that's the *mechanical filter* (legal confirmed
  2026-06-04 as **required**, not advisory). Read elsewhere is still
  blocked.
- The lift does **not** suppress notification of the patient — every
  indispensable-care lift fires a patient-portal notification (#210
  copy bundle, `indispensable_care_notification`). The patient will
  see your name, the caregiver, the reason you wrote, and the audit
  link.

### Vårdnadshavare exception

For a patient under 18, a vårdnadshavare (parent/guardian) cannot
lift the child's block from the patient portal — that path is gated
to the patient's own session. A vårdnadshavare who has lawful access
*and* meets the indispensable-care bar must lift via the same admin
route a clinician uses (this runbook). The lift is recorded with the
clinician's user_guid as the actor, never with the
vårdnadshavare's — the audit row is the source of truth for the
chain of custody.

---

## 2. How to lift via the admin UI

The admin UI fronts `POST /api/v1/admin/blocks/<block_guid>/lift`.

### Prerequisites

- You are authenticated as a user with `is_superuser=True` **or** a
  role in `IPS_INDISPENSABLE_LIFT_ROLES` (default
  `physician,admin` — operators on the macmini can broaden this via
  env, see § 6).
- The block you intend to lift is currently **active** (the UI hides
  already-lifted blocks; if you don't see one, refresh — someone may
  have lifted it ahead of you in the last 24 hours and it's already
  exposing data).
- You have a written **reason** (PDL § 5 mandates written
  justification — see § 3 below for what to write).
- You know the **concept GUIDs** you actually need. The UI offers a
  concept picker tied to plan.pdhc's concept tree; if you can't
  enumerate them, **don't lift** — bypassing the mechanical filter
  with an over-broad concept list is the most common audit finding
  in pre-launch reviews.

### Step-by-step

1. **Find the block.** From the patient lookup, open the patient's
   active blocks list. Each row shows the source caregiver / clinic,
   the date it was created, and any prior lift history.

2. **Open the lift form** for the block in question. The form has
   four required fields and two optional ones:

   | Field | Required | Notes |
   |---|---|---|
   | `reason` | Yes | Free text, persisted verbatim into the audit row. See § 3 for what makes a good reason. |
   | `concept_guids` | Yes | Mechanical filter — list of concept GUIDs you need to see. The lift exposes ONLY these concepts. |
   | `expires_in` | No | Seconds; defaults to 24 × 3600. Shorten if you only need an hour; do not lengthen casually. |
   | `from_date` | No | ISO 8601; further narrows the window. Use when the relevant clinical event is from a known prior episode. |
   | `until_date` | No | ISO 8601; pairs with `from_date`. |

3. **Confirm and submit.** The UI shows you a final summary including
   the projected `lift_expires_at` timestamp. Read it before clicking
   submit — the audit row is going to quote you.

4. **Read the data you came for.** Do not browse beyond the concept
   set you listed; every read against the lifted scope is audited
   under the same `lift_expires_at` window.

5. **The lift auto-re-imposes** at `lift_expires_at` via the
   `flask sweep-blocks` cron (#202). You do not need to do anything
   to restore the block.

If you needed less than the full 24 hours, you may explicitly lift
the lift (i.e., re-impose the block early) from the same admin form;
the audit row notes the early re-impose.

---

## 3. What gets audited and who can see it

Every indispensable-care lift writes **one** AuditLog row with:

- `event_type = "block.lifted"`
- `patient_guid` = the patient
- `resource_type = "PatientBlock"`, `resource_guid` = the block
- `actor_guid` = your user GUID
- `actor_type = "user"`
- `detail.mechanism = "indispensable_care"`
- `detail.reason` = your reason verbatim
- `detail.lift_concept_guids`, `detail.lift_from_date`,
  `detail.lift_until_date`, `detail.lift_expires_at`
- `detail.admin_route = true` (distinguishes this from the staff
  patient-scoped path)
- `session_id` = your SSO session (ticket #203 / #191)
- `ip_address`, `request_path`, `request_method`

That row is **immutable** — no UI route can edit it. The patient sees
the same row's projection through the audit-link in their
indispensable-care notification (#210).

### Who can see audit rows

- **The patient**, via the portal audit endpoint, scoped to her own
  patient_guid.
- **You and your clinic colleagues**, via the staff audit endpoint,
  scoped to your `PatientClinicAssignment`.
- **The PDL kontroller** at your caregiver (the data-protection
  officer or equivalent), who has unrestricted read against
  AuditLog for compliance review.
- **No one else**, ever. AuditLog is not exposed to research /
  analytics / dashboards.

### What a good `reason` looks like

The reason is the load-bearing field for any later compliance
review. It must say *why* the lift was indispensable, not just *what*
you did. Examples:

- ✅ "Unresponsive trauma patient, no allergy list locally; pulling
  prior allergies + current meds from primary-care caregiver to
  guide induction."
- ✅ "Active psychotic episode in ED; pulling prior crisis plan from
  psych team at <caregiver> to inform restraint / sedation choice."
- ❌ "Background." — does not say why indispensable.
- ❌ "Patient consented verbally." — that's a consent lift, not
  indispensable care; use the patient-scoped consent route, not this
  route.

Write the reason as if a reviewer who wasn't there will read it six
months from now.

---

## 4. The 24-hour auto-re-block

`lift_expires_at` is set at lift time (default `utcnow() + 24h`,
override via `expires_in`). The block does **not** stay lifted past
that time:

- The `PatientBlock.is_active()` method treats the block as active
  again as soon as `lift_expires_at` passes — even **before** the
  background sweep runs. Consumers reading the row see the truth
  immediately.
- The `flask sweep-blocks` cron (#202) walks expired lifts hourly
  and fires a `block.re_imposed` webhook so cache subscribers
  (request.pdhc dispatcher, dashboard.pdhc cache) drop the relevant
  entries.
- If the indispensable-care need persists past the lift window
  (rare in practice — most indispensable scenarios resolve within
  hours), you may lift again. **Each lift is a separate audit row.**
  Repeated lifts on the same block are a strong signal to a
  compliance reviewer that the situation isn't actually "in-the-moment
  indispensable" and should be re-evaluated.

The 24-hour default was confirmed lawful by counsel 2026-06-04. Do
not raise it without a corresponding case-by-case justification in
the `reason` field.

---

## 5. Notification to the patient

Every indispensable-care lift triggers a patient-portal notification
following the template at
`gateway/app/copy/sparr_copy.json::indispensable_care_notification`
(ticket #210). At time of writing the copy is **draft pending legal
review**; once approved, the portal will deliver it via the channels
the patient has configured (email primary; SMS if registered).

The notification carries:

- The caregiver that performed the lift.
- The timestamp of the access.
- Your `reason` verbatim.
- The concept-set scope.
- The lift expiry timestamp.
- A link to the full audit row.

You do not need to (and should not) inform the patient separately —
the notification is the patient's record of the access. Calling the
patient on top of the notification is fine when the clinical context
warrants it; it is not required by the law or by this runbook.

---

## 6. Operator config knobs

Set on the macmini via the service's `.env` (see § 1 of CLAUDE.md for
the env-file contract):

| Env var | Default | Purpose |
|---|---|---|
| `IPS_INDISPENSABLE_LIFT_ROLES` | `physician,admin` | Comma-separated list of roles permitted on `POST /api/v1/admin/blocks/<g>/lift`. SU admins always pass regardless. |
| `IPS_WEBHOOK_SECRET` | unset | Required for `block.lifted` / `block.re_imposed` webhooks to fire. |
| `IPS_WEBHOOK_TARGETS` | empty list | Comma-separated URLs that should be notified on block events. |

---

## 7. Cross-references

- **Code:** `gateway/app/api/admin_blocks_routes.py` (route),
  `gateway/app/services/block_expiry_service.py` (sweep),
  `gateway/app/copy/sparr_copy.json` (patient notification text).
- **Tests:** `gateway/tests/test_admin_blocks_lift.py`,
  `gateway/tests/test_block_expiry_and_webhook.py`,
  `gateway/tests/test_sparr_copy.py`.
- **Tickets:** #197 (PatientBlock), #201 (this admin route),
  #202 (expiry sweep + webhook), #208 (historical-data confirmation),
  #210 (patient copy).
- **Law:** PDL (2008:355) Ch 4 §§ 4-5; Lag (2022:913) § 5 for the
  cohesive-care interaction (relevant when the indispensable-care
  lift overlaps a cross-caregiver block).

---

## 8. Review log

This page MUST be reviewed by one clinical lead before the spärr
admin UI is exposed in production, per spärr_implementation_plan.md
§ 12.3. Record the review here when it happens:

| Reviewer (role, caregiver) | Date | Version reviewed | Notes |
|---|---|---|---|
| _pending_ | _pending_ | initial draft | |

When you click "lift" from the admin UI for the first time, this
section should already carry a signed-off row.
