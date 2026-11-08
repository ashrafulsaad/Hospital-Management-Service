from .models import AuditLog
from .services import log_action


class AuditProtectedRequestMixin:
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        user = request.user
        if (
            response.status_code < 300
            and user.is_authenticated
            and not getattr(request, "_audit_logged", False)
        ):
            log_action(
                request,
                AuditLog.Action.API_ACCESS,
                "API",
                request.path,
            )
        return response
