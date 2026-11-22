-- #1049 (patient app v2): record HOW a patient-clinic assignment came about.
--
-- A patient may now register themselves in the patient app and choose a care
-- unit (POST /api/v1/patients/self-register). That assignment is real -- the
-- patient is listed at the unit, so sso can link the account and gateway can
-- accept the patient's card for that unit -- but nobody at the unit has seen
-- the patient yet. The unit must be able to tell such a row from one its own
-- staff made, so the row says so.
--
-- ips.pdhc creates schema via db.create_all(), which adds missing TABLES only
-- and never alters an existing one, so a new column needs an explicit ALTER on
-- prod. Idempotent, same pattern as add_assignment_ended_at.sql (#891).
--
-- NULLABLE with no default: every existing row stays NULL = "not stated", and
-- every existing writer keeps writing NULL. Values: 'self-registered'.
-- Eleven sibling services read this table set, so changes here are additive.
--
-- Run on miserver (operator):
--   docker exec -i ips-db-1 psql -U ips_user -d ips_db -f - \
--       < add_assignment_origin.sql

ALTER TABLE patient_clinic_assignments
    ADD COLUMN IF NOT EXISTS origin VARCHAR(32);
