import pyotp
import pytest
from freezegun import freeze_time

from accounts.crypto import encrypt
from accounts.models import Role, User
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def _auth(api, token):
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")


# ---------- register ----------
def test_register_success_hashes_password(api):
    res = api.post("/api/auth/register/", {"email": "a@x.com", "password": PASSWORD})
    assert res.status_code == 201
    assert "password" not in res.data
    user = User.objects.get(email="a@x.com")
    assert user.password != PASSWORD
    assert user.check_password(PASSWORD)
    assert user.role == Role.PATIENT


def test_register_admin_role_rejected(api):
    res = api.post(
        "/api/auth/register/",
        {"email": "evil@x.com", "password": PASSWORD, "role": "admin"},
    )
    assert res.status_code == 400
    assert not User.objects.filter(email="evil@x.com").exists()


def test_register_duplicate_email(api, make_user):
    make_user(email="dup@x.com")
    res = api.post("/api/auth/register/", {"email": "dup@x.com", "password": PASSWORD})
    assert res.status_code == 400


def test_register_weak_password(api):
    res = api.post("/api/auth/register/", {"email": "w@x.com", "password": "123"})
    assert res.status_code == 400


# ---------- login ----------
def test_login_success(login, make_user):
    make_user(email="p@x.com")
    res = login("p@x.com")
    assert res.status_code == 200
    assert "access" in res.data and "refresh" in res.data


def test_login_wrong_password(login, make_user):
    make_user(email="p@x.com")
    assert login("p@x.com", "WrongPass!999").status_code == 401


def test_login_unknown_user(login):
    assert login("ghost@x.com").status_code == 401


# ---------- tokens ----------
def test_me_without_token_is_401(api):
    assert api.get("/api/auth/me/").status_code == 401


def test_expired_access_token_is_401(api, login, make_user):
    make_user(email="p@x.com")
    token = login("p@x.com").data["access"]
    with freeze_time("2999-01-01"):
        res = api.get("/api/auth/me/", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert res.status_code == 401


def test_refresh_rotates_and_blacklists_old(api, login, make_user):
    make_user(email="p@x.com")
    old = login("p@x.com").data["refresh"]
    first = api.post("/api/auth/refresh/", {"refresh": old})
    assert first.status_code == 200
    assert first.data["refresh"] != old
    reuse = api.post("/api/auth/refresh/", {"refresh": old})
    assert reuse.status_code == 401


def test_logout_blacklists_refresh(api, login, make_user):
    make_user(email="p@x.com")
    refresh = login("p@x.com").data["refresh"]
    assert api.post("/api/auth/logout/", {"refresh": refresh}).status_code == 200
    assert api.post("/api/auth/refresh/", {"refresh": refresh}).status_code == 401


# ---------- roles ----------
def test_patient_on_doctor_endpoint_is_403(api, login, make_user):
    make_user(email="p@x.com", role=Role.PATIENT)
    _auth(api, login("p@x.com").data["access"])
    assert api.get("/api/auth/ping/doctor/").status_code == 403


def test_doctor_on_doctor_endpoint_is_200(api, login, make_user):
    make_user(email="d@x.com", role=Role.DOCTOR)
    _auth(api, login("d@x.com").data["access"])
    assert api.get("/api/auth/ping/doctor/").status_code == 200


def test_role_endpoint_without_token_is_401(api):
    assert api.get("/api/auth/ping/patient/").status_code == 401


# ---------- admin 2FA ----------
@pytest.fixture
def admin_with_totp(make_user):
    admin = make_user(email="root@x.com", role=Role.ADMIN)
    secret = pyotp.random_base32()
    admin.totp_secret = encrypt(secret)
    admin.save()
    return admin, secret


def test_admin_password_alone_gives_no_tokens(login, admin_with_totp):
    res = login("root@x.com")
    assert res.status_code == 200
    assert res.data["requires_2fa"] is True
    assert "access" not in res.data and "refresh" not in res.data


def test_admin_without_2fa_setup_is_403(login, make_user):
    make_user(email="root@x.com", role=Role.ADMIN)
    assert login("root@x.com").status_code == 403


def test_admin_wrong_code_rejected(api, login, admin_with_totp):
    pending = login("root@x.com").data["pending_token"]
    res = api.post("/api/auth/login/2fa/", {"pending_token": pending, "code": "000000"})
    assert res.status_code == 401


def test_admin_right_code_gives_tokens(api, login, admin_with_totp):
    _, secret = admin_with_totp
    pending = login("root@x.com").data["pending_token"]
    code = pyotp.TOTP(secret).now()
    res = api.post("/api/auth/login/2fa/", {"pending_token": pending, "code": code})
    assert res.status_code == 200
    _auth(api, res.data["access"])
    assert api.get("/api/auth/ping/admin/").status_code == 200


def test_pending_token_cannot_be_used_as_jwt(api, login, admin_with_totp):
    pending = login("root@x.com").data["pending_token"]
    _auth(api, pending)
    assert api.get("/api/auth/me/").status_code == 401


def test_patient_login_needs_no_code(login, make_user):
    make_user(email="p@x.com")
    assert "access" in login("p@x.com").data
