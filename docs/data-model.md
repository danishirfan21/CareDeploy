# Data model

Migrations are additive and ordered: `0001` (clinics), `0002` (published config versions),
`0003` (scheduling). Committed migrations are never edited.

## M1 - configuration

`clinics`, `operating_hours`, `appointment_types`, `scheduling_policies`, `agent_configs` hold the
editable draft. `config_versions` holds immutable JSONB snapshots (a trigger rejects UPDATE/DELETE).

M2 changes to `appointment_types` (migration 0003): `archived_at` column; unique
`(clinic_id, id)` for composite foreign keys; the old `(clinic_id, lower(name))` uniqueness became a
partial unique index over active rows only (`WHERE archived_at IS NULL`).

## M2 - scheduling

| Table | Notes |
| --- | --- |
| `patients` | Synthetic, clinic-scoped: name, DOB, phone, email, `verification_method`, failed-attempt counter, `locked_until`, `last_verified_at`. Unique `(clinic_id, id)`. |
| `patient_authorizations` | Hashed bearer token, `expires_at`, `revoked_at`; composite FK to patient. |
| `appointments` | Clinic, patient, `appointment_type_id`, frozen `type_name`/`duration_minutes`/`timezone`, UTC `start_at`/`end_at`, `status` (`scheduled/completed/cancelled`), `config_version`, `reschedule_count`, `row_version`, cancellation metadata, timestamps. Exclusion constraint `ex_appointments_no_overlap`; checks `end_at > start_at`, valid status, cancelled-fields consistency. Composite FKs to patients and appointment types. |
| `appointment_events` | Append-only audit (trigger blocks UPDATE/DELETE): event type, actor, operation id, config version, details. |
| `operations` | Idempotency ledger: unique `(clinic_id, idempotency_key)`, fingerprint, status, attempts, outcome JSONB, appointment, timestamps. |
| `operation_proposals` | Confirmation records: bound details hash, confirmation-token hash, status, expiry, executed operation. |

Every scheduling table carries `clinic_id`; links to parents use composite `(clinic_id, id)` foreign
keys, so cross-clinic references are rejected by PostgreSQL itself (tested by direct SQL).
`btree_gist` is required (created by migration 0003). Downgrading 0003 drops the scheduling tables
and deletes archived appointment types.
