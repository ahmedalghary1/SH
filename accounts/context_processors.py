from .models import Branch


def branch_context(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    return {
        "active_branch": getattr(request, "active_branch", None),
        "available_branches": Branch.objects.filter(is_active=True).order_by("name")
        if request.user.is_superuser
        else Branch.objects.filter(pk=request.user.branch_id),
    }
