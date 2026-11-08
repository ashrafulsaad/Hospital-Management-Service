import re
from pathlib import Path

from django.utils import timezone
from rest_framework import serializers

from .models import (
    ConsentGrant,
    DoctorProfile,
    Hospital,
    MedicalRecord,
    MedicalRecordVersion,
    PatientDocument,
    Review,
    ReviewReport,
    Visit,
)

SEARCH_TEXT_RE = re.compile(r"^[\w\s.,'’-]+$", re.UNICODE)
BLOCKED_REVIEW_TERMS = {"asshole", "bitch", "fuck", "shit"}
MAX_DOCUMENT_SIZE = 10 * 1024 * 1024
DOCUMENT_SIGNATURES = {
    ".pdf": (b"%PDF-", "application/pdf"),
    ".png": (b"\x89PNG\r\n\x1a\n", "image/png"),
    ".jpg": (b"\xff\xd8\xff", "image/jpeg"),
    ".jpeg": (b"\xff\xd8\xff", "image/jpeg"),
}


class HospitalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Hospital
        fields = ("id", "name", "city", "specialty", "address")


class HospitalSearchSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, max_length=100)
    city = serializers.CharField(required=False, max_length=100)
    specialty = serializers.CharField(required=False, max_length=100)
    page = serializers.IntegerField(required=False, min_value=1, max_value=100000)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=50)

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {"query": f"Unknown search parameter(s): {', '.join(sorted(unknown))}."}
            )
        for field in ("name", "city", "specialty"):
            value = attrs.get(field)
            if value is not None and (
                not value.strip() or not SEARCH_TEXT_RE.fullmatch(value)
            ):
                raise serializers.ValidationError(
                    {field: "Use letters, numbers, spaces, and basic punctuation only."}
                )
        return attrs


class DoctorSearchSerializer(serializers.Serializer):
    specialty = serializers.CharField(required=False, max_length=100)
    hospital = serializers.IntegerField(required=False, min_value=1)
    min_rating = serializers.DecimalField(
        required=False,
        max_digits=2,
        decimal_places=1,
        min_value=0,
        max_value=5,
    )
    page = serializers.IntegerField(required=False, min_value=1, max_value=100000)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=50)

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {"query": f"Unknown search parameter(s): {', '.join(sorted(unknown))}."}
            )
        specialty = attrs.get("specialty")
        if specialty is not None and (
            not specialty.strip() or not SEARCH_TEXT_RE.fullmatch(specialty)
        ):
            raise serializers.ValidationError({"specialty": "Enter a valid specialty."})
        return attrs


class DoctorDirectorySerializer(serializers.ModelSerializer):
    hospital_name = serializers.CharField(source="hospital.name", read_only=True, default=None)
    rating = serializers.DecimalField(
        max_digits=3,
        decimal_places=2,
        read_only=True,
        allow_null=True,
    )
    review_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = DoctorProfile
        fields = ("id", "full_name", "specialty", "biography", "hospital_name", "rating", "review_count")


class DoctorApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = DoctorProfile
        fields = ("full_name", "specialty", "biography", "license_number", "hospital")
        extra_kwargs = {
            "license_number": {"write_only": True},
            "biography": {"required": False},
            "hospital": {"required": False, "allow_null": True},
        }

    def validate(self, attrs):
        if DoctorProfile.objects.filter(user=self.context["request"].user).exists():
            raise serializers.ValidationError("A doctor application already exists.")
        return attrs

    def create(self, validated_data):
        return DoctorProfile.objects.create(
            user=self.context["request"].user,
            **validated_data,
        )


class ConsentGrantSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConsentGrant
        fields = ("id", "purpose", "granted_at", "expires_at")
        read_only_fields = ("id", "granted_at")

    def validate(self, attrs):
        expires_at = attrs.get("expires_at")
        if expires_at and expires_at <= timezone.now():
            raise serializers.ValidationError(
                {"expires_at": "Consent expiration must be in the future."}
            )
        attrs["purpose"] = "treatment"
        return attrs


class VisitSerializer(serializers.ModelSerializer):
    hospital_name = serializers.CharField(source="hospital.name", read_only=True)
    doctor_name = serializers.CharField(source="doctor.doctor_profile.full_name", read_only=True)

    class Meta:
        model = Visit
        fields = ("id", "hospital_name", "doctor_name", "status", "started_at", "closed_at")


class MedicalRecordVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = MedicalRecordVersion
        fields = ("version", "content", "created_by", "created_at")
        read_only_fields = fields


class MedicalRecordSerializer(serializers.ModelSerializer):
    visit_id = serializers.IntegerField(read_only=True)
    versions = MedicalRecordVersionSerializer(many=True, read_only=True)

    class Meta:
        model = MedicalRecord
        fields = ("id", "visit_id", "versions", "created_at")
        read_only_fields = fields


class RecordContentSerializer(serializers.Serializer):
    content = serializers.CharField(min_length=1, max_length=20000, trim_whitespace=True)


class RecordCreateSerializer(RecordContentSerializer):
    visit = serializers.PrimaryKeyRelatedField(queryset=Visit.objects.select_related("patient"))


class PatientDocumentUploadSerializer(serializers.ModelSerializer):
    file = serializers.FileField(write_only=True)

    class Meta:
        model = PatientDocument
        fields = ("id", "visit", "file", "content_type", "size", "created_at")
        read_only_fields = ("id", "content_type", "size", "created_at")

    def validate_file(self, upload):
        if upload.size == 0:
            raise serializers.ValidationError("The uploaded file is empty.")
        if upload.size > MAX_DOCUMENT_SIZE:
            raise serializers.ValidationError("The file must not exceed 10 MiB.")
        if "/" in upload.name or "\\" in upload.name:
            raise serializers.ValidationError("File names must not contain path separators.")

        extension = Path(upload.name).suffix.lower()
        signature = DOCUMENT_SIGNATURES.get(extension)
        if signature is None:
            raise serializers.ValidationError("Only PDF, PNG, and JPEG documents are allowed.")

        header = upload.read(16)
        upload.seek(0)
        expected_signature, content_type = signature
        if not header.startswith(expected_signature):
            raise serializers.ValidationError(
                "The file contents do not match the file extension."
            )
        self._detected_content_type = content_type
        return upload

    def validate(self, attrs):
        attrs["content_type"] = self._detected_content_type
        return attrs


class PatientDocumentMetadataSerializer(serializers.ModelSerializer):
    class Meta:
        model = PatientDocument
        fields = ("id", "visit", "content_type", "size", "created_at")
        read_only_fields = fields


class ReviewCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ("visit", "rating", "text", "status")
        read_only_fields = ("status",)

    def validate_rating(self, value):
        if value < 1 or value > 5:
            raise serializers.ValidationError("Rating must be between 1 and 5.")
        return value

    def validate_text(self, value):
        normalized = value.strip()
        if len(normalized) < 10:
            raise serializers.ValidationError("Review text must be at least 10 characters.")
        words = set(re.findall(r"\b[\w']+\b", normalized.casefold()))
        if words & BLOCKED_REVIEW_TERMS:
            raise serializers.ValidationError("Review text contains abusive language.")
        return normalized

    def validate_visit(self, visit):
        user = self.context["request"].user
        if visit.patient_id != user.pk:
            raise serializers.ValidationError("You may only review your own visit.")
        if visit.status != Visit.Status.CLOSED:
            raise serializers.ValidationError("Only a closed visit can be reviewed.")
        if Review.objects.filter(visit=visit).exists():
            raise serializers.ValidationError("This visit already has a review.")
        return visit


class AdminVisitCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Visit
        fields = ("patient", "doctor", "hospital")

    def validate_patient(self, patient):
        from accounts.models import Role

        if patient.role != Role.PATIENT:
            raise serializers.ValidationError("Choose a patient account.")
        return patient

    def validate_doctor(self, doctor):
        from accounts.models import Role

        profile = getattr(doctor, "doctor_profile", None)
        if doctor.role != Role.DOCTOR or not profile or not profile.approved:
            raise serializers.ValidationError("Choose an approved doctor.")
        return doctor

    def create(self, validated_data):
        validated_data.update(status=Visit.Status.OPEN, started_at=timezone.now())
        return Visit.objects.create(**validated_data)


class ReviewQueueSerializer(serializers.ModelSerializer):
    patient_email = serializers.EmailField(source="visit.patient.email", read_only=True)
    doctor_name = serializers.CharField(
        source="visit.doctor.doctor_profile.full_name",
        read_only=True,
    )

    class Meta:
        model = Review
        fields = ("id", "patient_email", "doctor_name", "rating", "text", "status", "created_at")


class DoctorApplicationQueueSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    hospital_name = serializers.CharField(source="hospital.name", read_only=True, default=None)

    class Meta:
        model = DoctorProfile
        fields = (
            "id",
            "user_email",
            "full_name",
            "specialty",
            "biography",
            "license_number",
            "hospital_name",
            "created_at",
        )


class PublicReviewSerializer(serializers.ModelSerializer):
    doctor_name = serializers.CharField(source="visit.doctor.doctor_profile.full_name")
    hospital_name = serializers.CharField(source="visit.hospital.name")

    class Meta:
        model = Review
        fields = ("id", "doctor_name", "hospital_name", "rating", "text", "created_at")


class ReviewReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReviewReport
        fields = ("reason",)

    def validate_reason(self, value):
        value = value.strip()
        if len(value) < 5:
            raise serializers.ValidationError("Provide at least 5 characters.")
        return value


class ReviewModerationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ("status",)

    def validate_status(self, value):
        if value not in (Review.Status.APPROVED, Review.Status.REJECTED):
            raise serializers.ValidationError("Choose approved or rejected.")
        return value
