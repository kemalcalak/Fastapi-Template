from enum import StrEnum


class Permission(StrEnum):
    """RBAC permission keys an admin can be granted (resource:action).

    Superadmins implicitly hold every permission and bypass these checks; only
    plain ``admin`` accounts are gated by the grants stored in
    ``admin_permission``. Adding a key here is the single source of truth shared
    by the dependency guards, the ``/users/me`` payload, and the admin
    management endpoints.
    """

    USERS_READ = "users:read"
    USERS_WRITE = "users:write"
    USERS_ROLE = "users:role"
    USERS_DELETE = "users:delete"
    USERS_SUSPEND = "users:suspend"
    USERS_PASSWORD_RESET = "users:password_reset"
    FILES_READ = "files:read"
    FILES_DELETE = "files:delete"
    SUPPORT_READ = "support:read"
    SUPPORT_WRITE = "support:write"
    SUPPORT_UPDATE = "support:update"
    ACTIVITIES_READ = "activities:read"
    STATS_READ = "stats:read"
