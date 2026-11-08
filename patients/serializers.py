import re
from datetime import date

from rest_framework import serializers

from .models import PatientProfile

PHONE_RE = re.compile(r"^\+?[0-9 ()-]{7,20}$")


def _validate_phone(value):
    if value and not PHONE_RE.match(value):
        raise serializers.ValidationError("Enter a valid phone number.")
    return value


class PatientProfileSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = PatientProfile
        # Explicit whitelist. No id, no user, no role, no secrets.
        fields = (
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
        )
        read_only_fields = ("updated_at",)

    def validate_date_of_birth(self, value):
        if value and value > date.today():
            raise serializers.ValidationError("Date of birth cannot be in the future.")
        return value

    def validate_phone(self, value):
        return _validate_phone(value)

    def validate_emergency_contact_phone(self, value):
        return _validate_phone(value)
