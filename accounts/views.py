from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.state import token_backend
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import (
    TokenBlacklistView,
    TokenObtainPairView,
    TokenRefreshView,
)

from audit.mixins import AuditProtectedRequestMixin
from audit.models import AuditLog
from audit.services import log_action

from .models import Role, User
from .serializers import Admin2FASerializer, LoginSerializer, RegisterSerializer


class RegisterView(AuditProtectedRequestMixin, generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    throttle_scope = "register"

    def perform_create(self, serializer):
        user = serializer.save()
        log_action(
            self.request, AuditLog.Action.REGISTER, "User", user.pk,
            patient=user if user.role == Role.PATIENT else None,
        )


class LoginView(AuditProtectedRequestMixin, TokenObtainPairView):
    serializer_class = LoginSerializer
    throttle_scope = "login"


class AuditedTokenRefreshView(AuditProtectedRequestMixin, TokenRefreshView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        if response.status_code < 300 and not request.user.is_authenticated:
            refresh = response.data.get("refresh")
            if refresh:
                token = RefreshToken(refresh)
                user = User.objects.filter(
                    pk=token[api_settings.USER_ID_CLAIM],
                    is_active=True,
                ).first()
                if user:
                    log_action(
                        request,
                        AuditLog.Action.API_ACCESS,
                        "API",
                        request.path,
                        actor=user,
                    )
        return response


class AuditedTokenBlacklistView(AuditProtectedRequestMixin, TokenBlacklistView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        if response.status_code < 300 and not request.user.is_authenticated:
            payload = token_backend.decode(
                request.data["refresh"],
                verify=False,
            )
            user = User.objects.filter(
                pk=payload.get(api_settings.USER_ID_CLAIM),
                is_active=True,
            ).first()
            if user:
                log_action(
                    request,
                    AuditLog.Action.API_ACCESS,
                    "API",
                    request.path,
                    actor=user,
                )
        return response


class Admin2FAView(AuditProtectedRequestMixin, generics.GenericAPIView):
    serializer_class = Admin2FASerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "login"

    def get_authenticate_header(self, request):
        # makes DRF answer 401 (not 403) when the code is wrong
        return 'Bearer realm="api"'

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


class MeView(AuditProtectedRequestMixin, APIView):
    def get(self, request):
        u = request.user
        return Response({"id": u.id, "email": u.email, "role": u.role})


class RolePingView(AuditProtectedRequestMixin, APIView):
    """Temporary: proves role permissions. Delete in a later chunk."""

    role_permission = None

    def get_permissions(self):
        return [self.role_permission()]

    def get(self, request):
        return Response({"ok": True, "role": request.user.role})
