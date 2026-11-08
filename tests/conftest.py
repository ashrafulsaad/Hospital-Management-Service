import pytest
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Role, User

PASSWORD = "StrongPass!234"


@pytest.fixture(autouse=True)
def clear_throttle_cache():
    cache.clear()  # throttle counters must not leak between tests


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def make_user(db):
    def _make(email="user@example.com", role=Role.PATIENT, password=PASSWORD):
        return User.objects.create_user(email=email, password=password, role=role)

    return _make


@pytest.fixture
def login(api):
    def _login(email, password=PASSWORD):
        return api.post("/api/auth/login/", {"email": email, "password": password})

    return _login


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
