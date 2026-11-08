from django.urls import path

from .views import AuditLogListView, MyAuditLogListView

urlpatterns = [
    path("logs/", AuditLogListView.as_view()),
    path("my-logs/", MyAuditLogListView.as_view()),
]
