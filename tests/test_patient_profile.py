import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Role
from patients.models import PatientProfile

pytestmark = pytest.mark.django_db

URL = "/api/patients/me/"
EXPECTED_FIELDS = {
    "email",
    "full_name",
    "date_of_birth",
    "gender",
    "phone",
    "blood_group",
    "address",
    "emergency_contact_name",
    "emergency_contact_phone",
    "updated_at",
}


@pytest.fixture
def client_for(make_user):
    """Returns (user, client already logged in as that user)."""

    def _make(email, role=Role.PATIENT):
        user = make_user(email=email, role=role)
        client = APIClient()
        token = RefreshToken.for_user(user).access_token
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return user, client

    return _make


# ---------- creation ----------
def test_profile_created_on_patient_registration():
    from accounts.models import User

    res = APIClient().post(
        "/api/auth/register/",
        {"email": "new@x.com", "password": "StrongPass!234", "role": "patient"},
        format="json",
    )
    assert res.status_code == 201
    assert PatientProfile.objects.filter(user=User.objects.get(email="new@x.com")).exists()


def test_doctor_registration_creates_no_patient_profile(make_user):
    doctor = make_user(email="d@x.com", role=Role.DOCTOR)
    assert not PatientProfile.objects.filter(user=doctor).exists()


def test_missing_profile_is_created_on_first_get(client_for):
    user, client = client_for("old@x.com")
    PatientProfile.objects.filter(user=user).delete()
    assert client.get(URL).status_code == 200
    assert PatientProfile.objects.filter(user=user).exists()


# ---------- view and update ----------
def test_patient_reads_own_profile_with_only_safe_fields(client_for):
    _, client = client_for("a@x.com")
    res = client.get(URL)
    assert res.status_code == 200
    assert res.data["email"] == "a@x.com"
    assert set(res.data.keys()) == EXPECTED_FIELDS


def test_patient_updates_own_profile(client_for):
    user, client = client_for("a@x.com")
    res = client.patch(
        URL,
        {"full_name": "Test Patient", "blood_group": "O+", "phone": "+91 90000 00000"},
        format="json",
    )
    assert res.status_code == 200
    profile = PatientProfile.objects.get(user=user)
    assert profile.full_name == "Test Patient"
    assert profile.blood_group == "O+"


def test_put_not_allowed(client_for):
    _, client = client_for("a@x.com")
    assert client.put(URL, {}, format="json").status_code == 405


# ---------- ownership (IDOR) ----------
def test_patient_a_reads_own_data_not_patient_b(client_for):
    _, client_a = client_for("a@x.com")
    _, client_b = client_for("b@x.com")
    client_b.patch(URL, {"full_name": "Bee Synthetic"}, format="json")
    res = client_a.get(URL)
    assert res.data["email"] == "a@x.com"
    assert res.data["full_name"] != "Bee Synthetic"


def test_patient_a_edit_never_changes_patient_b(client_for):
    a, client_a = client_for("a@x.com")
    b, client_b = client_for("b@x.com")
    client_b.patch(URL, {"full_name": "Bee Synthetic"}, format="json")
    res = client_a.patch(URL, {"full_name": "Aye Synthetic"}, format="json")
    assert res.status_code == 200
    assert PatientProfile.objects.get(user=a).full_name == "Aye Synthetic"
    assert PatientProfile.objects.get(user=b).full_name == "Bee Synthetic"


def test_mass_assignment_of_email_and_user_is_ignored(client_for):
    a, client_a = client_for("a@x.com")
    b, _ = client_for("b@x.com")
    res = client_a.patch(
        URL,
        {"email": "hacker@x.com", "user": b.id, "id": 999, "full_name": "Aye"},
        format="json",
    )
    assert res.status_code == 200
    a.refresh_from_db()
    assert a.email == "a@x.com"
    assert PatientProfile.objects.get(user=a).full_name == "Aye"
    assert PatientProfile.objects.get(user=b).full_name == ""


# ---------- who may call ----------
def test_no_token_is_401():
    assert APIClient().get(URL).status_code == 401


def test_doctor_is_403(client_for):
    _, client = client_for("d@x.com", role=Role.DOCTOR)
    assert client.get(URL).status_code == 403


def test_admin_is_403(client_for):
    _, client = client_for("root@x.com", role=Role.ADMIN)
    assert client.get(URL).status_code == 403


# ---------- validation ----------
def test_future_birth_date_rejected(client_for):
    _, client = client_for("a@x.com")
    res = client.patch(URL, {"date_of_birth": "2999-01-01"}, format="json")
    assert res.status_code == 400


def test_bad_phone_rejected(client_for):
    _, client = client_for("a@x.com")
    res = client.patch(URL, {"phone": "abc"}, format="json")
    assert res.status_code == 400


def test_bad_blood_group_rejected(client_for):
    _, client = client_for("a@x.com")
    res = client.patch(URL, {"blood_group": "Z+"}, format="json")
    assert res.status_code == 400
