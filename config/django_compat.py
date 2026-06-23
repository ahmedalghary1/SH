from django.db import models


def check_constraint(*, check, name, **kwargs):
    try:
        return models.CheckConstraint(check=check, name=name, **kwargs)
    except TypeError as exc:
        if "unexpected keyword argument 'check'" not in str(exc):
            raise
        return models.CheckConstraint(condition=check, name=name, **kwargs)
