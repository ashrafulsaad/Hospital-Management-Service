from django.db import transaction
from rest_framework import generics
from rest_framework.response import Response

from accounts.permissions import IsPatient
from audit.models import AuditLog
from audit.services import log_action

from .models import PatientProfile
from .serializers import PatientProfileSerializer


class MyProfileView(generics.RetrieveUpdateAPIView):
    """The logged-in patient's own profile. No id in the URL, by design."""

    serializer_class = PatientProfileSerializer
    permission_classes = [IsPatient]
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        profile, _ = PatientProfile.objects.get_or_create(user=self.request.user)
        return profile

    def retrieve(self, request, *args, **kwargs):
        profile = self.get_object()
        log_action(
            request, AuditLog.Action.PROFILE_VIEW, "PatientProfile",
            profile.pk, patient=request.user,
        )
        return Response(self.get_serializer(profile).data)

    def perform_update(self, serializer):
        with transaction.atomic():  # change + log succeed or fail together
            profile = serializer.save()
            log_action(
                self.request, AuditLog.Action.PROFILE_UPDATE, "PatientProfile",
                profile.pk, patient=self.request.user,
                fields=serializer.validated_data.keys(),
            )
