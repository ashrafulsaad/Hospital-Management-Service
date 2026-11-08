from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from freezegun import freeze_time
from rest_framework.test import APIClient

from accounts.models import Role
from audit.models import AuditLog
from care.models import (
    AppendOnlyError,
    ConsentGrant,
    ConsentRevocation,
    DoctorProfile,
    Hospital,
    MedicalRecordVersion,
    PatientDocument,
    Review,
    ReviewReport,
    Visit,
)
from care.services import correct_record, create_record, has_active_consent

pytestmark = pytest.mark.django_db


@pytest.fixture
def hospital():
    return Hospital.objects.create(
        name="Central Hospital",
        city="Dhaka",
        specialty="Cardiology",
        address="1 Main Road",
    )


@pytest.fixture
def care_context(make_user, hospital):
    patient = make_user("patient@care.test", role=Role.PATIENT)
    doctor = make_user("doctor@care.test", role=Role.DOCTOR)
    DoctorProfile.objects.create(
        user=doctor,
        hospital=hospital,
        full_name="Dr. Example",
        specialty="Cardiology",
        license_number="LIC-1001",
        approved=True,
    )
    ConsentGrant.objects.create(patient=patient)
    visit = Visit.objects.create(
        patient=patient,
        doctor=doctor,
        hospital=hospital,
        status=Visit.Status.OPEN,
        started_at=timezone.now(),
    )
    return patient, doctor, visit


def _client_for_user(user):
    from rest_framework_simplejwt.tokens import RefreshToken

    client = APIClient()
    token = RefreshToken.for_user(user).access_token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def test_consent_denies_by_default_and_expires(make_user):
    patient = make_user("no-consent@care.test")
    assert not has_active_consent(patient)

    with freeze_time("2026-01-01 10:00:00"):
        grant = ConsentGrant.objects.create(
            patient=patient,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        assert has_active_consent(patient)

    with freeze_time("2026-01-01 11:00:01"):
        assert not has_active_consent(patient)

    assert grant.patient_id == patient.pk


def test_consent_revocation_takes_effect_immediately(care_context):
    patient, _, _ = care_context
    grant = ConsentGrant.objects.get(patient=patient)
    assert has_active_consent(patient)
    ConsentRevocation.objects.create(grant=grant)
    assert not has_active_consent(patient)


def test_consent_api_grants_and_revokes(make_user):
    patient = make_user("consent-api@care.test")
    client = _client_for_user(patient)

    granted = client.post("/api/patients/consents/", {}, format="json")
    assert granted.status_code == 201
    grant_id = granted.data["id"]
    assert has_active_consent(patient)

    revoked = client.post(
        f"/api/patients/consents/{grant_id}/revoke/",
        {},
        format="json",
    )
    assert revoked.status_code == 204
    assert not has_active_consent(patient)
    assert AuditLog.objects.filter(action=AuditLog.Action.CONSENT_REVOKED).exists()


def test_doctor_application_stays_unapproved_until_admin_approval(
    make_user,
    hospital,
    client_for,
):
    patient = make_user("applicant@care.test")
    client = _client_for_user(patient)
    response = client.post(
        "/api/doctors/apply/",
        {
            "full_name": "Dr. Applicant",
            "specialty": "Cardiology",
            "license_number": "LIC-PENDING",
            "hospital": hospital.pk,
        },
        format="json",
    )
    assert response.status_code == 201
    assert "license_number" not in response.data
    patient.refresh_from_db()
    assert patient.role == Role.PATIENT
    assert client.get("/api/auth/ping/doctor/").status_code == 403

    profile = DoctorProfile.objects.get(user=patient)
    _, admin_client = client_for("admin@care.test", role=Role.ADMIN)
    approved = admin_client.post(
        f"/api/admin/doctors/{profile.pk}/approve/",
        {},
        format="json",
    )
    assert approved.status_code == 200
    patient.refresh_from_db()
    assert patient.role == Role.DOCTOR
    assert client.get("/api/auth/ping/doctor/").status_code == 200
    assert AuditLog.objects.filter(
        action=AuditLog.Action.DOCTOR_APPROVED,
        patient=patient,
    ).exists()


def test_unapproved_doctor_is_blocked_from_doctor_workspace(make_user):
    doctor = make_user("pending@care.test", role=Role.DOCTOR)
    client = _client_for_user(doctor)
    workspace_routes = (
        "/api/auth/ping/doctor/",
        "/api/care/visits/",
        "/api/care/records/",
        "/api/care/documents/",
        "/api/audit/my-logs/",
    )
    for route in workspace_routes:
        assert client.get(route).status_code == 403


def test_doctor_record_access_requires_active_consent(care_context):
    patient, doctor, visit = care_context
    record, _ = create_record(visit, doctor, "Confidential note")
    grant = ConsentGrant.objects.get(patient=patient)
    ConsentRevocation.objects.create(grant=grant)

    doctor_client = _client_for_user(doctor)
    assert doctor_client.get("/api/care/records/").data == []
    assert doctor_client.get(f"/api/care/records/{record.pk}/").status_code == 403
    assert doctor_client.post(
        f"/api/care/records/{record.pk}/correct/",
        {"content": "Attempted correction"},
        format="json",
    ).status_code == 403


def test_patient_reads_only_own_record(care_context, make_user, hospital):
    patient_a, doctor, visit_a = care_context
    record_a, _ = create_record(visit_a, doctor, "Record A")
    patient_b = make_user("patient-b@care.test")
    ConsentGrant.objects.create(patient=patient_b)
    visit_b = Visit.objects.create(
        patient=patient_b,
        doctor=doctor,
        hospital=hospital,
        status=Visit.Status.OPEN,
        started_at=timezone.now(),
    )
    record_b, _ = create_record(visit_b, doctor, "Record B")

    response = _client_for_user(patient_a).get("/api/care/records/")
    assert response.status_code == 200
    assert [item["id"] for item in response.data] == [record_a.pk]
    assert record_b.pk not in [item["id"] for item in response.data]


def test_record_correction_creates_version_and_preserves_original(care_context):
    _, doctor, visit = care_context
    record, version_one = create_record(visit, doctor, "Original clinical note")
    version_two = correct_record(record.pk, doctor, "Corrected clinical note")

    version_one.refresh_from_db()
    assert version_one.version == 1
    assert version_one.content == "Original clinical note"
    assert version_two.version == 2
    assert list(record.versions.values_list("version", flat=True)) == [1, 2]


def test_record_versions_are_immutable_and_have_no_delete_route(care_context):
    patient, doctor, visit = care_context
    record, version = create_record(visit, doctor, "Original clinical note")
    version.content = "Changed"
    with pytest.raises(AppendOnlyError):
        version.save()
    with pytest.raises(AppendOnlyError):
        MedicalRecordVersion.objects.filter(pk=version.pk).update(content="Changed")
    with pytest.raises(AppendOnlyError):
        version.delete()
    with pytest.raises(AppendOnlyError):
        record.delete()
    assert _client_for_user(patient).delete(
        f"/api/care/records/{record.pk}/",
    ).status_code == 405


def test_record_and_correction_endpoints_create_audit_entries(care_context):
    patient, doctor, visit = care_context
    doctor_client = _client_for_user(doctor)
    created = doctor_client.post(
        "/api/care/records/",
        {"visit": visit.pk, "content": "Initial note"},
        format="json",
    )
    assert created.status_code == 201
    corrected = doctor_client.post(
        f"/api/care/records/{created.data['id']}/correct/",
        {"content": "Corrected note"},
        format="json",
    )
    assert corrected.status_code == 201
    assert corrected.data["version"] == 2
    assert AuditLog.objects.filter(
        action=AuditLog.Action.RECORD_CREATED,
        patient=patient,
    ).exists()
    assert AuditLog.objects.filter(
        action=AuditLog.Action.RECORD_CORRECTED,
        patient=patient,
    ).exists()
    assert "Initial note" not in str(AuditLog.objects.values("metadata").all())


def test_document_upload_validates_type_size_and_randomizes_name(
    care_context,
    settings,
    tmp_path,
):
    patient, _, visit = care_context
    settings.MEDIA_ROOT = tmp_path
    client = _client_for_user(patient)

    bad_type = client.post(
        "/api/care/documents/",
        {
            "visit": visit.pk,
            "file": SimpleUploadedFile("note.txt", b"plain text"),
        },
        format="multipart",
    )
    assert bad_type.status_code == 400

    fake_extension = client.post(
        "/api/care/documents/",
        {
            "visit": visit.pk,
            "file": SimpleUploadedFile("fake.pdf", b"\x89PNG\r\n\x1a\nnot a pdf"),
        },
        format="multipart",
    )
    assert fake_extension.status_code == 400

    oversize = client.post(
        "/api/care/documents/",
        {
            "visit": visit.pk,
            "file": SimpleUploadedFile(
                "oversize.pdf",
                b"%PDF-" + b"x" * (10 * 1024 * 1024),
            ),
        },
        format="multipart",
    )
    assert oversize.status_code in (400, 413)

    traversal = client.post(
        "/api/care/documents/",
        {
            "visit": visit.pk,
            "file": SimpleUploadedFile("../../record.pdf", b"%PDF-1.7\n"),
        },
        format="multipart",
    )
    assert traversal.status_code == 201
    stored_traversal = PatientDocument.objects.get(pk=traversal.data["id"])
    assert ".." not in stored_traversal.file.name
    assert stored_traversal.file.name != "../../record.pdf"

    uploaded = client.post(
        "/api/care/documents/",
        {
            "visit": visit.pk,
            "file": SimpleUploadedFile("record.pdf", b"%PDF-1.7\nsynthetic"),
        },
        format="multipart",
    )
    assert uploaded.status_code == 201
    assert "file" not in uploaded.data
    document = PatientDocument.objects.get(pk=uploaded.data["id"])
    assert document.content_type == "application/pdf"
    assert document.file.name.startswith("private/")
    assert "record.pdf" not in document.file.name
    assert document.file.name.rsplit("/", 1)[-1] != "record.pdf"
    assert client.get(f"/media/{document.file.name}").status_code == 404


def test_document_download_requires_ownership_and_authentication(
    care_context,
    make_user,
    settings,
    tmp_path,
):
    patient, _, visit = care_context
    settings.MEDIA_ROOT = tmp_path
    document = PatientDocument.objects.create(
        visit=visit,
        file=SimpleUploadedFile("private.pdf", b"%PDF-1.7\n"),
        content_type="application/pdf",
        size=9,
        uploaded_by=patient,
    )

    assert APIClient().get(
        f"/api/care/documents/{document.pk}/download/",
    ).status_code == 401
    other_patient = make_user("other-patient@care.test")
    response = _client_for_user(other_patient).get(
        f"/api/care/documents/{document.pk}/download/",
    )
    assert response.status_code == 404
    own_response = _client_for_user(patient).get(
        f"/api/care/documents/{document.pk}/download/",
    )
    assert own_response.status_code == 200
    assert own_response["Content-Type"] == "application/pdf"
    assert AuditLog.objects.filter(
        action=AuditLog.Action.DOCUMENT_DOWNLOADED,
        patient=patient,
    ).exists()


def test_hospital_search_filters_are_bounded_and_paged(
    hospital,
    django_assert_num_queries,
):
    for index in range(5):
        Hospital.objects.create(
            name=f"Central Hospital {index}",
            city="Dhaka",
            specialty="Cardiology",
        )

    with django_assert_num_queries(2):
        response = APIClient().get(
            "/api/hospitals/?city=Dhaka&specialty=Cardiology&page_size=3",
        )
    assert response.status_code == 200
    assert response.data["count"] == 6
    assert len(response.data["results"]) == 3

    assert APIClient().get("/api/hospitals/?page_size=100").status_code == 400
    assert APIClient().get("/api/hospitals/?unknown=value").status_code == 400
    assert APIClient().get("/api/hospitals/?name=%3Cscript%3E").status_code == 400


def test_doctor_directory_only_returns_safe_approved_doctors(care_context):
    patient, doctor, visit = care_context
    Review.objects.create(
        visit=visit,
        rating=5,
        text="Helpful and professional care.",
        status=Review.Status.APPROVED,
    )
    response = APIClient().get("/api/doctors/?specialty=Cardiology&min_rating=4.5")
    assert response.status_code == 200
    result = response.data["results"][0]
    assert result["full_name"] == "Dr. Example"
    assert result["rating"] == "5.00"
    assert result["review_count"] == 1
    assert "license_number" not in result
    assert "user_email" not in result
    assert "patient_email" not in result

    unpublished = APIClient().get("/api/doctors/?specialty=Neurology")
    assert unpublished.data["count"] == 0
    assert doctor.role == Role.DOCTOR
    assert patient.role == Role.PATIENT


def test_admin_endpoints_deny_non_admins_and_log_admin_actions(
    make_user,
    client_for,
):
    patient = make_user("non-admin@care.test")
    patient_client = _client_for_user(patient)
    admin_routes = (
        "/api/admin/hospitals/",
        "/api/admin/doctors/",
        "/api/admin/visits/",
        "/api/admin/reviews/",
        "/api/admin/doctors/1/approve/",
        "/api/admin/reviews/1/moderate/",
    )
    for route in admin_routes:
        assert patient_client.get(route).status_code == 403

    _, admin_client = client_for("admin-write@care.test", role=Role.ADMIN)
    response = admin_client.post(
        "/api/admin/hospitals/",
        {
            "name": "North Hospital",
            "city": "Dhaka",
            "specialty": "Neurology",
            "address": "2 North Road",
        },
        format="json",
    )
    assert response.status_code == 201
    assert AuditLog.objects.filter(
        action=AuditLog.Action.API_ACCESS,
        actor__email="admin-write@care.test",
        resource_id="/api/admin/hospitals/",
    ).exists()


def test_review_requires_closed_visit_and_is_moderated(care_context, client_for):
    patient, _, visit = care_context
    patient_client = _client_for_user(patient)
    payload = {
        "visit": visit.pk,
        "rating": 5,
        "text": "The care was kind and very helpful.",
    }
    assert patient_client.post("/api/reviews/", payload, format="json").status_code == 400

    visit.status = Visit.Status.CLOSED
    visit.closed_at = timezone.now()
    visit.save(update_fields=("status", "closed_at"))
    created = patient_client.post("/api/reviews/", payload, format="json")
    assert created.status_code == 201
    assert created.data["status"] == Review.Status.PENDING
    assert patient_client.post("/api/reviews/", payload, format="json").status_code == 400
    assert patient_client.get("/api/reviews/").data["count"] == 0

    _, admin_client = client_for("admin-reviews@care.test", role=Role.ADMIN)
    queued = admin_client.get("/api/admin/reviews/")
    assert queued.status_code == 200
    moderated = admin_client.patch(
        f"/api/admin/reviews/{created.data['id']}/moderate/",
        {"status": "approved"},
        format="json",
    )
    assert moderated.status_code == 200
    public = APIClient().get("/api/reviews/")
    assert public.data["count"] == 1
    assert "patient_email" not in public.data["results"][0]


def test_review_rejects_abusive_text_and_report_is_rate_limited(
    care_context,
):
    patient, _, visit = care_context
    visit.status = Visit.Status.CLOSED
    visit.closed_at = timezone.now()
    visit.save(update_fields=("status", "closed_at"))
    client = _client_for_user(patient)
    response = client.post(
        "/api/reviews/",
        {"visit": visit.pk, "rating": 5, "text": "This was a shit experience."},
        format="json",
    )
    assert response.status_code == 400

    review = Review.objects.create(
        visit=visit,
        rating=4,
        text="A verified review for reporting.",
        status=Review.Status.APPROVED,
    )
    first = client.post(
        f"/api/reviews/{review.pk}/report/",
        {"reason": "The review is inaccurate."},
        format="json",
    )
    assert first.status_code == 201
    assert ReviewReport.objects.filter(review=review, reporter=patient).exists()
    for _ in range(4):
        client.post(
            f"/api/reviews/{review.pk}/report/",
            {"reason": "The review is inaccurate."},
            format="json",
        )
    limited = client.post(
        f"/api/reviews/{review.pk}/report/",
        {"reason": "The review is inaccurate."},
        format="json",
    )
    assert limited.status_code == 429
