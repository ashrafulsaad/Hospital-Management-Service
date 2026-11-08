from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from accounts.models import Role

from .models import (
    ConsentGrant,
    ConsentRevocation,
    DoctorProfile,
    MedicalRecord,
    MedicalRecordVersion,
    Visit,
)

CONSENT_PURPOSE_TREATMENT = "treatment"


def is_approved_doctor(user):
    return bool(
        user
        and user.is_authenticated
        and user.role == Role.DOCTOR
        and DoctorProfile.objects.filter(user=user, approved=True).exists()
    )


def has_active_consent(patient, purpose=CONSENT_PURPOSE_TREATMENT, at=None):
    moment = at or timezone.now()
    grants = ConsentGrant.objects.filter(
        patient=patient,
        purpose=purpose,
        granted_at__lte=moment,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=moment))
    return not ConsentRevocation.objects.filter(
        grant__in=grants,
        revoked_at__lte=moment,
    ).exists() and grants.exists()


def require_treatment_consent(patient):
    if not has_active_consent(patient):
        raise PermissionDenied("Active patient consent is required.")


def require_doctor_visit_access(doctor, visit):
    if not is_approved_doctor(doctor):
        raise PermissionDenied("An approved doctor account is required.")
    if visit.doctor_id != doctor.pk:
        raise PermissionDenied("This visit is not assigned to you.")
    require_treatment_consent(visit.patient)


@transaction.atomic
def create_record(visit, doctor, content):
    require_doctor_visit_access(doctor, visit)
    if visit.status == Visit.Status.CLOSED:
        raise ValidationError("A closed visit cannot receive a new record.")
    record = MedicalRecord.objects.create(visit=visit)
    version = MedicalRecordVersion.objects.create(
        record=record,
        version=1,
        content=content,
        created_by=doctor,
    )
    return record, version


@transaction.atomic
def correct_record(record_id, doctor, content):
    record = MedicalRecord.objects.select_for_update().select_related("visit").get(pk=record_id)
    require_doctor_visit_access(doctor, record.visit)
    latest = record.versions.aggregate(version=Max("version"))["version"]
    version = MedicalRecordVersion.objects.create(
        record=record,
        version=(latest or 0) + 1,
        content=content,
        created_by=doctor,
    )
    return version


def patient_can_access_visit(user, visit):
    if user.role == Role.PATIENT:
        return visit.patient_id == user.pk
    return bool(
        is_approved_doctor(user)
        and visit.doctor_id == user.pk
        and has_active_consent(visit.patient)
    )
