"""Bring stored Device / DeviceUsage rows up to the R5 element names — #908.

#907 fixed what this service WRITES. Rows written before 2026-11-02 still
carry the pre-#907 shapes, and #896's export deep-copies `resource_json`,
so an export of an old row still ships an element R5 does not define.

Nothing in ips breaks on them: the section matcher keys on resource type,
`_CODE_BEARING_FIELDS` contains both `code` and `type`, and
`_is_patient_asserted` reads both `subject` and `patient` by design. The
defect surfaces the first time an external validator sees an export.

== Why this is Python and not SQL ==

#908 drafted the fix as JSONB statements. They are correct and they are
Postgres-only, which means the transformation could not be exercised by a
test suite that runs on SQLite — and the one that worried me most is a
RENAME, where a wrong operator silently drops a patient reference.

So the transformation is a pure function over the JSON, and the CLI
command walks rows and applies it. The same code runs on both databases,
every case has a test, and the command counts what it changed and can
refuse to proceed when the count disagrees with what it expected
(the lesson from #829: an in-place edit script that reports success
having matched nothing).

== The three changes, and the one that is not a deletion ==

1. `Device.patient` is DELETED. R5's Device element list has no
   `patient`; the association lives on `DeviceUsage.patient` or
   `DeviceAssociation`. The row's `FhirResource.patient_guid` is the
   linkage, and it is untouched here — this function never looks at it,
   so no migration can orphan a row.

2. `Device.code` is RENAMED to `type`. **Not deleted.** On an absent
   assertion that coding is the EXPLICITLY_ABSENT signal for a section,
   and deleting it would turn "no known devices" into "nothing recorded"
   — the exact silent downgrade `_CODE_BEARING_FIELDS`' own comment warns
   about. Renamed only when `type` is absent; where both exist, `type` is
   authoritative and `code` is dropped, because `type` is what #907
   writes.

3. `DeviceUsage.subject` is RENAMED to `patient`, and only when `patient`
   is absent. A row carrying both keeps the one it has: `patient` is what
   R5 requires and what #907 writes, so the stale `subject` must not
   overwrite it.

Idempotent by construction — a second run finds nothing to do, which is
asserted rather than assumed.
"""

from __future__ import annotations

#: Elements R5 does not define on these types, and what to do with each.
#: Kept as data so the set is readable at a glance and testable directly.
DEVICE_DROP = ("patient",)
DEVICE_RENAME = (("code", "type"),)
DEVICEUSAGE_RENAME = (("subject", "patient"),)

HANDLED_TYPES = ("Device", "DeviceUsage")


def migrate_resource_json(resource_type: str, resource_json: dict | None):
    """Return ``(new_json, changes)`` for one stored resource.

    ``changes`` is a list of short strings naming what happened, e.g.
    ``["drop:patient", "rename:code->type"]``. Empty means nothing to do,
    and in that case ``new_json`` is the SAME object, so a caller can test
    identity to avoid a pointless write.

    Never raises on odd input: a non-dict or an unhandled type is returned
    untouched. A migration that throws halfway through a table is worse
    than one that skips a row it does not understand.
    """
    if resource_type not in HANDLED_TYPES:
        return resource_json, []
    if not isinstance(resource_json, dict):
        return resource_json, []

    drops = DEVICE_DROP if resource_type == "Device" else ()
    renames = (DEVICE_RENAME if resource_type == "Device"
               else DEVICEUSAGE_RENAME)

    changes: list[str] = []
    out = dict(resource_json)

    for field in drops:
        if field in out:
            del out[field]
            changes.append(f"drop:{field}")

    for old, new in renames:
        if old not in out:
            continue
        if new in out:
            # Both present. The R5 name wins; the stale one goes. Never the
            # other way round -- overwriting a valid `patient` from a stale
            # `subject` is how a rename loses data.
            del out[old]
            changes.append(f"drop-stale:{old}")
        else:
            out[new] = out.pop(old)
            changes.append(f"rename:{old}->{new}")

    if not changes:
        return resource_json, []
    return out, changes


def plan(rows) -> dict:
    """What a run WOULD do, without doing it.

    ``rows`` is any iterable of objects with ``resource_type`` and
    ``resource_json``. Returns counts per change, the number of rows
    affected, and the total examined — so a dry run and a real run can be
    compared, which is what makes the real run's assertion meaningful
    rather than decorative.
    """
    per_change: dict[str, int] = {}
    affected = 0
    examined = 0
    for r in rows:
        examined += 1
        _new, changes = migrate_resource_json(r.resource_type,
                                              r.resource_json)
        if changes:
            affected += 1
            for c in changes:
                per_change[c] = per_change.get(c, 0) + 1
    return {"examined": examined, "affected": affected,
            "changes": per_change}
