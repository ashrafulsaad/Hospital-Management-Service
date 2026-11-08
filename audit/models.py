from django.conf import settings
from django.db import models


class AppendOnlyError(Exception):
    pass


class AuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise AppendOnlyError("Audit log is append-only")

    def delete(self):
        raise AppendOnlyError("Audit log is append-only")


class AuditLog(models.Model):
    class Action(models.TextChoices):
        REGISTER = "register", "Register"
        PROFILE_VIEW = "profile_view", "Profile view"
        PROFILE_UPDATE = "profile_update", "Profile update"
        API_ACCESS = "api_access", "API access"
        CONSENT_GRANTED = "consent_granted", "Consent granted"
        CONSENT_REVOKED = "consent_revoked", "Consent revoked"
        DOCTOR_APPROVED = "doctor_approved", "Doctor approved"
        RECORD_CREATED = "record_created", "Medical record created"
        RECORD_CORRECTED = "record_corrected", "Medical record corrected"
        DOCUMENT_UPLOADED = "document_uploaded", "Document uploaded"
        DOCUMENT_DOWNLOADED = "document_downloaded", "Document downloaded"
        REVIEW_CREATED = "review_created", "Review created"
        REVIEW_REPORTED = "review_reported", "Review reported"
        REVIEW_MODERATED = "review_moderated", "Review moderated"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    actor_role = models.CharField(max_length=10, blank=True)
    action = models.CharField(max_length=30, choices=Action.choices)
    resource_type = models.CharField(max_length=50)
    resource_id = models.CharField(max_length=64)
    patient = models.ForeignKey(  # whose record was touched
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    ip = models.GenericIPAddressField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)  # field NAMES only
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = AuditQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["patient", "-created_at"])]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AppendOnlyError("Audit log is append-only")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Audit log is append-only")
