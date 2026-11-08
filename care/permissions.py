from rest_framework.permissions import BasePermission

from accounts.models import Role

from .services import is_approved_doctor


class IsPatientOrApprovedDoctor(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and (
                user.role == Role.PATIENT
                or is_approved_doctor(user)
            )
        )


class IsApprovedDoctor(BasePermission):
    def has_permission(self, request, view):
        return is_approved_doctor(request.user)
