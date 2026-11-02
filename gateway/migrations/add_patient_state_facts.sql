-- #895 (EPS C1): the bitemporal patient-state projection.
--
-- A NEW TABLE, so `db.create_all()` does create it on a fresh database. This
-- file exists for deployments where the schema already exists, and because
-- create_all() does not create the INDEXES declared in __table_args__ on an
-- existing table either. Idempotent.
--
-- DERIVED, never authored. Every row comes from `fhir_resources` (Patient
-- versions) or `patient_clinic_assignments`, and
-- `services/patient_state.rebuild_for_patient()` deletes and re-derives rather
-- than patching. So this table can always be dropped and rebuilt, which is
-- what makes it a projection and not a second source of truth -- the role
-- `patient_index` already plays. #894 (EPS A2) chose this shape over a new
-- authored table and over more resource types in `fhir_resources`.
--
-- TWO TIME AXES, and the pair is not optional:
--
--     validity   valid_from / valid_to          when was this TRUE of the patient
--     record     recorded_at / recorded_until   when did WE know it
--
-- A patient moves in March and tells us in July. One axis cannot express "the
-- register was wrong between March and July", and that is the ordinary case
-- for an address. Adding the second axis later is a re-migration, so it goes
-- in from the start.
--
-- `valid_from` is NULLABLE and NULL means "we do not know when this became
-- true" -- NOT "it became true when we recorded it". Measured 2026-11-02: no
-- Patient element in this service carries a `period`, so demographics have
-- NULL validity until #888 (EPS C2) adds real `Address.period`. Filling it
-- from `recorded_at` is the single-axis mistake this table exists to prevent.
--
-- Run on miserver:
--   docker exec -i ips-db-1 psql -U ips_user -d ips_db -f - \
--       < add_patient_state_facts.sql

CREATE TABLE IF NOT EXISTS patient_state_facts (
    guid            UUID PRIMARY KEY,
    patient_guid    UUID NOT NULL
                      REFERENCES patient_index(guid) ON DELETE CASCADE,
    fact_type       VARCHAR(64) NOT NULL,
    -- JSONB because several of these are structured: an address line is a
    -- list, a contact is a name plus a relationship plus a telecom. A text
    -- column would force every consumer to parse.
    value           JSONB NOT NULL,
    valid_from      TIMESTAMPTZ,
    valid_to        TIMESTAMPTZ,
    recorded_at     TIMESTAMPTZ NOT NULL,
    recorded_until  TIMESTAMPTZ,
    -- Provenance, so the projection never has to be trusted on its own.
    source_table    VARCHAR(64) NOT NULL,
    source_guid     UUID,
    source_version  INTEGER
);

-- The as-at read filters validity and record intervals together. Lower bounds
-- are indexed; upper bounds are usually NULL (still true / still current),
-- which an index cannot help with and does not need to.
CREATE INDEX IF NOT EXISTS ix_psf_patient_type
    ON patient_state_facts (patient_guid, fact_type);
CREATE INDEX IF NOT EXISTS ix_psf_valid_from
    ON patient_state_facts (patient_guid, valid_from);
CREATE INDEX IF NOT EXISTS ix_psf_recorded_at
    ON patient_state_facts (patient_guid, recorded_at);

-- NO unique constraint on (patient_guid, fact_type), deliberately. The
-- cardinality is 1:N per patient and 1:1 only per
-- (patient, fact_type, validity period): a patient has several addresses,
-- several next-of-kin, and a history of each. The original requirement said
-- "1:1 on the patient card" and the operator corrected it to 1:N, which is
-- the correction this absence encodes.
