"""SQLAlchemy models for IPS Server."""

from app.models.base import db
from app.models.user import User
from app.models.clinic import Clinic, UserClinicAssignment
from app.models.api_key import ApiKey
from app.models.fhir_resource import FhirResource
from app.models.patient_index import PatientIndex, PatientClinicAssignment
from app.models.ips_card import IpsCard
from app.models.ips_snapshot import IpsSnapshot
from app.models.push_destination import PushDestination
from app.models.push_job import PushJob
from app.models.audit_log import AuditLog
from app.models.capability_statement import CapabilityStatement

__all__ = [
    "db",
    "User",
    "Clinic",
    "UserClinicAssignment",
    "ApiKey",
    "FhirResource",
    "PatientIndex",
    "PatientClinicAssignment",
    "IpsCard",
    "IpsSnapshot",
    "PushDestination",
    "PushJob",
    "AuditLog",
    "CapabilityStatement",
]
