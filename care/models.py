import uuid
from pathlib import Path

from django.conf import settings
from django.db import models
from django.utils import timezone


class AppendOnlyError(Exception):
    pass


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise AppendOnlyError("This record is append-only")

    def delete(self):
        raise AppendOnlyError("This record is append-only")


class Hospital(models.Model):
    name = models.CharField(max_length=150)
    city = models.CharField(max_length=100)
    specialty = models.CharField(max_length=100)
    address = models.CharField(max_length=250, blank=True)

    class Meta:
        ordering = ["name", "id"]
        indexes = [
            models.Index(fields=["name", "city"]),
            models.Index(fields=["specialty", "city"]),
        ]

    def __str__(self):
        return self.name


class DoctorProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="doctor_profile",
    )
    hospital = models.ForeignKey(
        Hospital,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="doctors",
    )
    full_name = models.CharField(max_length=150)
    specialty = models.CharField(max_length=100)
    biography = models.TextField(blank=True, max_length=2000)
    license_number = models.CharField(max_length=100)
    approved = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["approved", "specialty"])]

    def __str__(self):
        return self.full_name


class ConsentGrant(models.Model):
    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="care_consent_grants",
    )
    purpose = models.CharField(max_length=60, default="treatment")
    granted_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)
    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        ordering = ["-granted_at", "-id"]
        indexes = [models.Index(fields=["patient", "purpose", "granted_at"])]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AppendOnlyError("Consent grants are append-only")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Consent grants are append-only")


class ConsentRevocation(models.Model):
    grant = models.OneToOneField(
        ConsentGrant,
        on_delete=models.PROTECT,
        related_name="revocation",
    )
    revoked_at = models.DateTimeField(default=timezone.now)
    objects = AppendOnlyQuerySet.as_manager()

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AppendOnlyError("Consent revocations are append-only")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Consent revocations are append-only")


class Visit(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"

    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="patient_visits",
    )
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="doctor_visits",
    )
    hospital = models.ForeignKey(
        Hospital,
        on_delete=models.PROTECT,
        related_name="visits",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.SCHEDULED,
        db_index=True,
    )
    started_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["patient", "status"]),
            models.Index(fields=["doctor", "status"]),
        ]

    def __str__(self):
        return f"Visit({self.pk})"


class MedicalRecordQuerySet(AppendOnlyQuerySet):
    pass


class MedicalRecord(models.Model):
    visit = models.OneToOneField(
        Visit,
        on_delete=models.PROTECT,
        related_name="medical_record",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    objects = MedicalRecordQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AppendOnlyError("Medical records are immutable")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Medical records are immutable")


class MedicalRecordVersionQuerySet(AppendOnlyQuerySet):
    pass


class MedicalRecordVersion(models.Model):
    record = models.ForeignKey(
        MedicalRecord,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    version = models.PositiveIntegerField()
    content = models.TextField(max_length=20000)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    objects = MedicalRecordVersionQuerySet.as_manager()

    class Meta:
        ordering = ["version"]
        constraints = [
            models.UniqueConstraint(
                fields=["record", "version"],
                name="unique_medical_record_version",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AppendOnlyError("Medical record versions are immutable")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Medical record versions are immutable")


def private_document_path(instance, filename):
    extension = Path(filename).suffix.lower()
    return f"private/{uuid.uuid4().hex}{extension}"


class PatientDocument(models.Model):
    visit = models.ForeignKey(
        Visit,
        on_delete=models.PROTECT,
        related_name="documents",
    )
    file = models.FileField(upload_to=private_document_path)
    content_type = models.CharField(max_length=40)
    size = models.PositiveIntegerField()
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class Review(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    visit = models.OneToOneField(
        Visit,
        on_delete=models.PROTECT,
        related_name="review",
    )
    rating = models.PositiveSmallIntegerField()
    text = models.TextField(max_length=2000)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="moderated_reviews",
    )
    moderated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["status", "created_at"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rating__gte=1, rating__lte=5),
                name="review_rating_between_1_and_5",
            ),
        ]


class ReviewReport(models.Model):
    review = models.ForeignKey(
        Review,
        on_delete=models.PROTECT,
        related_name="reports",
    )
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="review_reports",
    )
    reason = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["review", "reporter"],
                name="one_review_report_per_user",
            ),
        ]
