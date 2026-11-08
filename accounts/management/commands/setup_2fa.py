import pyotp
from django.core.management.base import BaseCommand, CommandError

from accounts.crypto import encrypt
from accounts.models import Role, User


class Command(BaseCommand):
    help = "Create a TOTP secret for an admin and print the provisioning URI."

    def add_arguments(self, parser):
        parser.add_argument("email")

    def handle(self, *args, **options):
        user = User.objects.filter(email=options["email"], role=Role.ADMIN).first()
        if not user:
            raise CommandError("No admin with that email")
        secret = pyotp.random_base32()
        user.totp_secret = encrypt(secret)
        user.save(update_fields=["totp_secret"])
        uri = pyotp.TOTP(secret).provisioning_uri(
            name=user.email, issuer_name="Healthcare Platform"
        )
        self.stdout.write(uri)
