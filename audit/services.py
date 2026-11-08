from .models import AuditLog


def log_action(
    request,
    action,
    resource_type,
    resource_id,
    patient=None,
    fields=None,
    actor=None,
):
    """Write one audit entry. `fields` = names of changed fields, never values."""
    user = actor
    if user is None and request.user.is_authenticated:
        user = request.user
    if user and getattr(request, "_audit_logged", False):
        return None
    if user:
        request._audit_logged = True
    if patient is None and user and user.role == "patient":
        patient = user
    return AuditLog.objects.create(
        actor=user,
        actor_role=user.role if user else "",
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        patient=patient,
        ip=request.META.get("REMOTE_ADDR"),
        metadata={"fields": sorted(fields)} if fields else {},
    )
