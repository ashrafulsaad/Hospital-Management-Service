from rest_framework.permissions import BasePermission

from .models import Role


class HasRole(BasePermission):
    role = None

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated and user.role == self.role):
            return False
        if self.role == Role.DOCTOR:
            from care.services import is_approved_doctor

            return is_approved_doctor(user)
        return True


class IsPatient(HasRole):
    role = Role.PATIENT


class IsDoctor(HasRole):
    role = Role.DOCTOR


class IsAdminRole(HasRole):
    role = Role.ADMIN