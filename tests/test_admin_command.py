from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from accounts.models import Role, User

pytestmark = pytest.mark.django_db


def test_create_admin_prompts_for_a_password_and_creates_superuser(monkeypatch):
    answers = iter(("StrongAdmin!Pass123", "StrongAdmin!Pass123"))
    monkeypatch.setattr(
        "accounts.management.commands.create_admin.getpass",
        lambda prompt: next(answers),
    )
    output = StringIO()

    call_command("create_admin", "admin@example.com", stdout=output)

    admin = User.objects.get(email="admin@example.com")
    assert admin.role == Role.ADMIN
    assert admin.is_staff and admin.is_superuser
    assert admin.check_password("StrongAdmin!Pass123")
    assert "StrongAdmin!Pass123" not in output.getvalue()


def test_create_admin_rejects_mismatched_passwords(monkeypatch):
    answers = iter(("StrongAdmin!Pass123", "DifferentAdmin!Pass123"))
    monkeypatch.setattr(
        "accounts.management.commands.create_admin.getpass",
        lambda prompt: next(answers),
    )

    with pytest.raises(CommandError, match="must be non-empty and match"):
        call_command("create_admin", "admin@example.com")

    assert not User.objects.filter(email="admin@example.com").exists()
