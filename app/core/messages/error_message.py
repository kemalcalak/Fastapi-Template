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
    INVALID_PASSWORD = "error.user.invalid_password"
    USER_INACTIVE = "error.user.user_inactive"
    REFRESH_TOKEN_MISSING = "error.auth.refresh_token_missing"
