"""Request-local branch isolation for all branch-owned business records."""

from contextvars import ContextVar

from django.db import models
from django.core.exceptions import ValidationError


_UNSET = object()
_current_branch_id = ContextVar("current_branch_id", default=_UNSET)


def set_current_branch(branch_id):
    """Set a branch id, or ``None`` for an explicitly unscoped superuser request."""
    return _current_branch_id.set(branch_id)


def reset_current_branch(token):
    _current_branch_id.reset(token)


def get_current_branch_id():
    value = _current_branch_id.get()
    return None if value is _UNSET else value


def branch_context_is_set():
    return _current_branch_id.get() is not _UNSET


def get_default_branch_id():
    """Return/create the compatibility branch used outside an HTTP request."""
    from django.apps import apps

    Branch = apps.get_model("accounts", "Branch")
    branch, _ = Branch.objects.get_or_create(
        code="MAIN",
        defaults={"name": "المعرض الرئيسي", "is_active": True},
    )
    return branch.pk


class BranchQuerySet(models.QuerySet):
    def for_branch(self, branch):
        return self.filter(branch=branch)

    def all_branches(self):
        return self.model.all_objects.all()


class BranchManager(models.Manager.from_queryset(BranchQuerySet)):
    """Automatically scopes normal ORM access to the active request branch."""

    def get_queryset(self):
        queryset = super().get_queryset()
        if branch_context_is_set():
            branch_id = get_current_branch_id()
            if branch_id is not None:
                queryset = queryset.filter(branch_id=branch_id)
        return queryset


class BranchOwnedModel(models.Model):
    branch_relations = ()
    branch = models.ForeignKey(
        "accounts.Branch",
        on_delete=models.PROTECT,
        related_name="%(app_label)s_%(class)s_records",
        db_index=True,
        default=get_default_branch_id,
    )

    objects = BranchManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True
        base_manager_name = "all_objects"
        default_manager_name = "objects"

    def infer_branch_id(self):
        """Child models may override this to inherit their parent's branch."""
        return None

    def save(self, *args, **kwargs):
        if not self.branch_id:
            self.branch_id = self.infer_branch_id() or get_current_branch_id()
            if not self.branch_id:
                if branch_context_is_set():
                    raise ValidationError({"branch": "اختر معرضًا أولًا قبل إنشاء البيانات."})
                self.branch_id = get_default_branch_id()
        errors = {}
        for relation_name in self.branch_relations:
            relation_id = getattr(self, f"{relation_name}_id", None)
            if not relation_id:
                continue
            field = self._meta.get_field(relation_name)
            related_model = field.remote_field.model
            if related_model._meta.label_lower == "accounts.user":
                matches = related_model.objects.filter(pk=relation_id, branch_id=self.branch_id).exists()
            elif hasattr(related_model, "all_objects"):
                matches = related_model.all_objects.filter(pk=relation_id, branch_id=self.branch_id).exists()
            else:
                continue
            if not matches:
                errors[relation_name] = "لا يمكن ربط بيانات من معرض مختلف."
        if errors:
            raise ValidationError(errors)
        return super().save(*args, **kwargs)
