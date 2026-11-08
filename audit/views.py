from rest_framework import generics
from rest_framework.pagination import PageNumberPagination

from accounts.permissions import IsAdminRole, IsPatient

from .mixins import AuditProtectedRequestMixin
from .models import AuditLog
from .serializers import AuditLogSerializer


class AuditPagination(PageNumberPagination):
    page_size = 50
    max_page_size = 200
    page_size_query_param = "page_size"


class AuditLogListView(AuditProtectedRequestMixin, generics.ListAPIView):
    """Read-only. Admin only."""

    serializer_class = AuditLogSerializer
    permission_classes = [IsAdminRole]
    pagination_class = AuditPagination

    def get_queryset(self):
        qs = AuditLog.objects.all()
        params = self.request.query_params
        if params.get("action"):
            qs = qs.filter(action=params["action"])
        if params.get("patient", "").isdigit():
            qs = qs.filter(patient_id=int(params["patient"]))
        return qs


class MyAuditLogListView(AuditProtectedRequestMixin, generics.ListAPIView):
    serializer_class = AuditLogSerializer
    permission_classes = [IsPatient]
    pagination_class = AuditPagination

    def get_queryset(self):
        return AuditLog.objects.filter(patient=self.request.user)
