from django.shortcuts import render

# Create your views here.
from django.http import JsonResponse
from django.db import connection


def health_check(request):
    try:
        connection.ensure_connection()
        return JsonResponse({
            "status": "healthy",
            "database": "connected",
        })
    except Exception:
        return JsonResponse({
            "status": "unhealthy",
            "database": "disconnected",
        }, status=503)
