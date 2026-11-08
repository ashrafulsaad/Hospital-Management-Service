import pyotp
from django.contrib.auth.password_validation import validate_password
from django.core import signing
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .crypto import decrypt
from .models import Role, User

PENDING_SALT = "admin-2fa-pending"
PENDING_MAX_AGE = 300  # seconds


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ("id", "email", "password")

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)

    def validate(self, attrs):
        requested_role = self.initial_data.get("role")
        if requested_role not in (None, "", Role.PATIENT):
            raise serializers.ValidationError(
                {"role": "Doctor and admin roles cannot be assigned during registration."}
            )
        candidate = User(email=attrs["email"], role=Role.PATIENT)
        try:
            validate_password(attrs["password"], candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)})
        return attrs


class MeSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "email", "role")
        read_only_fields = fields


class RolePingSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    role = serializers.ChoiceField(choices=Role.choices)


class LoginSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = user.role
        return token

    def validate(self, attrs):
        data = super().validate(attrs)  # checks email+password, sets self.user
        if self.user.role != Role.ADMIN:
            return data
        if not self.user.totp_secret:
            raise PermissionDenied("Admin 2FA not set up. Run: manage.py setup_2fa <email>")
        pending = signing.dumps({"uid": self.user.pk}, salt=PENDING_SALT)
        return {"requires_2fa": True, "pending_token": pending}


class Admin2FASerializer(serializers.Serializer):
    pending_token = serializers.CharField()
    code = serializers.CharField(min_length=6, max_length=6)

    def validate(self, attrs):
        try:
            payload = signing.loads(
                attrs["pending_token"], salt=PENDING_SALT, max_age=PENDING_MAX_AGE
            )
        except signing.BadSignature:
            raise AuthenticationFailed("Invalid or expired pending token")

        user = User.objects.filter(
            pk=payload["uid"], role=Role.ADMIN, is_active=True
        ).first()
        if not user or not user.totp_secret:
            raise AuthenticationFailed("Invalid pending token")

        totp = pyotp.TOTP(decrypt(user.totp_secret))
        if not totp.verify(attrs["code"], valid_window=1):
            raise AuthenticationFailed("Invalid code")

        refresh = LoginSerializer.get_token(user)
        return {"refresh": str(refresh), "access": str(refresh.access_token)}