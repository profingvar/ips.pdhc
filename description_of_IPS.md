# IPS Server (FHIR R5) — Project Description for External Readers

This project is a Python-based backend service for producing and serving an **International Patient Summary (IPS)** using **FHIR R5**. It combines a standards-oriented FHIR REST surface (so that external systems can interact with patient and clinical resources in familiar FHIR terms) with an application-oriented API (so that operational workflows like “create an IPS card”, “snapshot it”, “push it to a destination”, and “audit access” can be expressed in a pragmatic way).

At its core, the service maintains FHIR resources (such as `Patient`, `Condition`, `Observation`, etc.) and can generate an **IPS document bundle** for a patient on demand (FHIR `$ips` operation) or persist a point-in-time **snapshot** for later retrieval and delivery. A small administrative frontend is provided for operators (service status/metrics and basic inspection), but the main value of the project lies in the backend APIs and their security and operational posture.

## What the system does (end-to-end narrative)

An external system that wants to use IPS typically needs three things: a way to identify the patient, a way to store or reference clinical data, and a way to obtain an IPS document (and optionally distribute it). The IPS Server supports these needs in a sequence that can be understood as “phases”, even though the APIs can be used flexibly.

### Phase 1 — Identity, patient context, and trust boundaries

The first step is establishing **who is calling** the service and **which patient** the call relates to.

On the application API side (`/api/v1/...`), the service is built around the assumption that requests come from a trusted environment where the caller authenticates using an **SSO/OAuth-style Bearer access token**. The server validates that token by resolving the user against an external authentication service endpoint (the codebase config names this `OATH_BASE_URL`, but conceptually it is an OAuth/SSO “who am I” integration and resolves the current user via an `/api/auth/me`-style call). When validation succeeds, the resolved user identity is attached to the request context and becomes the “actor” used in audit logging.

On the patient side, the project uses a combination of:

- a **FHIR logical id** for `Patient.id` (commonly a UUID/GUID), used for references within FHIR resources and API paths, and
- an optional national identifier representation (for example a Swedish personal number stored in `Patient.identifier`), which is useful for search and integration but should be treated as sensitive data.

This separation matters for design and security: the system can operate on stable internal identifiers while still supporting real-world identifiers for interoperability, without assuming that the latter are safe to expose or use as primary keys everywhere.

### Phase 2 — Resource ingestion and persistence

Once a patient exists, clinical facts can be ingested either through the FHIR REST surface (`/fhir/...`) or through application workflows that create mock or manual data for testing and demonstration.

The service stores FHIR resources in a PostgreSQL database in a way that favors flexibility and forward compatibility: resources are persisted as **JSON** (typically `JSONB`) along with supporting indexing/search metadata. This “store the canonical resource JSON” approach is widely used in FHIR servers because it:

- preserves the original semantic structure of each resource,
- avoids brittle table-per-field modeling,
- allows incremental support for new resource fields and profiles, and
- keeps “what was received” auditable and reproducible.

The trade-off is that search, validation, and performance require deliberate indexing and limits. The project’s structure reflects that separation: “FHIR storage” and “IPS generation” are handled as services, while the route layer remains thin.

### Phase 3 — IPS generation (FHIR `$ips` and filtered modes)

The IPS is generated as a **FHIR Bundle** conforming to the IPS profile (the project references the canonical IPS profile URL). Generation can happen in multiple ways:

- a standards-aligned path via FHIR `$ips` (for interoperability), and
- an application path that can generate “full” or “minimal” content (useful when different consumers want different clinical breadth).

Conceptually, IPS generation is a deterministic transformation:

1. identify the patient and a time context (“as of” / composition date),
2. collect the relevant clinical resources for that patient (conditions, observations, medications, allergies, immunizations, procedures, and document references/diagnostic reports),
3. assemble them into an IPS document bundle with appropriate resource references and metadata.

This phase is where correctness considerations dominate: FHIR compliance, reference integrity, and consistent patient linking must be preserved. Because IPS is typically shared across system boundaries, this is also where privacy considerations are most visible (only include the intended data categories; avoid leaking unrelated resources).

### Phase 4 — Cards and snapshots (operationalizing IPS)

In real deployments, “generate an IPS right now” is not the only requirement. Consumers often need:

- a stable handle for an IPS concept (a “card” that represents a patient-facing or workflow-facing summary), and
- immutable versions (“snapshots”) that capture what the IPS looked like at a specific point in time.

The application API supports this operational model:

- **IPS cards** represent a named/owned summary concept tied to a patient (and optionally a clinic context).
- **IPS snapshots** store the generated bundle JSON for later retrieval, comparison, and delivery.

This separation is a design choice that improves auditability and reproducibility: once a snapshot exists, the exact payload delivered to downstream systems can be re-served, re-validated, and referenced in logs, rather than being a moving target that depends on current database state.

### Phase 5 — Distribution (“push jobs”) and external destinations

Many IPS workflows end with distributing the IPS to another system: a care planning service, a FHIR endpoint, or an integration gateway. The project models this as:

- **push destinations** (where to send),
- **push jobs** (what was queued/sent, status, retries, and errors).

This phase is intentionally decoupled from immediate request/response flows. Even when the API creates a push job synchronously, the “execution” aspect is naturally suited to background processing with retries and proper observability. The codebase already includes the data model and API layer to manage this lifecycle; production deployments would typically add a worker component (or scheduled executor) to perform delivery with rate limits and backoff.

### Phase 6 — Operations, monitoring, and auditing

Healthcare integrations are operational systems. The project includes endpoints and database structures aimed at safe operation:

- a basic **health** endpoint (`/api/v1/health`) for uptime checks,
- a **metrics** endpoint (`/api/v1/metrics`) for high-level service statistics,
- an **audit log** endpoint (`/api/v1/audit`) and audit events persisted to the database, including events for sensitive actions like retrieving an IPS bundle (“IPS blob read”).

Auditing is treated as a first-class capability: the server records who accessed what, when, and through which API path. This is essential both for security compliance and for debugging integration issues.

## Architecture and design considerations

The system is structured as a set of independently understandable layers:

1. **HTTP/API layer (Flask + blueprints)**  
   Exposes both FHIR (`/fhir/...`) and application (`/api/v1/...`) endpoints. Error handling favors FHIR-style `OperationOutcome` where appropriate.

2. **Service layer (business logic)**  
   Handles IPS bundle generation, API key lifecycle logic, storage abstractions, and integration calls (SSO user resolution).

3. **Persistence layer (SQLAlchemy + PostgreSQL + Alembic)**  
   Manages schema migrations and database sessions. Data is partitioned conceptually into an “application schema” (cards, snapshots, destinations, jobs, audit events, clinics) and a “FHIR schema” (resource JSON storage and related search/index metadata).

4. **Admin frontend (optional)**  
   A lightweight operator UI served separately (port 9002) that targets the backend APIs.

This separation is deliberate. In healthcare projects, the ability to evolve the FHIR surface, the operational workflows, and the security integration independently is often more important than micro-optimizing for a single use case early.

## Security model (what is protected, and how)

From an external reader’s perspective, the project’s security posture can be understood as four concentric controls: authentication, authorization policy, data minimization, and auditability.

### Authentication

For the application API, requests are expected to include an **`Authorization: Bearer ...`** token. The server validates the token by calling an external auth/SSO service and fails closed when the user cannot be resolved (expired token, upstream error). A small set of endpoints are explicitly whitelisted (health/metrics) to support monitoring without credentials.

The project also contains an **API key** concept (create/rotate/revoke/expire) for integrations where key-based auth is desired. In deployments, it is common to support both SSO-based user calls and key-based machine-to-machine access; whichever mode is used, keys and tokens must be treated as secrets and never logged.

### Authorization and scope

Authentication answers “who are you”; authorization answers “what are you allowed to do”. The codebase currently emphasizes authentication and operational logging; production hardening typically adds:

- explicit **role/scope checks** (e.g., admin vs clinic operator vs service account),
- clinic/group scoping (ensuring a user can only act within permitted clinic contexts),
- patient access rules (consent, assignment, or other policy),
- endpoint-level restrictions (read-only vs write).

The project’s data model (clinics, patient-clinic assignments, audit actor fields) is prepared for this evolution even if policy is still being tightened.

### Data minimization and safe defaults

IPS generation can be “full” or “minimal”, reflecting that not all consumers need all data categories. This is both a usability feature and a privacy control: the default integration should transmit only what is required for the clinical or operational purpose.

Additionally, the system uses structured resource types rather than ad-hoc payloads wherever possible, which makes it easier to validate and reason about what data is included.

### Auditability and non-repudiation

Sensitive reads (like retrieving a snapshot bundle) are logged with actor identity, patient id, timestamp, and request path. This supports incident response, regulatory compliance, and debugging. In production, audit logs should be treated as security-relevant records: they need retention policies, integrity protections, and restricted access.

## Deployment and operational considerations

The server is designed to run locally for development and to be deployable in containerized environments:

- **PostgreSQL** can be run via Docker Compose (commonly exposed on port 9000 in local setups), or an external DB can be used with environment configuration.
- The **API** typically runs on port **9001** and the optional **admin UI** on **9002**.
- Database schema changes are managed through **Alembic migrations**.

Operationally, deployments should consider:

- **TLS termination** (the application should be behind a reverse proxy that enforces HTTPS),
- **CORS restrictions** (only allow known admin UI origins; the service supports an allowlist via environment configuration),
- **rate limiting** and request size/time limits (protect against abuse and accidental overload),
- **timeouts and retries** for external auth service calls,
- **structured logging** with careful redaction (never log tokens, keys, or raw patient identifiers unless explicitly required and protected),
- **separation of environments** (dev/stage/prod credentials and endpoints).

## Typical usage patterns (what external systems do)

An external consumer generally interacts with the IPS Server in one of these modes:

1. **FHIR-first integration**: create/search patient and related resources through `/fhir/...`, then call `$ips` to obtain an IPS bundle.
2. **Workflow/operations integration**: manage IPS cards and snapshots through `/api/v1/...`, retrieve snapshot bundles, and optionally create push jobs to send content to downstream services.
3. **Hybrid**: use FHIR endpoints for clinical ingestion and the application endpoints for operational handling (snapshots, audit, push).

In all cases, the overarching design goal is to make IPS generation **repeatable, inspectable, and controllable**: you can see what data is stored, generate summaries in predictable modes, snapshot results when you need immutability, and track who accessed which patient summaries.

