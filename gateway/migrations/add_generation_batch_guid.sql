-- euIPS reform #791: a batch marker on patient_index.
--
-- ips.pdhc creates schema via db.create_all(), which adds missing TABLES only
-- and never alters an existing one, so a new column on patient_index needs an
-- explicit ALTER on prod. Idempotent (IF NOT EXISTS), same pattern as
-- add_reform_patient_flags.sql (#404).
--
-- Why this column and no table: generating "up to 100 patients for an assigned
-- care provider" has to be undoable, and there was no batch or run marker
-- here at all -- removing a batch meant recording its GUIDs by hand. Nothing
-- else about a batch needs storing: the timestamp is created_at and the
-- organisation comes from the clinic assignment, so a batch TABLE would only
-- duplicate derivable facts.
--
-- NULLABLE with no default, deliberately. The 150 existing rows stay NULL,
-- which correctly means "not from a tracked batch". Nine sibling services read
-- patient_index -- analysis-filter alone is read by cdr, cdr_6, analyse,
-- dashboard and rosetta -- so changes to this table are additive by rule.
--
-- Run on miserver:
--   docker exec -i ips-db-1 psql -U ips_user -d ips_db -f - \
--       < add_generation_batch_guid.sql

-- UUID, not VARCHAR(36). models/base.py::GUID is a TypeDecorator whose
-- postgresql impl is PG_UUID(as_uuid=True) -- `patient_index.guid` and
-- `fhir_resource_guid` are both `uuid` in the live database, confirmed against
-- information_schema. A varchar column here would take bound UUID objects via
-- psycopg2's adaptation and appear to work while disagreeing with the model,
-- which is the UUID-versus-string mismatch that hid #730's 500.
ALTER TABLE patient_index
    ADD COLUMN IF NOT EXISTS generation_batch_guid UUID;

-- No index yet. Add one only when a query filters on it and the row count
-- justifies it; an unused index is cost without benefit.
