from rest_framework.permissions import BasePermission

from .models import Role


class HasRole(BasePermission):
    role = None

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.role == self.role)


class IsPatient(HasRole):
    role = Role.PATIENT


class IsDoctor(HasRole):
    role = Role.DOCTOR


class IsAdminRole(HasRole):
    role = Role.ADMIN