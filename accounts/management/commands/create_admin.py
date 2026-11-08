from getpass import getpass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from accounts.models import Role, User


class Command(BaseCommand):
    help = "Create an administrator without storing credentials in source code."

    def add_arguments(self, parser):
        parser.add_argument("email")

    def handle(self, *args, **options):
        email = User.objects.normalize_email(options["email"])
        if User.objects.filter(email__iexact=email).exists():
            raise CommandError("A user with that email address already exists.")

        password = getpass("Password: ")
        confirmation = getpass("Confirm password: ")
        if not password or password != confirmation:
            raise CommandError("Passwords must be non-empty and match.")

        candidate = User(email=email, role=Role.ADMIN)
        try:
            validate_password(password, candidate)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc

        User.objects.create_superuser(
            email=email,
            password=password,
            role=Role.ADMIN,
        )
        self.stdout.write(self.style.SUCCESS(f"Administrator {email} created."))
