-- EPS C3 (#889): a patient-granted next-of-kin privilege.
--
-- A SEPARATE table from patient_consents by requirement, not by taste:
-- a consent authorises a CAREGIVER under Lag (2022:913) § 5; this
-- authorises a PRIVATE INDIVIDUAL to act for the patient. Two legal
-- bases in one table makes "who may read?" unanswerable.
--
-- NOTE there is deliberately NO unique constraint over
-- (patient_guid, proxy_user_guid). #891's lesson: a plain UNIQUE would
-- make revocation terminal for that pair for ever, and the same two
-- people must be able to grant, revoke and grant again. "Only one
-- ACTIVE grant per pair" is enforced at the API layer, exactly as
-- patient_blocks and patient_consents already do it.
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS patient_proxy_grants (
    guid                    UUID PRIMARY KEY,
    patient_guid            UUID NOT NULL
                                REFERENCES patient_index(guid)
                                ON DELETE CASCADE,
    -- the relative's sso.pdhc users.guid (#890). Not FK'd: users live
    -- in sso, same convention as patient_consents.grantee_caregiver_guid.
    proxy_user_guid         UUID NOT NULL,
    proxy_label             VARCHAR(255),
    scope                   VARCHAR(32) NOT NULL DEFAULT 'read_as_patient',

    -- validity time: BOTH ends from the start (#889 / EPS C1), so a
    -- grant can begin in the future. expires_at alone cannot say
    -- "while I am in hospital next month".
    valid_from              TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_to                TIMESTAMPTZ,

    -- record time, separate from validity time (EPS C2).
    granted_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    granted_by_user_guid    UUID,
    granted_via             VARCHAR(32) NOT NULL DEFAULT 'portal',
    granted_note            TEXT,

    -- either party may revoke (EPS A3); only the patient may create.
    revoked_at              TIMESTAMPTZ,
    revoked_by_user_guid    UUID,
    revoked_by_role         VARCHAR(16),
    revoked_reason          TEXT
);

CREATE INDEX IF NOT EXISTS ix_patient_proxy_grants_patient
    ON patient_proxy_grants (patient_guid);
CREATE INDEX IF NOT EXISTS ix_patient_proxy_grants_proxy
    ON patient_proxy_grants (proxy_user_guid);
