-- Access-model reform D1 (#404): patient opt-out flags on patient_index.
--
-- ips.pdhc creates schema via db.create_all() (adds missing tables only, never
-- alters existing ones), so these NEW COLUMNS on the existing patient_index
-- table need an explicit ALTER on prod. Idempotent (IF NOT EXISTS).
--
-- Only the two consents with NO pre-existing model are added here. The other
-- two v3-spec consents are already modelled richer and are NOT duplicated:
--   allow_sharing_in_care   -> existing patient_consents (per-caregiver, #198)
--   primary_care_unit_guids -> existing patient_clinic_assignments
--
-- Run on miserver:
--   docker exec ips-db-1 psql -U ips_user -d ips_db -f - < add_reform_patient_flags.sql
-- or paste the statements.

ALTER TABLE patient_index
    ADD COLUMN IF NOT EXISTS ehds_opt_out BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE patient_index
    ADD COLUMN IF NOT EXISTS quality_registry_opt_out BOOLEAN NOT NULL DEFAULT FALSE;

-- JSONB list of ResearchProject GUIDs the patient consented to (registry in
-- sso.pdhc, S4). Nullable = "no research consents recorded".
ALTER TABLE patient_index
    ADD COLUMN IF NOT EXISTS consented_research_projects JSONB;
