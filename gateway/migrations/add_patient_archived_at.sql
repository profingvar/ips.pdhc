-- #811: archive a patient out of the admin list without deleting it.
--
-- ips.pdhc creates schema via db.create_all(), which adds missing TABLES only
-- and never alters an existing one, so a new column on patient_index needs an
-- explicit ALTER on prod. Idempotent (IF NOT EXISTS), same pattern as
-- add_generation_batch_guid.sql (#791) and add_reform_patient_flags.sql (#404).
--
-- Why a NEW column and not the `is_active` bool that already exists:
-- `is_active` is FHIR `Patient.active`, and it is already load-bearing on a
-- CROSS-SERVICE endpoint -- app/api/clinic_routes.py filters
-- `PatientIndex.is_active.is_(True)` on GET /api/v1/clinics/<guid>/patients,
-- which is the roster sim.pdhc builds cohorts from. Reusing it would make
-- "archive" silently also mean "remove from every org-scoped roster and stop
-- receiving generated data" -- a far larger decision than hiding one row from
-- one admin table, and not what was asked for.
--
-- Why a timestamp and not a boolean: it answers both "archived?" and "when?"
-- for the same storage, and NULL is unambiguously "not archived". A bool would
-- need a second column to carry the date.
--
-- NULLABLE with no default. Every existing row stays NULL = not archived, so
-- the migration changes nothing about what anyone currently sees. Nine sibling
-- services read patient_index -- analysis-filter alone is read by cdr, cdr_6,
-- analyse, dashboard and rosetta -- so changes to this table are additive by
-- rule, and this one is.
--
-- Run on miserver:
--   docker exec -i ips-db-1 psql -U ips_user -d ips_db -f - \
--       < add_patient_archived_at.sql

-- TIMESTAMPTZ to match created_at/updated_at on this table, which are
-- DateTime(timezone=True) in the model. A naive `timestamp` here would compare
-- and sort incorrectly against them.
ALTER TABLE patient_index
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;

-- Partial index: the default admin list filters `archived_at IS NULL`, which
-- is almost every row, so an index on the whole column would not be used. This
-- one covers the "show me the archived ones" query instead, which is the
-- selective direction.
CREATE INDEX IF NOT EXISTS ix_patient_index_archived
    ON patient_index (archived_at)
    WHERE archived_at IS NOT NULL;
