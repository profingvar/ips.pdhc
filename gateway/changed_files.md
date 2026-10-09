/Users/martiningvar/T7_sidewinder/ips.pdhc/gateway/app/services/euips_header.py
/Users/martiningvar/T7_sidewinder/ips.pdhc/gateway/app/services/ips_generator.py
/Users/martiningvar/T7_sidewinder/ips.pdhc/gateway/app/admin.py
/Users/martiningvar/T7_sidewinder/ips.pdhc/gateway/app/api/patient_routes.py
/Users/martiningvar/T7_sidewinder/ips.pdhc/gateway/tests/test_euips_header.py
/Users/martiningvar/T7_sidewinder/ips.pdhc/gateway/tests/test_euips_header_custodian.py
/Users/martiningvar/T7_sidewinder/ips.pdhc/gateway/app/services/euips_header_backfill.py
/Users/martiningvar/T7_sidewinder/ips.pdhc/gateway/app/__init__.py
/Users/martiningvar/T7_sidewinder/ips.pdhc/docs/technical.md
/Users/martiningvar/T7_sidewinder/ips.pdhc/docs/user_manual.md
/Users/martiningvar/T7_sidewinder/ips.pdhc/gateway/app/services/fhir_service.py
/Users/martiningvar/T7_sidewinder/ips.pdhc/gateway/app/models/clinic.py
/Users/martiningvar/T7_sidewinder/ips.pdhc/gateway/app/services/care_hierarchy_sync.py
/Users/martiningvar/T7_sidewinder/ips.pdhc/gateway/app/__init__.py
/Users/martiningvar/T7_sidewinder/ips.pdhc/gateway/migrations/add_clinic_care_organisation.sql
/Users/martiningvar/T7_sidewinder/ips.pdhc/gateway/tests/test_one_guid_and_care_levels.py
/Users/martiningvar/T7_sidewinder/ips.pdhc/gateway/app/services/mock_generator.py
/Users/martiningvar/T7_sidewinder/ips.pdhc/gateway/app/admin.py
/Users/martiningvar/T7_sidewinder/ips.pdhc/gateway/app/__init__.py
/Users/martiningvar/T7_sidewinder/ips.pdhc/gateway/app/services/guids.py
/Users/martiningvar/T7_sidewinder/ips.pdhc/gateway/app/api/clinic_routes.py
/Users/martiningvar/T7_sidewinder/ips.pdhc/gateway/app/api/patient_routes.py
/Users/martiningvar/T7_sidewinder/ips.pdhc/gateway/tests/test_clinic_guid_guard.py

## 2026-10-09 — #810 admin patient list: sort, archive, batch inspect
- /Users/martiningvar/T7_sidewinder/ips.pdhc/gateway/app/models/patient_index.py
- /Users/martiningvar/T7_sidewinder/ips.pdhc/gateway/app/admin.py
- /Users/martiningvar/T7_sidewinder/ips.pdhc/gateway/app/templates/patients.html
- /Users/martiningvar/T7_sidewinder/ips.pdhc/gateway/migrations/add_patient_archived_at.sql  (NEW, APPLIED to prod)
- /Users/martiningvar/T7_sidewinder/ips.pdhc/gateway/tests/test_admin_patient_archive_sort.py  (NEW)
- 2026-10-09 gateway/app/services/mock_generator.py — age range (#811): resolve_age_range, AgeRangeError, _birth_date_for_age
- 2026-10-09 gateway/app/admin.py — generate-mock takes age_min/age_max, refuses a bad range, redirects to the patient list
- 2026-10-09 gateway/app/templates/patients.html — Age from / Age to fields
- 2026-10-09 gateway/tests/test_mock_generator_age_range.py (NEW)
