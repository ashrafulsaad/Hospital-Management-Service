from rest_framework import generics

from accounts.permissions import IsPatient

from .models import PatientProfile
from .serializers import PatientProfileSerializer


class MyProfileView(generics.RetrieveUpdateAPIView):
    """The logged-in patient's own profile. No id in the URL, by design."""

    serializer_class = PatientProfileSerializer
    permission_classes = [IsPatient]
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        # Always the caller's own row. There is no way to ask for another.
        profile, _ = PatientProfile.objects.get_or_create(user=self.request.user)
        return profile
