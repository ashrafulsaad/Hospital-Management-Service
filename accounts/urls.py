from django.urls import path

from .permissions import IsAdminRole, IsDoctor, IsPatient
from .views import (
    Admin2FAView,
    AuditedTokenBlacklistView,
    AuditedTokenRefreshView,
    LoginView,
    MeView,
    RegisterView,
    RolePingView,
)

urlpatterns = [
    path("register/", RegisterView.as_view()),
    path("login/", LoginView.as_view()),
    path("login/2fa/", Admin2FAView.as_view()),
    path("refresh/", AuditedTokenRefreshView.as_view()),
    path("logout/", AuditedTokenBlacklistView.as_view()),
    path("me/", MeView.as_view()),
    path("ping/patient/", RolePingView.as_view(role_permission=IsPatient)),
    path("ping/doctor/", RolePingView.as_view(role_permission=IsDoctor)),
    path("ping/admin/", RolePingView.as_view(role_permission=IsAdminRole)),
]