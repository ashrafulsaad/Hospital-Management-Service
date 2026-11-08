from rest_framework import serializers

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = (
            "id", "actor", "actor_role", "action", "resource_type",
            "resource_id", "patient", "ip", "metadata", "created_at",
        )
        read_only_fields = fields
