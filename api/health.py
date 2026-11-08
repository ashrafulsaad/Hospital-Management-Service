from django.db import DatabaseError, connection
from rest_framework import serializers
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


class HealthSerializer(serializers.Serializer):
    status = serializers.CharField()
    database = serializers.CharField()


class HealthView(GenericAPIView):
    serializer_class = HealthSerializer
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except DatabaseError:
            return Response(
                self.get_serializer(
                    {"status": "unhealthy", "database": "disconnected"},
                ).data,
                status=503,
            )
        return Response(
            self.get_serializer({"status": "ok", "database": "connected"}).data,
        )
