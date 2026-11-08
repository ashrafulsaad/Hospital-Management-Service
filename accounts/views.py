from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from .serializers import Admin2FASerializer, LoginSerializer, RegisterSerializer


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    throttle_scope = "register"


class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer
    throttle_scope = "login"


class Admin2FAView(generics.GenericAPIView):
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


class MeView(APIView):
    def get(self, request):
        u = request.user
        return Response({"id": u.id, "email": u.email, "role": u.role})


class RolePingView(APIView):
    """Temporary: proves role permissions. Delete in a later chunk."""

    role_permission = None

    def get_permissions(self):
        return [self.role_permission()]

    def get(self, request):
        return Response({"ok": True, "role": request.user.role})
