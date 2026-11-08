import pytest
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.test import APIClient

from accounts.models import Role
from audit.mixins import AuditProtectedRequestMixin
from audit.models import AppendOnlyError, AuditLog

pytestmark = pytest.mark.django_db

PROFILE = "/api/patients/me/"
LOGS = "/api/audit/logs/"


# ---------- every protected action creates an entry ----------
def test_profile_view_is_logged(client_for):
    user, client = client_for("a@x.com")
    client.get(PROFILE)
    log = AuditLog.objects.get()
    assert log.action == "profile_view"
    assert log.actor == user and log.patient == user
    assert log.actor_role == "patient"
    assert log.resource_type == "PatientProfile"
    assert log.ip


def test_profile_update_logs_field_names_not_values(client_for):
    _, client = client_for("a@x.com")
    client.patch(PROFILE, {"full_name": "Secret Name", "phone": "+91 90000 00000"}, format="json")
    log = AuditLog.objects.get(action="profile_update")
    assert log.metadata == {"fields": ["full_name", "phone"]}
    assert "Secret Name" not in str(log.metadata)
    assert "90000" not in str(log.metadata)


def test_rejected_update_writes_no_update_entry(client_for):
    _, client = client_for("a@x.com")
    assert client.patch(PROFILE, {"blood_group": "Z+"}, format="json").status_code == 400
    assert not AuditLog.objects.filter(action="profile_update").exists()


def test_register_is_logged_without_password():
    res = APIClient().post(
        "/api/auth/register/",
        {"email": "new@x.com", "password": "StrongPass!234", "role": "patient"},
        format="json",
    )
    assert res.status_code == 201
    log = AuditLog.objects.get(action="register")
    assert log.actor is None
    assert log.patient.email == "new@x.com"
    assert "StrongPass!234" not in str(log.metadata)


def test_blocked_request_writes_no_log(client_for):
    _, client = client_for("d@x.com", role=Role.DOCTOR)
    assert client.get(PROFILE).status_code == 403
    assert AuditLog.objects.count() == 0


# ---------- who may read the log ----------
def test_admin_can_list_logs(client_for):
    _, patient = client_for("a@x.com")
    patient.get(PROFILE)
    _, admin = client_for("root@x.com", role=Role.ADMIN)
    res = admin.get(LOGS)
    assert res.status_code == 200
    assert len(res.data["results"]) == 1


def test_patient_cannot_list_logs(client_for):
    _, client = client_for("a@x.com")
    assert client.get(LOGS).status_code == 403


def test_logs_without_token_is_401():
    assert APIClient().get(LOGS).status_code == 401


def test_successful_authenticated_protected_action_is_logged(client_for):
    user, client = client_for("me@x.com")
    response = client.get("/api/auth/me/")
    assert response.status_code == 200
    entry = AuditLog.objects.get(action=AuditLog.Action.API_ACCESS)
    assert entry.actor == user
    assert entry.resource_type == "API"
    assert entry.resource_id == "/api/auth/me/"


def test_patient_audit_feed_is_scoped_to_the_patient(client_for):
    patient_a, client_a = client_for("a@x.com")
    _, client_b = client_for("b@x.com")
    client_a.get(PROFILE)
    client_b.get(PROFILE)

    response = client_a.get("/api/audit/my-logs/")
    assert response.status_code == 200
    assert all(item["patient"] == patient_a.pk for item in response.data["results"])


def test_doctors_cannot_read_or_write_audit_logs(client_for):
    _, client = client_for("doctor@x.com", role=Role.DOCTOR)
    assert client.get(LOGS).status_code == 403
    assert client.get("/api/audit/my-logs/").status_code == 403
    assert client.post(LOGS, {}, format="json").status_code == 403


def _url_patterns(patterns, prefix=""):
    for pattern in patterns:
        if isinstance(pattern, URLPattern):
            yield prefix + str(pattern.pattern), pattern
        elif isinstance(pattern, URLResolver):
            yield from _url_patterns(
                pattern.url_patterns,
                prefix + str(pattern.pattern),
            )


def test_every_protected_api_view_uses_the_audit_mixin():
    for route, pattern in _url_patterns(get_resolver().url_patterns):
        view_class = getattr(pattern.callback, "cls", None)
        if view_class is None:
            continue
        if not route.startswith("api/"):
            continue
        if "rest_framework.permissions.AllowAny" in str(view_class.permission_classes):
            continue
        assert issubclass(view_class, AuditProtectedRequestMixin), view_class.__name__


# ---------- append-only ----------
@pytest.fixture
def one_log(client_for):
    _, client = client_for("a@x.com")
    client.get(PROFILE)
    return AuditLog.objects.get()


def test_existing_entry_cannot_be_saved_again(one_log):
    one_log.action = "register"
    with pytest.raises(AppendOnlyError):
        one_log.save()


def test_entry_cannot_be_deleted(one_log):
    with pytest.raises(AppendOnlyError):
        one_log.delete()


def test_bulk_update_blocked(one_log):
    with pytest.raises(AppendOnlyError):
        AuditLog.objects.all().update(action="register")


def test_bulk_delete_blocked(one_log):
    with pytest.raises(AppendOnlyError):
        AuditLog.objects.all().delete()
