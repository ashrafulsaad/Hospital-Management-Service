from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Avg, Count, Prefetch, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from accounts.models import Role, User
from accounts.permissions import IsAdminRole, IsPatient
from audit.mixins import AuditProtectedRequestMixin
from audit.models import AuditLog
from audit.services import log_action

from .models import (
    ConsentGrant,
    ConsentRevocation,
    DoctorProfile,
    Hospital,
    MedicalRecord,
    MedicalRecordVersion,
    PatientDocument,
    Review,
    ReviewReport,
    Visit,
)
from .permissions import IsApprovedDoctor, IsPatientOrApprovedDoctor
from .serializers import (
    AdminVisitCreateSerializer,
    ApprovalResultSerializer,
    ConsentGrantSerializer,
    DoctorApplicationQueueSerializer,
    DoctorApplicationSerializer,
    DoctorDirectorySerializer,
    DoctorSearchSerializer,
    EmptySerializer,
    HospitalSearchSerializer,
    HospitalSerializer,
    MedicalRecordSerializer,
    PatientDocumentMetadataSerializer,
    PatientDocumentUploadSerializer,
    PublicReviewSerializer,
    RecordContentSerializer,
    RecordCorrectionResultSerializer,
    RecordCreateSerializer,
    ReviewCreateSerializer,
    ReviewModerationResultSerializer,
    ReviewModerationSerializer,
    ReviewQueueSerializer,
    ReviewReportSerializer,
    VisitSerializer,
)
from .services import (
    CONSENT_PURPOSE_TREATMENT,
    correct_record,
    create_record,
    has_active_consent,
    is_approved_doctor,
    patient_can_access_visit,
    require_doctor_visit_access,
)


class DirectoryPagination(PageNumberPagination):
    page_size = 3
    page_size_query_param = "page_size"
    max_page_size = 50


class HospitalDirectoryView(AuditProtectedRequestMixin, generics.ListAPIView):
    serializer_class = HospitalSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    pagination_class = DirectoryPagination

    def get_queryset(self):
        params = HospitalSearchSerializer(data=self.request.query_params)
        params.is_valid(raise_exception=True)
        filters = params.validated_data
        queryset = Hospital.objects.all()
        for field in ("name", "city", "specialty"):
            if field in filters:
                queryset = queryset.filter(**{f"{field}__icontains": filters[field].strip()})
        return queryset.order_by("name", "id")


class DoctorDirectoryView(AuditProtectedRequestMixin, generics.ListAPIView):
    serializer_class = DoctorDirectorySerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    pagination_class = DirectoryPagination

    def get_queryset(self):
        params = DoctorSearchSerializer(data=self.request.query_params)
        params.is_valid(raise_exception=True)
        filters = params.validated_data
        approved_reviews = Q(
            user__doctor_visits__review__status=Review.Status.APPROVED,
        )
        queryset = DoctorProfile.objects.filter(approved=True).select_related(
            "hospital",
            "user",
        ).annotate(
            rating=Avg(
                "user__doctor_visits__review__rating",
                filter=approved_reviews,
            ),
            review_count=Count(
                "user__doctor_visits__review",
                filter=approved_reviews,
                distinct=True,
            ),
        )
        if "specialty" in filters:
            queryset = queryset.filter(
                specialty__icontains=filters["specialty"].strip(),
            )
        if "hospital" in filters:
            queryset = queryset.filter(hospital_id=filters["hospital"])
        if "min_rating" in filters:
            queryset = queryset.filter(rating__gte=filters["min_rating"])
        return queryset.order_by("full_name", "id")


class DoctorApplicationView(AuditProtectedRequestMixin, generics.CreateAPIView):
    serializer_class = DoctorApplicationSerializer
    permission_classes = [IsPatient]


class ConsentCollectionView(AuditProtectedRequestMixin, generics.ListCreateAPIView):
    serializer_class = ConsentGrantSerializer
    permission_classes = [IsPatient]

    def get_queryset(self):
        return ConsentGrant.objects.filter(patient=self.request.user)

    def perform_create(self, serializer):
        grant = serializer.save(
            patient=self.request.user,
            purpose=CONSENT_PURPOSE_TREATMENT,
        )
        log_action(
            self.request,
            AuditLog.Action.CONSENT_GRANTED,
            "ConsentGrant",
            grant.pk,
            patient=self.request.user,
        )


class ConsentRevokeView(AuditProtectedRequestMixin, generics.GenericAPIView):
    serializer_class = EmptySerializer
    permission_classes = [IsPatient]

    @transaction.atomic
    def post(self, request, pk):
        grant = get_object_or_404(
            ConsentGrant.objects.select_for_update(),
            pk=pk,
            patient=request.user,
            purpose=CONSENT_PURPOSE_TREATMENT,
        )
        if ConsentRevocation.objects.filter(grant=grant).exists():
            return Response(
                {"detail": "This consent has already been revoked."},
                status=status.HTTP_409_CONFLICT,
            )
        revocation = ConsentRevocation.objects.create(grant=grant)
        log_action(
            request,
            AuditLog.Action.CONSENT_REVOKED,
            "ConsentRevocation",
            revocation.pk,
            patient=request.user,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class VisitListView(AuditProtectedRequestMixin, generics.ListAPIView):
    serializer_class = VisitSerializer
    permission_classes = [IsPatientOrApprovedDoctor]

    def get_queryset(self):
        queryset = Visit.objects.select_related(
            "hospital",
            "doctor",
            "doctor__doctor_profile",
        )
        if self.request.user.role == Role.PATIENT:
            return queryset.filter(patient=self.request.user)

        patient_ids = set(
            queryset.filter(doctor=self.request.user)
            .values_list("patient_id", flat=True)
            .distinct()
        )
        permitted_ids = [
            patient_id
            for patient_id in patient_ids
            if has_active_consent(patient_id)
        ]
        return queryset.filter(doctor=self.request.user, patient_id__in=permitted_ids)


class VisitCloseView(AuditProtectedRequestMixin, generics.GenericAPIView):
    serializer_class = VisitSerializer
    permission_classes = [IsApprovedDoctor]

    @extend_schema(request=EmptySerializer, responses=VisitSerializer)
    @transaction.atomic
    def post(self, request, pk):
        visit = get_object_or_404(
            Visit.objects.select_for_update().select_related("patient"),
            pk=pk,
            doctor=request.user,
        )
        require_doctor_visit_access(request.user, visit)
        if visit.status != Visit.Status.OPEN:
            return Response(
                {"detail": "Only an open visit can be closed."},
                status=status.HTTP_409_CONFLICT,
            )
        visit.status = Visit.Status.CLOSED
        visit.closed_at = timezone.now()
        visit.save(update_fields=("status", "closed_at"))
        return Response(VisitSerializer(visit).data)


class MedicalRecordCollectionView(AuditProtectedRequestMixin, generics.GenericAPIView):
    serializer_class = MedicalRecordSerializer
    permission_classes = [IsPatientOrApprovedDoctor]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return RecordCreateSerializer
        return MedicalRecordSerializer

    @extend_schema(operation_id="care_records_list")
    def get(self, request):
        queryset = MedicalRecord.objects.select_related(
            "visit",
            "visit__doctor",
            "visit__hospital",
        ).prefetch_related(
            Prefetch(
                "versions",
                queryset=MedicalRecordVersion.objects.select_related("created_by"),
            )
        )
        if request.user.role == Role.PATIENT:
            queryset = queryset.filter(visit__patient=request.user)
        else:
            visits = Visit.objects.filter(doctor=request.user).values_list(
                "patient_id",
                flat=True,
            ).distinct()
            patient_ids = {
                patient_id
                for patient_id in visits
                if has_active_consent(patient_id)
            }
            queryset = queryset.filter(
                visit__doctor=request.user,
                visit__patient_id__in=patient_ids,
            )
        return Response(MedicalRecordSerializer(queryset, many=True).data)

    @extend_schema(operation_id="care_records_create")
    def post(self, request):
        if not is_approved_doctor(request.user):
            raise PermissionDenied("Only approved doctors can create medical records.")
        serializer = RecordCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record, _ = create_record(
            serializer.validated_data["visit"],
            request.user,
            serializer.validated_data["content"],
        )
        log_action(
            request,
            AuditLog.Action.RECORD_CREATED,
            "MedicalRecord",
            record.pk,
            patient=record.visit.patient,
            fields=("version",),
        )
        record = MedicalRecord.objects.prefetch_related("versions").get(pk=record.pk)
        return Response(
            MedicalRecordSerializer(record).data,
            status=status.HTTP_201_CREATED,
        )


class MedicalRecordDetailView(AuditProtectedRequestMixin, generics.GenericAPIView):
    serializer_class = MedicalRecordSerializer
    permission_classes = [IsPatientOrApprovedDoctor]

    @extend_schema(operation_id="care_records_retrieve")
    def get(self, request, pk):
        record = get_object_or_404(
            MedicalRecord.objects.select_related(
                "visit",
                "visit__patient",
                "visit__doctor",
                "visit__hospital",
            ).prefetch_related("versions"),
            pk=pk,
        )
        if request.user.role == Role.PATIENT:
            if record.visit.patient_id != request.user.pk:
                raise Http404
        else:
            require_doctor_visit_access(request.user, record.visit)
        log_action(
            request,
            AuditLog.Action.API_ACCESS,
            "MedicalRecord",
            record.pk,
            patient=record.visit.patient,
        )
        return Response(MedicalRecordSerializer(record).data)


class MedicalRecordCorrectionView(AuditProtectedRequestMixin, generics.GenericAPIView):
    serializer_class = RecordContentSerializer
    permission_classes = [IsApprovedDoctor]

    @extend_schema(
        request=RecordContentSerializer,
        responses=RecordCorrectionResultSerializer,
    )
    def post(self, request, pk):
        serializer = RecordContentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        version = correct_record(
            pk,
            request.user,
            serializer.validated_data["content"],
        )
        log_action(
            request,
            AuditLog.Action.RECORD_CORRECTED,
            "MedicalRecord",
            version.record_id,
            patient=version.record.visit.patient,
            fields=("version",),
        )
        return Response(
            RecordCorrectionResultSerializer(
                {
                "version": version.version,
                "content": version.content,
                "created_at": version.created_at,
                },
            ).data,
            status=status.HTTP_201_CREATED,
        )


class PatientDocumentCollectionView(
    AuditProtectedRequestMixin,
    generics.GenericAPIView,
):
    serializer_class = PatientDocumentMetadataSerializer
    permission_classes = [IsPatientOrApprovedDoctor]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return PatientDocumentUploadSerializer
        return PatientDocumentMetadataSerializer

    def get(self, request):
        queryset = PatientDocument.objects.select_related(
            "visit",
            "visit__patient",
        )
        if request.user.role == Role.PATIENT:
            queryset = queryset.filter(visit__patient=request.user)
        else:
            visits = Visit.objects.filter(doctor=request.user).values_list(
                "patient_id",
                flat=True,
            ).distinct()
            patient_ids = {
                patient_id
                for patient_id in visits
                if has_active_consent(patient_id)
            }
            queryset = queryset.filter(
                visit__doctor=request.user,
                visit__patient_id__in=patient_ids,
            )
        return Response(
            PatientDocumentMetadataSerializer(queryset, many=True).data,
        )

    def post(self, request):
        if request.user.role != Role.PATIENT:
            raise PermissionDenied("Only patients can upload their documents.")
        serializer = PatientDocumentUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        visit = serializer.validated_data["visit"]
        if visit.patient_id != request.user.pk:
            raise PermissionDenied("You may only upload documents to your own visit.")
        document = serializer.save(
            uploaded_by=request.user,
            size=serializer.validated_data["file"].size,
        )
        log_action(
            request,
            AuditLog.Action.DOCUMENT_UPLOADED,
            "PatientDocument",
            document.pk,
            patient=request.user,
            fields=("file",),
        )
        return Response(
            PatientDocumentMetadataSerializer(document).data,
            status=status.HTTP_201_CREATED,
        )


class PatientDocumentDownloadView(AuditProtectedRequestMixin, generics.GenericAPIView):
    serializer_class = PatientDocumentMetadataSerializer
    permission_classes = [IsPatientOrApprovedDoctor]

    @extend_schema(responses=OpenApiTypes.BINARY)
    def get(self, request, pk):
        document = get_object_or_404(
            PatientDocument.objects.select_related("visit", "visit__patient"),
            pk=pk,
        )
        if not patient_can_access_visit(request.user, document.visit):
            raise Http404
        if not default_storage.exists(document.file.name):
            raise Http404("The requested document is no longer available.")
        log_action(
            request,
            AuditLog.Action.DOCUMENT_DOWNLOADED,
            "PatientDocument",
            document.pk,
            patient=document.visit.patient,
        )
        file_handle = default_storage.open(document.file.name, "rb")
        filename = document.file.name.rsplit("/", 1)[-1]
        return FileResponse(
            file_handle,
            as_attachment=True,
            filename=filename,
            content_type=document.content_type,
        )


class ReviewCollectionView(AuditProtectedRequestMixin, generics.ListCreateAPIView):
    serializer_class = ReviewCreateSerializer
    pagination_class = DirectoryPagination

    def get_permissions(self):
        if self.request.method == "GET":
            return [AllowAny()]
        return [IsPatient()]

    def get_queryset(self):
        return Review.objects.filter(status=Review.Status.APPROVED).select_related(
            "visit__doctor__doctor_profile",
            "visit__hospital",
        )

    def get_serializer_class(self):
        if self.request.method == "GET":
            return PublicReviewSerializer
        return ReviewCreateSerializer

    def perform_create(self, serializer):
        review = serializer.save()
        log_action(
            self.request,
            AuditLog.Action.REVIEW_CREATED,
            "Review",
            review.pk,
            patient=review.visit.patient,
            fields=("rating", "text"),
        )


class ReviewReportCreateView(AuditProtectedRequestMixin, generics.CreateAPIView):
    serializer_class = ReviewReportSerializer
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "review_report"

    def create(self, request, *args, **kwargs):
        review = get_object_or_404(Review, pk=kwargs["pk"])
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if ReviewReport.objects.filter(review=review, reporter=request.user).exists():
            return Response(
                {"detail": "You have already reported this review."},
                status=status.HTTP_409_CONFLICT,
            )
        report = serializer.save(review=review, reporter=request.user)
        log_action(
            request,
            AuditLog.Action.REVIEW_REPORTED,
            "Review",
            review.pk,
            patient=review.visit.patient,
            fields=("report",),
        )
        return Response(
            {"id": report.pk, "status": "reported"},
            status=status.HTTP_201_CREATED,
        )


class AdminHospitalListCreateView(
    AuditProtectedRequestMixin,
    generics.ListCreateAPIView,
):
    serializer_class = HospitalSerializer
    permission_classes = [IsAdminRole]
    queryset = Hospital.objects.all()


class AdminDoctorQueueView(AuditProtectedRequestMixin, generics.ListAPIView):
    serializer_class = DoctorApplicationQueueSerializer
    permission_classes = [IsAdminRole]
    queryset = DoctorProfile.objects.filter(approved=False).select_related("user", "hospital")


class DoctorApprovalView(AuditProtectedRequestMixin, generics.GenericAPIView):
    serializer_class = ApprovalResultSerializer
    permission_classes = [IsAdminRole]

    @extend_schema(request=EmptySerializer, responses=ApprovalResultSerializer)
    @transaction.atomic
    def post(self, request, pk):
        profile = get_object_or_404(
            DoctorProfile.objects.select_for_update().select_related("user"),
            pk=pk,
        )
        if not profile.approved:
            profile.approved = True
            profile.save(update_fields=("approved", "updated_at"))
            User.objects.filter(pk=profile.user_id).update(role=Role.DOCTOR)
        log_action(
            request,
            AuditLog.Action.DOCTOR_APPROVED,
            "DoctorProfile",
            profile.pk,
            patient=profile.user,
            fields=("approved",),
        )
        return Response({"status": "approved"})


class AdminVisitCreateView(AuditProtectedRequestMixin, generics.CreateAPIView):
    serializer_class = AdminVisitCreateSerializer
    permission_classes = [IsAdminRole]


class AdminReviewQueueView(AuditProtectedRequestMixin, generics.ListAPIView):
    serializer_class = ReviewQueueSerializer
    permission_classes = [IsAdminRole]
    queryset = Review.objects.filter(status=Review.Status.PENDING).select_related(
        "visit__patient",
        "visit__doctor__doctor_profile",
    )


class ReviewModerationView(AuditProtectedRequestMixin, generics.GenericAPIView):
    serializer_class = ReviewModerationSerializer
    permission_classes = [IsAdminRole]

    @extend_schema(responses=ReviewModerationResultSerializer)
    @transaction.atomic
    def patch(self, request, pk):
        review = get_object_or_404(
            Review.objects.select_for_update().select_related("visit__patient"),
            pk=pk,
        )
        serializer = ReviewModerationSerializer(review, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(moderated_by=request.user, moderated_at=timezone.now())
        log_action(
            request,
            AuditLog.Action.REVIEW_MODERATED,
            "Review",
            review.pk,
            patient=review.visit.patient,
            fields=("status",),
        )
        return Response({"id": review.pk, "status": review.status})
