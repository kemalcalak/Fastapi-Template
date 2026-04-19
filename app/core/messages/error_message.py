class ErrorMessages:
    # System Errors
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    INVALID_TOKEN = "INVALID_TOKEN"
    INSUFFICIENT_PERMISSIONS = "INSUFFICIENT_PERMISSIONS"
    RESOURCE_CONFLICT = "RESOURCE_CONFLICT"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"

    # User Specific
    INVALID_ROLE = "error.user.role_invalid"
    USER_NOT_FOUND = "error.user.not_found"
    EMAIL_ALREADY_EXISTS = "error.user.email_exists"
    INVALID_CREDENTIALS = "error.user.invalid_credentials"
    INVALID_PASSWORD = "error.user.invalid_password"
    USER_INACTIVE = "error.user.user_inactive"
    EMAIL_NOT_VERIFIED = "error.user.email_not_verified"
    INVALID_VERIFICATION_TOKEN = "error.user.invalid_verification_token"
    REFRESH_TOKEN_MISSING = "error.auth.refresh_token_missing"
    INVALID_CURRENT_PASSWORD = "error.auth.invalid_current_password"
    INVALID_EMAIL_DOMAIN = "error.user.invalid_email_domain"
    DISPOSABLE_EMAIL_NOT_ALLOWED = "error.user.disposable_email_not_allowed"

    # Account deactivation / grace-period deletion
    ACCOUNT_ALREADY_DEACTIVATED = "error.account.already_deactivated"
    ACCOUNT_NOT_DEACTIVATED = "error.account.not_deactivated"
    ACCOUNT_DELETION_EXPIRED = "error.account.deletion_expired"

    # Admin
    ADMIN_CANNOT_MODIFY_SELF = "error.admin.cannot_modify_self"
    ADMIN_CANNOT_DELETE_SELF = "error.admin.cannot_delete_self"
    ADMIN_CANNOT_DEMOTE_LAST_ADMIN = "error.admin.cannot_demote_last_admin"
    ADMIN_CANNOT_DELETE_LAST_ADMIN = "error.admin.cannot_delete_last_admin"
