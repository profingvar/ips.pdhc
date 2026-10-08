-- 2026-10-08: ips must be able to answer BOTH care levels for a patient.
--
-- Operator principle: "a guid must have a 1:1 relation to a personnummer, a
-- caregiver and a careunit. If careunit is not given then the careunit should
-- be set to the caregiver."
--
-- ips could not express that. `clinics.organisation_guid` is the vårdenhet
-- (care unit); the vårdgivare above it lived only in sso, so every consumer
-- had to call sso to learn which level it was looking at — and a vårdenhet is
-- the spärrgräns, so that is a legal distinction, not a label.
--
-- Nullable on purpose: a clinic whose caregiver has not been synced yet reads
-- NULL, which `is_own_caregiver()` treats as "it is its own caregiver". That
-- is the operator's fallback, so an unsynced row is safe rather than wrong.
--
-- Populate with:  flask sync-care-hierarchy
ALTER TABLE clinics
    ADD COLUMN IF NOT EXISTS care_organisation_guid VARCHAR(255);

-- Consumers filter patients by caregiver as well as by unit.
CREATE INDEX IF NOT EXISTS ix_clinics_care_organisation_guid
    ON clinics (care_organisation_guid);
