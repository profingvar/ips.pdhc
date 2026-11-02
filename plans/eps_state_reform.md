# EPS + patient state in ips.pdhc — what the job actually is

> **TICKETED 2026-11-02 as #876–#896** — epic #876, decisions #877, #879,
> #880 and **#894**, EPS conformance #881–#886 plus **#896** (export),
> the state layer **#895**, #888, #889 and #891, sso's companion identity
> #890, cross-cutting #892–#893. Marked `EPS <phase><n>:` to mirror the
> closed euIPS set (#788–#799).
>
> **A2 and C1 were refiled the same day** after the operator corrected the
> premise, and the renumbering is the board's behaviour, not a mistake:
> A2 #878 -> **#894**, C1 #887 -> **#895**. §3 above still carries the 1:1
> wording from the requirement as stated; the relationship is **1:N**
> (1:1 only per `(patient, fact_type, period)`), state changes are stored
> as EVENTS and the current state is projected, and diagnoses and alerts
> are REFERENCED from icd11.pdhc and alert.pdhc rather than owned here.
> #894 carries all three corrections and the three-way decision that
> replaced the two-way one.
>
> Each ticket body carries the measurement that justifies it and points back
> here. **They reference each other by PHASE LABEL, never by number**: the
> board has no edit, so a refined ticket is deleted and recreated with a new
> number, which would silently dangle every numeric cross-reference.
>
> Two corrections to this document were found while ticketing, and are recorded
> in #883 rather than edited into §2.5 above:
> `euips_sections.py:129`'s *"THE MISSING ONE. No Device resource type exists"*
> is **stale** — `_devices()` exists at `euips_recommended.py:266`, is
> dispatched via `_BUILDERS` and is called from `mock_generator.py:321`, all
> since 2026-10-07. The real gap is that `Device` is absent from
> `SUPPORTED_RESOURCE_TYPES`, so the HTTP API refuses it and the
> CapabilityStatement does not advertise it, while `resource_type` is a free
> `String(64)` so storage already works. Narrower and cheaper than stated.

**Assessment, 2026-10-30.** Sources: `docs/EPS_patientoversikt.docx` and
`docs/EPS_sektioner_vokabularer.xlsx` (both dated 2026-10-30), measured against
this repo's code and every sibling repo. Nothing here was read from memory;
every number below has the command that produced it.

Companion to `plans/euips_reform.md` (epic #788, tickets #789–#799), which is
built on an **older and different** source document,
`docs/EU_Patient_Summary_ICD11.docx`. This one does not replace that plan — it
measures what the newer EPS specification adds to it, and what the state model
needs that neither plan has.

---

## The headline: this is three jobs, and they differ by a factor of ten

| | job | size | blocked on |
|---|---|---|---|
| **1** | Rename IPS → EPS | small to edit, **large to deploy** | an operator, DNS, TLS, nginx |
| **2** | EPS conformance | **mostly already built** | one architecture decision (R4/R5) |
| **3** | Patient state with validity dates | **the real work** | three decisions, listed below |

They are separable and should be done in the order 2 → 3 → 1. The reasoning for
putting the rename last is in §1: it is the only one of the three that cannot be
undone without an operator, and it is the only one that buys no capability.

---

## 1. The rename, and why it should be last or not at all

### EPS is a specialisation of IPS, so the name is not a choice between them

From the source document: *"EPS är en specialisering av IPS. Ett giltigt
EPS-dokument är också ett giltigt IPS-dokument, men inte tvärtom."*

That is the whole argument. A service that serves EPS **also** serves IPS, by
construction. Renaming the service to EPS asserts the narrower of two true
statements, and it discards the broader one — which is the one nine of the
eleven consuming services actually want, because they are domestic and have no
EU exchange in scope.

The capability is EPS. The service is a patient registry. Those are different
nouns, and the current name is closer to the second than `eps.pdhc` would be.

### What a rename would actually cost, measured

Counted with `find | xargs grep`, not a tree-wide `grep -r`, because `grep` on
this machine is `ugrep` and honours the root `.gitignore` — which is a
whitelist, so a tree-wide search silently skips every service repo. **The first
count this assessment made was wrong for that reason**: it reported 3 matching
*lines* for `IPS_BASE_URL` where the real figure is 66 matching *files*. Both
halves of that were wrong — the filter, and comparing a line count against a
file count — which is why the table below says which unit it is in.

| identifier | files |
|---|---|
| `IPS_BASE_URL` | **66** |
| `IPS_API_KEY` | **44** |
| `ips.pdhc.se` | **38** |
| `ips-app-1` / `ips-db-1` | **16** |

~411 occurrences across 15 directories. Per service:

| service | occurrences | | service | occurrences |
|---|---|---|---|---|
| ips.pdhc itself | 91 | | analyse.pdhc | 41 |
| dashboard.pdhc | 60 | | cdr.pdhc | 39 |
| request.pdhc | 46 | | cdr_6.pdhc | 25 |
| contract.pdhc | 44 | | icd11.pdhc | 16 |
| rosetta.pdhc | 14 | | gateway.pdhc | 11 |
| sim.pdhc | 8 | | tools 6, pdhc 3, alert 5, miserver-ops 2 | 16 |

### The good news: the API paths do NOT carry the name

The paths named across the sibling repos are `/api/v1/fhir/…`,
`/api/v1/patients/…`, `/api/v1/patients/analysis-filter`, `/api/v1/clinics/…`,
`/api/v1/patients/<g>/blocks/check` and `/api/v1/patients/<g>/consents`.

Those raw counts are **not** usable as "calls made on ips" and are deliberately
not quoted here: several siblings have FHIR surfaces of their own — cdr's is
`/api/v1/fhir/<type>` too — so a count of the string conflates calls *to* ips
with each service's own routes. Separating them needs per-call-site reading,
which this assessment did not do.

What IS established, because it is a search for absence rather than a count:
**not one sibling names a path containing `ips`.** This service's own
ips-named blueprint serves `/cards` and `/snapshots`, and nobody outside calls
either. So a rename does not break a single cross-service call.

### The bad news: it is a DNS, TLS, proxy and compose-project change

Which puts it outside what can be done from here (CLAUDE.md §14, §15):

* **`eps.pdhc.se` would be a NEW name.** `ips.pdhc.se` already has a DNS
  record, an nginx vhost and a certificate; the new one has none of the three,
  and `ips.pdhc.se` then has to keep answering because 38 files name it.
  Editing the reverse proxy is explicitly operator-only, and a bad config there
  takes down every service at once. Two live vhosts for one service is also how
  cdr4 and cdr5 ended up as enabled vhosts that 502 — a rename leaves exactly
  that kind of residue if the old name is ever retired carelessly.
* `COMPOSE_PROJECT_NAME` is **not pinned anywhere in this repo** — verified, no
  occurrence in any `.yml`, `.sh`, `.env*` or `.md`. The container names
  `ips-app-1` / `ips-db-1` mean the project is currently `ips`, so a rename
  changes the compose project name. That is the shape of dashboard's #113, and
  a release swap under an unpinned project name silently creates a *second*
  parallel project with colliding ports and volumes.
* **The volume is the dangerous part, and it is also the one piece of good
  luck.** `gateway/docker-compose.yml:36-39` declares `pgdata` as
  `name: ips_pgdata`, `external: true`. External means compose does not own it,
  so a project rename cannot orphan it. The data is therefore safe **as long as
  nobody also renames the volume**: renaming a volume means dump-and-restore,
  and a wrong-direction copy between volumes during the March 2026
  gateway→planp rename destroyed a production database irrecoverably. Pin the
  project name, leave `ips_pgdata` alone.

### Recommendation

**Do not rename the service.** Add EPS as a declared capability: an EPS
Composition profile, an EPS Bundle endpoint, `eps` in the CapabilityStatement.
If the name must change for external reasons, do it after §2 and §3 are done,
pin `COMPOSE_PROJECT_NAME` first, and keep `ips.pdhc.se` as a permanent alias
rather than a redirect — 38 files name it.

---

## 2. EPS conformance — mostly built, and the refusal to guess paid off

`gateway/app/services/euips_*.py` is **2,795 lines across nine modules**, with a
section catalogue (`euips_sections.py`), a document header (`euips_header.py`),
obligation tiers, a batch builder and a report. #791 already decided that
**section content lives in `fhir_resources` and no new tables are added**, which
remains right under EPS for the same reason.

So the gap is not "build EPS". It is five specific differences, measured by
comparing this repo's catalogue against the document's 17 sections
programmatically rather than by eye.

### 2.1 Two LOINC codes this repo deliberately refused to guess — now available

`euips_sections.py` carries `CODES_VERIFIED = False` and leaves a section's
LOINC as `None` rather than invent one. Three sections have `None` today. The
EPS document supplies two of them:

| section | was | EPS gives |
|---|---|---|
| `alerts` | `None` — *"LOINC code not established for this EU addition — left None rather than guessed"* | **104605-1** |
| `travel_history` | `None` | **10182-4** |

This is the cheapest win in the whole assessment, and it only exists because
the code refused to guess. A guessed value would have had to be found and
unpicked instead.

### 2.2 Two sections EPS has that this repo does not

| LOINC | section | content |
|---|---|---|
| **81338-6** | Patient Story / Patientens berättelse | free text |
| **11329-0** | Patient History / Sjukdomshistoria — **EPS-unique** | free text |

Both are free text in practice per the document, so the cost is catalogue
entries plus narrative generation, not terminology work.

### 2.3 One section EPS deliberately does NOT profile, and we have it

`past_illnesses` (**11348-0**) exists here as OPTIONAL. The document is
explicit: *"En sektion utelämnad. IPS-sektionen History of Past Illness
profileras inte i EPS."*

This is a decision, not a mapping. Resolved conditions currently have a defined
home and under EPS they do not; the nearest candidate is Patient History
(11329-0), which is free text. **Dropping the section would turn coded resolved
conditions into prose**, and `euips_sections.py` already warns that `problems`
and `past_illnesses` are told apart *only* by `clinicalStatus` — so a
careless merge puts resolved illnesses in the active problem list.

Recommendation: keep 11348-0 as a domestic section, and map it into 11329-0
only when building an EPS document for export. A valid EPS document may not
carry it; our own storage may.

### 2.4 `patient_provided` has no EPS counterpart at all

An EU_ADDITION section here, distinguished by the resource's source/performer.
EPS has Patient Story and Patient History; neither means "information the
patient asserted". Same treatment as 2.3: domestic, not exported.

### 2.5 Two obligations are upgraded, and one of them has no data

| section | this repo | IPS | **EPS** |
|---|---|---|---|
| `procedures` (47519-4) | recommended | 0..1 | **1..1** |
| `devices` (46264-8) | recommended | 0..1 | **1..1** |

EPS makes mandatory exactly the section this repo's own catalogue note calls
**"THE MISSING ONE"**: *"No Device resource type exists in fhir_resources at
all."* So EPS turns a section with zero rows into one that may never be empty.

It is not as bad as it sounds, because #791's absent-code machinery already
handles this: a mandatory-but-empty section is written as a real resource
carrying the IPS absent/unknown code, and `devices` already has
`absent_code="no-known-devices"`. The work is generating that resource for every
patient and extending `fhir_resources` to carry the `Device` /
`DeviceUseStatement` types.

**This is where alert.pdhc meets EPS.** Section 46264-8 is implants, and
alert.pdhc's `Förekomst av implantat` selection is exactly that list — 19
national selections, of which the implant one is ICD-10-SE `Z95.x`. The
`alert_assertion` table built today carries `code_system` + `code` +
`national_term`, which is what a `DeviceUseStatement` needs. Wiring alert's
step 5.b into section 46264-8 fills the mandatory section from real selection
data rather than from a generator.

### 2.6 The one that is a genuine architecture decision: **EPS is R4, we are R5**

The document states EPS is **FHIR R4**, STU 1 Ballot. This service declares
`fhirVersion: 5.0.0` (`gateway/app/fhir/fhir_routes.py:280`) and the euIPS
builders emit R5 shapes **deliberately and with the differences flagged**:

* `Coverage` in R5 requires `kind` and uses `insurer`; R4 used `payor`
  (`euips_header.py:40`)
* `Composition.attester.mode` in R5 is a `CodeableConcept`; in R4 a plain code
  (`euips_header.py:42`)

So the two disagree on precisely the elements a reviewer was already asked to
look at. A conformant EPS Bundle cannot be R5, and this service's whole FHIR
surface is R5 — including the CapabilityStatement that nine services read.

Three options, and this needs a decision before any conformance claim:

| | approach | cost |
|---|---|---|
| **A** | Keep R5 internally, **render** R4 on the EPS export path only | medium; one serialiser, two element shapes, no sibling impact — **recommended** |
| **B** | Move the service to R4 | large, and backwards: R5 is the newer standard and ten siblings are built on this R5 surface |
| **C** | Claim EPS conformance from R5 output | not available — it would be false |

A is recommended because the differences are enumerable (the repo has already
enumerated two of them) and because the export path is the only place
conformance is claimed.

### 2.7 Conformance may not be claimed yet, and the code already says so

`CODES_VERIFIED = False` is deliberate: the LOINC and absent/unknown codes were
written from knowledge of the IG, not from a fetch of the published
CodeSystem and ValueSet. The EPS document is a **CI-build** of a **STU 1
Ballot**, which is a draft of a draft. The existing plan's rule — say *"all
required sections present"*, never *"EU-conformant"* — holds unchanged, and the
new document does not lift it. Flipping the flag needs a fetch of the published
IG, which is network work nobody has asked for yet.

### 2.8 The three mapping debts, unchanged and not ours to pay

| area | mapping | where it belongs |
|---|---|---|
| Lab | NPU → LOINC | rosetta.pdhc / termbank.pdhc |
| Procedures | KVÅ → SNOMED CT | termbank.pdhc |
| Medicines | NPL → ATC / EDQM / EMA SMS | termbank.pdhc |

None of these is ips work. The document is clear that Swedish source data is
largely free text or NPU/KVÅ/NPL-coded and must be mapped, and that Snomed CT
uptake in Sweden is still low. Worth noting against alert.pdhc's D1: the Swedish
Snomed extension's translated IPS refset is the nearest thing to a Swedish
patient-summary vocabulary, and **the licence is free from Socialstyrelsen** —
which is a second data point on the open question of which Snomed licence is
actually held.

---

## 3. Patient state with validity dates — the real work

This is the part that is genuinely new, and the part the two existing plans do
not touch at all. The requirement as stated:

> all state information about a patient — address, contact, next-of-kin
> (including that person's access privileges), alert information and more —
> stored 1:1 on the patient card, while transactions are stored in the CDR.
> State data has a begin date and a possible end date.

Measured against the schema, that is **four separate gaps**, and one of them is
much larger than the other three.

### 3.1 There is no patient card. The thing with that name is a document.

`app/models/ips_card.py` — `ips_cards` — is 49 lines: `title`, `status`,
`mode='full'`, `created_by_guid`, `clinic_guid`, and a `snapshots`
relationship. It is a **generated summary document with versions**, not a state
record. `ips_snapshots` hangs off it.

So the name is taken, and it is taken by something whose meaning is almost the
opposite: a card in the requirement's sense is the *current truth about a
person*; `ips_cards` is *a rendering produced at a moment*. Reusing the name
would make every reader of this schema wrong. The state store needs its own
name.

### 3.2 Address, contact and next-of-kin are not in the schema at all

Searched every model for `address`, `telecom`, `contact`, `next_of_kin`,
`anhörig`, `relative`. The only hit is `audit_log.ip_address`, which is
unrelated.

They exist only inside `fhir_resources.resource_json`, and only because the
mock generator writes them (`mock_generator.py:238-261`):

```
"address":  [{"use": "home", "city": …, "country": …}]      # city + country only
"telecom":  [{"system": "phone", "value": "+4670…", "use": "mobile"}]
"contact":  euips_header.patient_contact(related)            # name, relationship, telecom
```

So there is a next-of-kin representation already — `RelatedPerson` plus an
inline `Patient.contact` mirror, deliberately generated from one list so the
two cannot disagree. **But it carries name, relationship and telephone and
nothing else.** No privileges, no validity period, no identity that could be
authenticated.

And the address is `city` + `country`. There is no street, no postcode. A
registry that is to hold "all state information about a patient" needs a real
address element, which in FHIR R5 is `Address` with `line`, `postalCode`, `city`
and `period` — and `period` is the begin/end date the requirement asks for,
already present in the standard.

### 3.3 Nothing anywhere has a validity period

Searched every model for `valid_from`, `valid_to`, `effective_from`,
`period_start`, `start_date`, `end_date`. The complete set of date-bounded
things in this service is:

| model | field | shape |
|---|---|---|
| `patient_block` | `expires_at`, `lift_expires_at` | **one-ended** |
| `emergency_access` | `expires_at` | one-ended |
| `api_key` | `expires_at` | one-ended |
| `patient_clinic_assignments` | `assigned_at` | **start only, no end** |

Every one is an expiry or a start, never an interval. `created_at` and
`updated_at` are everywhere, but those are *record* times — when we wrote the
row — not *validity* times, when the fact was true. `updated_at` has
`onupdate=utcnow`, which means current state is **mutated in place**: the
previous address is gone.

`patient_clinic_assignments` is the clearest example of the cost. It records
that a patient belongs to a clinic and *when that began*, with no way to say it
ended. So a patient who moves is either still assigned to the old clinic or has
no record of ever having been — and the roster endpoint
`/api/v1/clinics/<guid>/patients`, which sim.pdhc builds cohorts from, reads
exactly this table.

### 3.4 The favourable surprise: record time already exists, and is append-only

`fhir_service.update_resource()` does **not** update. It writes a new
`fhir_resources` row with `version_id + 1` and sets the previous row's status to
`superseded`. There is no history table because the table *is* the history.

That is half of what the requirement needs, and it is the harder half to add
later. What is missing is the other axis:

| axis | question it answers | status |
|---|---|---|
| **record time** — `version_id`, `created_at` | when did we come to know this? | **built** |
| **validity time** — begin / possible end | when was this true of the patient? | **absent** |

Two axes is a *bitemporal* store, and the pair is not optional for this
requirement: "the address was wrong in the register between March and July"
cannot be expressed with one axis, and that is the ordinary case for an address.

This is the same distinction `alert.pdhc` settled today as `asserted_at` versus
`recorded_at`, for the same reason — and the plan there records why merging them
makes the second question unanswerable. The vocabulary is already agreed inside
this platform; it just has not reached ips.

### 3.5 The large one: a next-of-kin with privileges is a new axis in the access model

`app/services/care_access_policy.py` is described in its own docstring as the
canonical single source of the zone rule, *"so no two consumers may enforce
different zone rules"*. Its vocabulary is:

```
zone_for(reader_care_unit_guid, reader_care_organisation_guid,
         author_clinic_guid, author_caregiver_guid) -> 1 | 2 | 3
```

Every argument is a **care** identity. Zone 1 is the same care unit, zone 2 the
same organisation, zone 3 everything else, and the bases are
`same_unit` / `same_org` / `emergency`. There is no zone, no basis and no
argument for *a private individual acting on the patient's behalf*.

`auth_service.py` does know `user_type == 'patient'`, so a patient can
authenticate. A relative cannot: there is no identity for them, and no rule that
would answer yes.

So "next-of-kin including access privileges" is not a column on a contact. It
is:

1. an **identity** for a private individual who is not the patient — which is
   an sso.pdhc question, not an ips one
2. a **grant** from the patient to that identity, scoped and time-bounded —
   which is new, and is the one piece of this that genuinely resembles
   `patient_consents` and should probably be modelled beside it rather than
   inside it, for the same reason advance directives were kept out of that
   table
3. a **new branch in `care_access_policy`** — the highest-blast-radius module
   in the repo, read by eleven services

Item 3 is the cost. Items 1 and 2 are ordinary work.

> **MEASURED AND CORRECTED 2026-11-02, while delivering #889.** The premise
> above — that item 3 is the cost because `care_access_policy` is read by
> eleven services — was wrong in BOTH directions.
>
> **Cheaper than stated.** A patient reading their own record does not go
> through `care_access_policy` at all. That module answers "may this CARE
> identity read data authored by that care identity?" and every argument is a
> care identity; the patient surface is gated by
> `auth_service.require_patient`, which never calls it. Inside ips,
> `evaluate_care_access` has exactly **two** call sites, both in
> `care_access_routes.py`. So a relative reading *as* the patient needed **no
> new zone and no new branch in the zone rule**, and the eleven consumers were
> untouched. #889's proxy decision is a separate function with its own basis
> (`patient_proxy`), added to the same module so its single-source-of-truth
> docstring stays true.
>
> **More expensive than stated, and this is the finding.** `require_patient`
> does not gate a data surface. It gates the patient's **self-determination
> controls**. Of the seventeen routes behind the patient identity, **ten are
> POST**, and they are create-block, **lift-block**, extend-block,
> create-consent and revoke-consent — each in both the JSON and the HTML
> surface.
>
> So a relative admitted through that decorator without a method gate could
> **lift the patient's spärr and then read what the spärr had been hiding**.
> That is an escalation chain, not an over-broad read, and it is the third time
> this platform has met the shape: #729 and #760 both found an identity added
> so it could READ that could also WRITE. EPS A3 forbids it directly — only the
> patient may INCREASE access, and lifting a spärr increases access.
>
> Hence the refusal of non-safe methods lives in ONE decorator rather than per
> route, plus a categorically reserved-action list so a future scope widening
> cannot silently un-refuse it. The single write a relative may perform
> anywhere in ips is ending their own grant (A3 clause 4), behind its own
> narrow decorator that never sets `g.patient_guid`.

### 3.6 Eleven consuming services, and the additive rule

The existing plan says nine. Measured today it is **eleven**: request, contract,
analyse, rosetta, dashboard, cdr, cdr_6, sim, icd11, gateway and alert — the
last two having arrived since that plan was written.

> **CORRECTED 2026-11-02 by #892, which is the ticket this paragraph asked
> for: the number is TEN, and the eleventh is a trap.**
>
> `alert.pdhc` is NOT a consumer. Its only ips references are two
> `os.environ.get` lines in `app/config.py` — no client, no call. It holds two
> config keys nothing reads, so setting or rotating them changes nothing. Same
> shape as the SSO External Partner secret that authenticates nowhere.
>
> The hand count also could not have found `sim.pdhc`, which uses
> `IPS_PDHC_BASE_URL` and `IPS_PDHC_API_KEY` while every other sibling uses
> `IPS_BASE_URL`. A grep for one spelling reports sim as a non-consumer;
> `icd11.pdhc` carries eight spellings of its own. The number has now been
> wrong three times in three counts — nine, then eleven, now ten — which is
> the argument for `tools/pin_ips_consumers.py` rather than for a better
> paragraph.
>
> That tool discovers the spelling (`IPS[A-Z0-9_]*`), walks each service
> directory explicitly, separates **calls** from **configures_only**, and
> diffs a committed baseline: a new consumer, or a config-only service that
> starts calling, exits non-zero. Narrowing informs and exits zero.
>
> Note what it does and does not answer. It answers "which services call ips at
> all" (ten). It does NOT answer "which services read `patient_index`", which
> is narrower and is the claim that table's own comment makes.

`patient_index`'s own comments state the rule this creates: *"nine sibling
services read this table — so every change here is additive by rule."* Three
additions already follow it (`generation_batch_guid`, `archived_at`, the opt-out
flags), each nullable with no default and each with a comment saying why it is
not a reuse of an existing column.

And `patient_index` is itself a **projection**: `_sync_patient_index()` rebuilds
it from the Patient resource on every write. So it is already a derived copy,
and putting state there would create a second source of truth for facts that
live in `fhir_resources` — the shape #779 and #771 were both about.

**That argues for the state store being its own table**, keyed on the patient,
append-only, with both time axes — and for `patient_index` to stay a thin
searchable projection.

---

## 4. Effort, honestly

Ranges, not points, and the reason for each range is the decision it waits on.

| | work | estimate | waits on |
|---|---|---|---|
| 2.1 | Fill the two LOINC codes | **~1 h** | nothing |
| 2.2 | Two new free-text sections | ~0.5 d | nothing |
| 2.3–2.4 | Decide domestic-vs-exported for 11348-0 and `patient_provided` | ~0.5 d | a decision |
| 2.5 | `devices` mandatory: resource types, absent-code generation | 1–2 d | nothing; 2–3 d more to wire alert.pdhc's implant selection in |
| 2.6 | **R4 render path for EPS export** | **3–5 d** | **decision A/B/C** |
| 2.7 | Verify codes against the published IG, flip `CODES_VERIFIED` | 1 d | permission to fetch |
| 3.1–3.4 | State store: new table, both time axes, address/contact/next-of-kin elements, read path | **5–8 d** | decision on where state lives |
| 3.5 | Next-of-kin identity + grant + the policy branch | **8–15 d** | sso.pdhc, and a decision on the privilege model |
| 3.3b | Give `patient_clinic_assignments` an end date | 1–2 d | additive, but eleven readers |
| 1 | The rename | 2–3 d of edits, **operator-gated** for DNS/TLS/proxy | an operator |

**Totals.** EPS conformance (§2) is **6–11 days** and most of it is already
done. The state architecture (§3) is **14–25 days** and almost none of it
exists. The rename (§1) is small to write and the only item that cannot be
undone from here.

The honest summary: **the EPS part is a finishing job; the state part is a new
subsystem.** The requirement reads as one task and is two, and the second is
roughly three times the first.

---

## 5. Three decisions needed before building

These are architecture decisions in the sense D1–D3 were for alert.pdhc — each
goes into every row that is written afterwards, and changing one later is a
re-migration.

**E1 — R4 or R5 on the EPS export path?** §2.6. Recommendation **A**: keep R5
internally, render R4 on export only. Without this decision nothing may claim
conformance, and with the wrong one ten siblings move.

**E2 — Where does state live?** A new append-only state table keyed on the
patient, or more resource types in `fhir_resources`? Recommendation: **a new
table**, because validity time is not a FHIR resource field in any uniform way
and because `patient_index` is already a projection — but note that #791 decided
the opposite for *clinical* content, and the two decisions must be told apart
explicitly or the next reader will think one of them is a mistake. State is not
clinical content; that is the distinction.

**E3 — What is a next-of-kin privilege?** A grant from the patient to a named
private individual, scoped to what and bounded by when? Or a flag on a contact?
The second is cheaper and cannot be audited, and this platform has already
learned (#729, #760) that an identity added so it could read could also write.
Recommendation: model it beside `patient_consents`, never inside it, and give it
a validity interval from the start.

---

## 6. What this assessment did NOT measure

Stated so that none of it is mistaken for checked.

* **The live database.** No row counts, no check of whether any patient actually
  carries an address today. The existing plan's finding that 110 of 150 patients
  had no clinical resources at all was measured on 2026-10-07 and may have
  moved.
* **The server.** No `ssh`, no `docker inspect`. The compose-project finding is
  from the repo and the container names in CLAUDE.md's table, not from the
  running platform. Confirming it is a production touch.
* **The published EPS IG.** Everything about EPS here comes from the two
  documents in `docs/`, which are themselves a reading of a CI-build of a STU 1
  Ballot. `CODES_VERIFIED` stays `False`.
* **Whether `patient_provided` and `past_illnesses` have EPS homes I have not
  found.** I compared 17 sections against 17 by LOINC. A section could
  correspond semantically under a code I did not match.
* **sso.pdhc's identity model**, which decides most of E3's cost.
