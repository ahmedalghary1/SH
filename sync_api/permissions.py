def can_use_sync_api(user):
    return bool(user and user.is_authenticated and user.is_active)
