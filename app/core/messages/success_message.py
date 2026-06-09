class SuccessMessages:
    # User Specific
    USER_CREATED = "success.user.created"
    USER_UPDATED = "success.user.updated"
    EMAIL_VERIFIED = "success.user.email_verified"
    VERIFICATION_EMAIL_SENT = "success.user.verification_email_sent"

    # Auth Specific
    LOGIN_SUCCESS = "success.auth.login"
    PASSWORD_RESET_SENT = "success.auth.password_reset_sent"
    PASSWORD_RESET_SUCCESS = "success.auth.password_reset_success"
    PASSWORD_CHANGE_SUCCESS = "success.auth.password_change_success"
    LOGOUT_SUCCESS = "success.auth.logout_success"
    REGISTER_SUCCESS = "success.auth.register_success"

    # Account deactivation / grace-period deletion
    ACCOUNT_DEACTIVATED = "success.account.deactivated"
    ACCOUNT_REACTIVATED = "success.account.reactivated"

    # Admin
    ADMIN_USER_UPDATED = "success.admin.user_updated"
    ADMIN_USER_SUSPENDED = "success.admin.user_suspended"
    ADMIN_USER_UNSUSPENDED = "success.admin.user_unsuspended"
    ADMIN_USER_DELETED = "success.admin.user_deleted"
    ADMIN_PASSWORD_CHANGED = "success.admin.password_changed"

    # RBAC / admin management
    ADMIN_CREATED = "success.admin.created"
    ADMIN_ACCOUNT_DELETED = "success.admin.account_deleted"
    SUPERADMIN_PROMOTED = "success.admin.superadmin_promoted"
    SUPERADMIN_DEMOTED = "success.admin.superadmin_demoted"
    ADMIN_PERMISSIONS_UPDATED = "success.admin.permissions_updated"
    ROOT_TRANSFER_INITIATED = "success.admin.root_transfer_initiated"
    ROOT_TRANSFERRED = "success.admin.root_transferred"

    # File / upload
    FILE_UPLOADED = "success.file.uploaded"
    ADMIN_FILE_DELETED = "success.admin.file_deleted"

    # Support / tickets
    TICKET_CREATED = "success.support.ticket_created"
    TICKET_CLOSED = "success.support.ticket_closed"
    TICKET_MESSAGE_SENT = "success.support.message_sent"
    ADMIN_TICKET_UPDATED = "success.support.admin_ticket_updated"
    ADMIN_TICKET_REPLIED = "success.support.admin_ticket_replied"
